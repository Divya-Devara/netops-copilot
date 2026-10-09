import asyncio
import json
import os
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from langgraph.types import Command

from netops.agents.graph import graph, llm, fast_llm, AUDIT_FILE, EVENT_SINKS
from netops.tools import faults, health

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
    monitor = asyncio.create_task(health_monitor())
    yield
    monitor.cancel()

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
    "answer":   {"pipe": "diagnose", "mode": "scan",   "detail": "Investigating the network..."},
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

# ── live health monitor: polls the lab and pushes changes to every connected UI ──
HEALTH_INTERVAL = float(os.environ.get("NETOPS_HEALTH_INTERVAL", "10"))
CLIENTS: set[WebSocket] = set()
_health: dict = {}

async def broadcast(payload: dict):
    for ws in list(CLIENTS):
        try:
            await ws.send_json(payload)
        except Exception:
            CLIENTS.discard(ws)

async def refresh_health():
    """Poll once; broadcast the new state plus which issues appeared/cleared since the last poll."""
    global _health
    try:
        new = await asyncio.to_thread(health.check_health)
    except Exception as e:
        print(f"[health] poll failed: {e}")
        return
    old = set(_health.get("issues", [])) if _health else None
    cur = set(new["issues"])
    appeared = sorted(cur - old) if old is not None else []     # first poll is a baseline, not an alert
    cleared = sorted(old - cur) if old is not None else []
    changed = new != _health
    _health = new
    if changed:
        await broadcast({"type": "health", **new, "appeared": appeared, "cleared": cleared, "ts": time.time()})

async def health_monitor():
    while True:
        await refresh_health()
        await asyncio.sleep(HEALTH_INTERVAL)

def _check_origin(request: Request):
    origin = request.headers.get("origin")
    if origin is not None and origin not in ALLOWED_ORIGINS:
        raise HTTPException(403, "Origin not allowed")

@app.get("/api/faults")
def list_faults(request: Request):
    _check_origin(request)
    return faults.catalog()

@app.post("/api/faults/reset")
async def reset_faults(request: Request):
    _check_origin(request)
    undone = await asyncio.to_thread(faults.reset)
    await asyncio.sleep(2)           # let routing settle before re-polling
    await refresh_health()
    return {"reset": undone}

@app.post("/api/faults/{fault_id}/inject")
async def inject_fault(fault_id: str, request: Request):
    _check_origin(request)
    if fault_id not in faults.FAULTS:
        raise HTTPException(404, "Unknown fault")
    try:
        res = await asyncio.to_thread(faults.inject, fault_id)
    except Exception as e:
        raise HTTPException(500, f"Injection failed: {e}")
    await asyncio.sleep(2)
    await refresh_health()
    return res

@app.get("/api/audit")
def audit(request: Request, limit: int = 40):
    """Most recent finished runs from the audit log (newest first)."""
    _check_origin(request)
    if not os.path.exists(AUDIT_FILE):
        return []
    with open(AUDIT_FILE, "rb") as f:                 # read only the tail: the log grows forever
        f.seek(0, os.SEEK_END)
        f.seek(max(0, f.tell() - 2_000_000))
        lines = f.read().decode("utf-8", "ignore").splitlines()[1:]
    runs = []
    for line in reversed(lines):
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get("type") == "run_end":
            plan = e.get("plan") or {}
            runs.append({"ts": e["ts"], "run_id": e["run_id"], "outcome": e.get("outcome"), "intent": e.get("intent"),
                         "routers": sorted({c["router"] for c in plan.get("changes", [])}), "risk": plan.get("risk"),
                         "twin_ok": (e.get("twin") or {}).get("ok"), "approved": e.get("approved")})
            if len(runs) >= min(max(limit, 1), 200):
                break
    return runs

_locks: dict[str, asyncio.Lock] = {}

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    origin = websocket.headers.get("origin")
    if origin is not None and origin not in ALLOWED_ORIGINS:
        await websocket.close(code=1008)
        return
    await websocket.accept()
    CLIENTS.add(websocket)
    await websocket.send_json({"type": "hello", "boot_id": BOOT_ID})
    if _health:
        await websocket.send_json({"type": "health", **_health, "appeared": [], "cleared": [], "ts": time.time()})

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
    finally:
        CLIENTS.discard(websocket)

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
        evidence = [{"tool": e["tool"], "args": e["args"], "output": str(e["output"])[:1500]}
                    for e in values.get("evidence") or []]
        return {"outcome": "answer", "text": values.get("answer", ""), "evidence": evidence,
                "citations": values.get("citations") or []}
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
    # tool-progress events come from the Q&A agent's worker thread; forward them to the browser as they happen
    thread_id = config["configurable"]["thread_id"]
    loop, events = asyncio.get_running_loop(), asyncio.Queue()
    EVENT_SINKS[thread_id] = lambda ev: loop.call_soon_threadsafe(events.put_nowait, ev)

    async def pump():
        while True:
            await ws.send_json(await events.get())
    pump_task = asyncio.create_task(pump())
    try:
        await send_stage(ws, "classify" if isinstance(input_data, dict) else "apply", "running")

        async for chunk in graph.astream(input_data, config, stream_mode="updates"):
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

        await asyncio.sleep(0)                      # let the pump forward the last tool events before the final answer
        while not events.empty():
            await ws.send_json(events.get_nowait())
        values = (await graph.aget_state(config)).values
        await ws.send_json({"type": "final", **final_message(values)})

    except WebSocketDisconnect:
        raise
    except Exception as e:
        await ws.send_json({"type": "final", "outcome": "error", "text": f"Error: {e}"})
    finally:
        EVENT_SINKS.pop(thread_id, None)
        pump_task.cancel()
