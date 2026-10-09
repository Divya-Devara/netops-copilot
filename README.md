# NetOps Copilot

An AI assistant for an [FRRouting](https://frrouting.org/) lab. Ask anything about the network in plain English, or
ask it to change something. Questions are answered from live evidence; changes pass through safety gates and need your
approval before they touch a router.

A 3D view of the lab shows router health live, highlights the router the agent is working on, and turns broken links red.

## What it does

- **Answers any network question.** A read-only agent picks its own tools: `show` commands, ping, traceroute, running
  config, link diagnosis (compares both ends of a link), network health, what-if analysis and RFC/FRR documentation search.
  Every answer lists the tool calls it was based on, and cited sources are verified.
- **Changes the network safely.** `classify -> diagnose -> plan -> policy -> reviewer -> digital twin -> human approval
  -> apply -> verify -> rollback on failure`. The question agent has no tool that can modify a router.
- **Monitors the lab.** The backend polls OSPF adjacencies and BGP sessions and pushes problems to the UI.
- **Demo-ready failure injection.** Break a link or add a subtle misconfiguration from the UI, then let the agent find
  and fix it.
- **Audit trail.** Every run is recorded in `audit.jsonl` and shown in the History tab.

## Architecture

```
React + three.js UI  <--WebSocket / REST-->  FastAPI (backend/server.py)
 (frontend/)                                        |
                                              LangGraph agents (netops/agents)
                                                    |
        Ollama LLM  |  RAG over RFC/FRR docs  |  safety gates (netops/safety)  |  tools (netops/tools)
                                                    |
                                  Containerlab FRR lab (lab/)  +  digital twin
```

| Path | Contents |
|---|---|
| `backend/server.py` | WebSocket chat, health monitor, fault and audit REST endpoints |
| `netops/agents/` | LangGraph graph, Q&A agent, planner, reviewer, prompts |
| `netops/tools/` | FRR access, health, link diagnosis, topology/what-if, fault injection |
| `netops/safety/` | Policy rules and the digital twin |
| `netops/rag/` | Document ingestion and hybrid (vector + BM25) retrieval |
| `lab/` | Containerlab topology (6 routers, AS 65001/65002/65003) and configs |
| `frontend/` | React UI with the 3D scene, chat, lab-control panel and 3 colour themes |
| `tests/`, `evals/` | Unit/integration tests and evaluation scenarios |
| `docs/` | Change notes per phase (see `docs/PHASE8_CHANGES.md`) |

`api.py` is the older REST-only entry point; the UI uses `backend/server.py`.

## Requirements

- Linux with Docker and [Containerlab](https://containerlab.dev/)
- [Ollama](https://ollama.com/) with a model pulled (default `qwen2.5:7b`; a larger model follows tools more reliably)
- Python 3.10+ and Node.js 18+

## Setup

```bash
# Python environment
python3 -m venv .venv && source .venv/bin/activate
pip install fastapi "uvicorn[standard]" websockets pydantic langgraph langchain-ollama \
            chromadb sentence-transformers rank_bm25 pytest      # no requirements.txt yet

# Model
ollama pull qwen2.5:7b

# Lab (container names are clab-netops-r1 ... r6)
sudo containerlab deploy -t lab/topology.clab.yml

# Frontend
cd frontend && npm install
```

## Run

```bash
# terminal 1: backend
source .venv/bin/activate
uvicorn backend.server:app --host localhost --port 8000

# terminal 2: frontend
cd frontend && npm run dev          # http://localhost:5173
```

Open `http://localhost:5173` (this exact origin is allowed by default).

## Try it

1. "What is wrong with the network right now?"
2. "Why is the OSPF adjacency between r1 and r2 down?"
3. "What happens if r2 goes down?"
4. "Ping 6.6.6.6 from r5"
5. "How does OSPF DR election work?"
6. "Set OSPF cost on r1 eth1 to 100" (goes through the approval gates)

The shipped lab starts with two faults on purpose: r1 `eth1` is in OSPF area 0 while r2 `eth1` is in area 1, and r1 expects
r5 to be AS 65099 while r5 runs AS 65002. The monitor reports both from the start.

**Failure demo:** open **Lab control > Break**, inject "Cut link r2-r4", watch the alert and the red link, click
**Investigate**, then ask the agent to bring the link back up and approve the change. Use **Reset injected faults**
afterwards (OSPF takes about 30 s to re-form).

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `NETOPS_MODEL` | `qwen2.5:7b` | Main LLM (planning, Q&A agent) |
| `NETOPS_FAST_MODEL` | same as main | Small model for classification |
| `NETOPS_REVIEWER_MODEL` | same as main | Model for the change reviewer |
| `NETOPS_NUM_GPU` | `0` (CPU) | GPU layers for Ollama; empty lets Ollama decide |
| `NETOPS_HEALTH_INTERVAL` | `10` | Seconds between health polls |
| `NETOPS_ALLOWED_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | Origins allowed for WebSocket and REST |
| `NETOPS_TWIN_PERSIST` | off | Set to `1` to keep the digital-twin lab running between runs |
| `VITE_WS_URL` / `VITE_API_URL` | `ws://localhost:8000/ws` / derived | Backend address for the UI |

## Tests

```bash
python -m pytest tests/test_qa_agent.py -q      # fast, no lab or LLM needed
python -m pytest tests -q                       # full suite: needs the lab, Ollama and a few minutes
```

Four older tests currently fail because they assume a healthy lab or depend on the local 7B planner (they fail the same
way on the commit before Phase 8); see `docs/PHASE8_CHANGES.md`.

## Safety model

- The Q&A agent is read-only; `show` commands are validated and ping/traceroute accept plain IP addresses only.
- Every change is policy-checked, reviewed by a second LLM pass, tested in a digital twin, and approved by a human.
- The executor re-validates the approved plan, snapshots configs, applies, verifies, and rolls back on failure.
- Router output and documents are treated as untrusted data, and cited sources must have been retrieved in the same run.
- The WebSocket and REST endpoints check the browser `Origin`.

## Limitations

- Answer quality depends on the local model; on CPU, tool-using answers take roughly 10 to 60 seconds.
- `what_if_down` is a hop-count topology model, not a simulation of FRR.
- The lab is an FRR/Containerlab environment; it is not wired to real hardware.
