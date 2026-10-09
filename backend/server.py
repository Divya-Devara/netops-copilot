import asyncio
import json
import os
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from langgraph.types import Command

from netops.agents.graph import graph, llm, fast_llm

# Origins allowed to use the API. CORS does not protect WebSockets, so /ws checks Origin itself:
# otherwise any web page open in the operator's browser could drive (and approve!) changes.
ALLOWED_ORIGINS = [o.strip() for o in os.environ.get(
    "NETOPS_ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if o.strip()]

def _warm_up():
    """Pay the one-off model-load costs at startup instead of on the first user request."""
    try:
        from netops.rag.retrieve import search_docs
        search_docs("ospf", k=1)          # loads embedding model + Chroma + BM25 (~8s cold)
    except Exception as e:
        print(f"[warmup] rag failed: {e}")
    try:
        fast_llm().invoke("ok")           # makes Ollama load the models into memory
        llm().invoke("ok")
    except Exception as e:
        print(f"[warmup] llm failed: {e}")

@asynccontextmanager
async def lifespan(app):
    asyncio.create_task(asyncio.to_thread(_warm_up))  # don't block startup
    yield

app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Changes on every backend start. The UI compares it to detect a restart
# (an in-memory checkpointer forgets everything when the process restarts).
BOOT_ID = str(uuid.uuid4())

# ── pipeline stages shown in the UI ──
NODES = {
    "classify": {"pipe": "classify", "mode": "scan",   "detail": "Classifying intent..."},
    "diagnose": {"pipe": "diagnose", "mode": "scan",   "detail": "Reading network state..."},
    "plan":     {"pipe": "plan",     "mode": "plan",   "detail": "Drafting configuration changes..."},
    "policy":   {"pipe": "policy",   "mode": "twin",   "gate": "policy",   "detail": "Checking policy constraints..."},
    "review":   {"pipe": "review",   "mode": "plan",   "gate": "reviewer", "detail": "Critiquing blast radius..."},
    "twin":     {"pipe": "twin",     "mode": "twin",   "gate": "twin",     "detail": "Simulating in Digital Twin..."},
    "approval": {"pipe": "approve",  "mode": "plan",   "detail": "Awaiting human approval..."},
    "apply":    {"pipe": "apply",    "mode": "apply",  "detail": "Applying config to live lab..."},
    "verify":   {"pipe": "verify",   "mode": "verify", "detail": "Verifying OSPF/BGP states..."},
}
# Which stage starts after each one (dry_run is internal, so review hands straight to twin)
NEXT_MAP = {"classify": "diagnose", "diagnose": "plan", "plan": "policy", "policy": "review",
            "review": "twin", "twin": "approval", "approval": "apply", "apply": "verify"}

# Does this node's update mean its gate failed?
GATE_FAILED = {
    "policy": lambda st: st.get("policy_result", {}).get("allowed") is False,
    "review": lambda st: st.get("review_result", {}).get("approve") is False,
    "twin":   lambda st: st.get("twin_result", {}).get("ok") is False,
}

def serialize(obj):
    return obj.model_dump() if hasattr(obj, "model_dump") else obj

def plan_routers(plan) -> list[str]:
    plan = serialize(plan) or {}
    seen = []
    for c in plan.get("changes", []):
        if c["router"] not in seen:
            seen.append(c["router"])
    return seen

_locks: dict[str, asyncio.Lock] = {}

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    origin = websocket.headers.get("origin")
    if origin is not None and origin not in ALLOWED_ORIGINS:
        await websocket.close(code=1008)
        return
    await websocket.accept()
    await websocket.send_json({"type": "hello", "boot_id": BOOT_ID})

    fallback_thread = str(uuid.uuid4())
    try:
        while True:
            msg = json.loads(await websocket.receive_text())
            # The browser's thread_id lets a page refresh continue the same LangGraph conversation
            thread_id = msg.get("thread_id") or fallback_thread
            config = {"configurable": {"thread_id": thread_id}}

            lock = _locks.setdefault(thread_id, asyncio.Lock())
            if lock.locked():
                await websocket.send_json({"type": "final", "outcome": "error",
                                           "text": "A run is already in progress for this session."})
                continue
            async with lock:
                if msg["type"] == "intent":
                    await process_graph(websocket, {"intent": msg["text"]}, config)
                elif msg["type"] == "decision":
                    await process_graph(websocket, Command(resume=msg["value"]), config)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await websocket.send_json({"type": "final", "outcome": "error", "text": str(e)})
        except Exception:
            pass

async def send_stage(ws, node, status, routers=None, gate_status="null"):
    cfg = NODES.get(node)
    if not cfg:
        return
    await ws.send_json({
        "type": "stage", "node": cfg["pipe"], "status": status, "mode": cfg["mode"],
        "routers": routers or ["r1"], "gate": cfg.get("gate", "null"),
        "gate_status": gate_status, "detail": cfg["detail"],
    })

def final_message(values: dict) -> dict:
    """Translate the graph's final state into the single 'final' message the UI shows."""
    outcome = values.get("outcome")
    if outcome == "answer":
        return {"outcome": "answer", "text": values.get("answer", "")}
    if outcome in ("blocked", "no_change"):
        return {"outcome": "blocked" if outcome == "blocked" else "answer", "text": values.get("blocked_reason", "Blocked.")}
    if outcome == "rejected":
        return {"outcome": "rejected", "text": "Change rejected. Network untouched."}
    if outcome == "applied":
        return {"outcome": "applied", "text": "Applied and verified on the live lab."}
    if outcome == "rolled_back":
        why = values.get("apply_error") or "Post-change verification failed."
        if values.get("rollback_ok"):
            return {"outcome": "rolled_back", "text": f"{why} Rolled back; config matches the pre-change snapshot."}
        return {"outcome": "error", "text": f"{why} ROLLBACK DID NOT FULLY RESTORE THE CONFIG. Manual check needed."}
    return {"outcome": "error", "text": "The run ended without a result."}

async def process_graph(ws: WebSocket, input_data, config):
    routers, kind = ["r1"], None
    try:
        await send_stage(ws, "classify" if isinstance(input_data, dict) else "apply", "running")

        async for mode, chunk in graph.astream(input_data, config, stream_mode=["updates", "messages"]):
            if mode == "messages":
                # Stream the read-only answer to the UI as it is generated
                token, meta = chunk
                if meta.get("langgraph_node") == "answer" and isinstance(token.content, str) and token.content:
                    await ws.send_json({"type": "token", "text": token.content})
                continue
            if "__interrupt__" in chunk:
                data = chunk["__interrupt__"][0].value
                await ws.send_json({
                    "type": "approval_request",
                    "plan": serialize(data.get("plan", {"rationale": "N/A", "risk": "unknown"})),
                    "diffs": data.get("diffs", {}),
                    "review": data.get("review"),
                    "policy": data.get("policy"),
                    "twin": data.get("twin"),
                })
                return

            for node_name, state in chunk.items():
                if node_name not in NODES or not isinstance(state, dict):
                    continue
                kind = state.get("kind", kind)
                if state.get("plan"):
                    routers = plan_routers(state["plan"]) or routers

                if GATE_FAILED.get(node_name, lambda st: False)(state):
                    await send_stage(ws, node_name, "failed", routers, "fail")
                    await send_stage(ws, "plan", "running", routers)  # a retry (if any) goes back to the planner
                    continue

                await send_stage(ws, node_name, "done", routers, "pass" if NODES[node_name].get("gate") else "null")
                if node_name in NEXT_MAP and not (node_name == "diagnose" and kind == "question"):
                    await send_stage(ws, NEXT_MAP[node_name], "running", routers)

        values = (await graph.aget_state(config)).values
        await ws.send_json({"type": "final", **final_message(values)})

    except WebSocketDisconnect:
        raise
    except Exception as e:
        await ws.send_json({"type": "final", "outcome": "error", "text": f"Error: {e}"})
