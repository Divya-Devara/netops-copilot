import json
import uuid
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from langgraph.types import Command

# 1. IMPORT YOUR REAL GRAPH HERE
from netops.agents.graph import graph

app = FastAPI()

# Allow your React app to communicate with FastAPI
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------
# 2. WEBSOCKET PROTOCOL & STATE TRANSLATION
# ---------------------------------------------------------
NODES = {
    "classify": {"pipe": "classify", "mode": "scan",   "detail": "Classifying intent..."},
    "diagnose": {"pipe": "diagnose", "mode": "scan",   "detail": "Reading network state..."},
    "plan":     {"pipe": "plan",     "mode": "plan",   "detail": "Drafting configuration changes..."},
    "review":   {"pipe": "review",   "mode": "plan",   "gate": "reviewer", "detail": "Critiquing blast radius..."},
    "policy":   {"pipe": "policy",   "mode": "twin",   "gate": "policy",   "detail": "Checking policy constraints..."},
    "twin":     {"pipe": "twin",     "mode": "twin",   "gate": "twin",     "detail": "Simulating in Digital Twin..."},
    "approval": {"pipe": "approve",  "mode": "plan",   "detail": "Awaiting human approval..."},
    "apply":    {"pipe": "apply",    "mode": "apply",  "detail": "Applying config to live lab..."},
    "verify":   {"pipe": "verify",   "mode": "verify", "detail": "Verifying OSPF/BGP states..."},
}

NEXT_MAP = {"classify": "diagnose", "diagnose": "plan", "plan": "review", "review": "policy", 
            "policy": "twin", "twin": "approval", "approval": "apply", "apply": "verify"}

def serialize(obj):
    return obj.model_dump() if hasattr(obj, "model_dump") else obj

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    try:
        while True:
            msg = json.loads(await websocket.receive_text())
            if msg["type"] == "intent":
                await process_graph(websocket, {"intent": msg["text"]}, config)
            elif msg["type"] == "decision":
                await process_graph(websocket, Command(resume=msg["value"]), config)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        await websocket.send_json({"type": "final", "outcome": "error", "text": str(e)})

async def send_stage(ws, node, status, routers=None, gate_status="null"):
    cfg = NODES.get(node)
    if not cfg: return
    await ws.send_json({
        "type": "stage", "node": cfg["pipe"], "status": status, "mode": cfg["mode"],
        "routers": routers or ["r1"], "gate": cfg.get("gate", "null"),
        "gate_status": gate_status, "detail": cfg["detail"]
    })

async def process_graph(ws: WebSocket, input_data, config):
    try:
        if isinstance(input_data, dict):
            await send_stage(ws, "classify", "running")
        else:
            await send_stage(ws, "apply", "running")

        async for chunk in graph.astream(input_data, config, stream_mode="updates"):
            
            if "__interrupt__" in chunk:
                data = chunk["__interrupt__"][0].value
                await ws.send_json({
                    "type": "approval_request",
                    "plan": serialize(data.get("plan", {"rationale": "N/A", "risk": "unknown"})),
                    "diffs": data.get("diffs", {})
                })
                return

            for node_name, state in chunk.items():
                # 1. Listen for the actual answer from the LLM, no matter which node generates it
                if "answer" in state and state["answer"]:
                    await ws.send_json({"type": "final", "outcome": "answer", "text": state["answer"]})
                    return

                # Skip UI updates for internal LangGraph nodes we don't track
                if node_name not in NODES: 
                    continue

                routers = [c.get("router", "r1") for c in state.get("plan", {}).get("changes", [])] if isinstance(state.get("plan"), dict) else ["r1"]

                # 2. Handle Safety Gates
                gate_fail, reason = False, ""
                if node_name == "policy" and state.get("policy_allowed") is False:
                    gate_fail, reason = True, "Blocked by Policy-as-Code rules."
                elif node_name == "twin" and state.get("ok") is False:
                    gate_fail, reason = True, "Failed Digital Twin dry-run."
                elif node_name == "review" and state.get("ok") is False:
                    gate_fail, reason = True, "Blocked by Reviewer."

                if gate_fail:
                    await send_stage(ws, node_name, "failed", routers, "fail")
                    await ws.send_json({"type": "final", "outcome": "blocked", "text": reason})
                    return
                
                gate_type = "pass" if NODES[node_name].get("gate") else "null"
                await send_stage(ws, node_name, "done", routers, gate_type)

                # 3. Terminal states
                if node_name == "verify":
                    if state.get("ok", True):
                        await ws.send_json({"type": "final", "outcome": "applied", "text": "Applied and verified on the live lab."})
                    else:
                        await ws.send_json({"type": "final", "outcome": "rolled_back", "text": "Verification failed. Rolled back."})
                    return
                elif node_name == "approval" and state.get("ok") is False:
                    await ws.send_json({"type": "final", "outcome": "rejected", "text": "Change rejected. Network untouched."})
                    return

                # 4. Auto-advance UI state
                if node_name in NEXT_MAP:
                    await send_stage(ws, NEXT_MAP[node_name], "running", routers)

        # Catch if the graph finishes naturally without returning a final state above
        final_state = graph.get_state(config).values
        if "answer" in final_state and final_state["answer"]:
            await ws.send_json({"type": "final", "outcome": "answer", "text": final_state["answer"]})

    except Exception as e:
        await ws.send_json({"type": "final", "outcome": "error", "text": f"Error: {str(e)}"})