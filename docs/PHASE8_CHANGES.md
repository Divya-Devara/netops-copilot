# Phase 8: UI overhaul, tool-using agent, live monitoring, failure injection

This document records what changed in this phase, why, how to run it, and what is known to be limited.
Everything below was added on top of commit `1cbfa85` (branch `phase7-frontend`).

## 1. Summary

| Area | Before | After |
|---|---|---|
| Questions the agent can answer | Only what a fixed snapshot (OSPF/BGP summary of all routers + 3 RAG passages) happened to contain | Any network question: a read-only agent chooses its own tools (show, ping, traceroute, config, health, link diagnosis, what-if, docs) |
| Router in the 3D scene | Abstract wireframe sphere and rings | Rack-style device with blinking port LEDs; router symbol (core) or globe (external AS); labels, legend, zones, link labels with subnets |
| Colours | One hard-coded dark theme | Three themes (Aurora, Cyber amber, Mission control light), switchable, remembered per browser |
| Lab health | Not visible unless you asked | Backend polls the lab every 10 s and pushes problems to the UI; broken links turn red in the 3D scene |
| Demo / testing | Manual `docker exec` | "Lab control" panel: inject faults, reset them, see live monitor events and the audit history |
| Explainability | Answer text only | Every answer lists the tool calls and outputs it was based on; citations are verified |

Safety design is unchanged: the new agent has **no tool that can modify a router**. Changes still go through
plan, policy, reviewer, digital twin, human approval, apply, verify and rollback.

## 2. Backend

### 2.1 Tool-using Q&A agent (`netops/agents/qa_agent.py`, new)
* Replaces the old "snapshot, then one LLM call" answer node. The question path is now
  `classify -> answer` (the `diagnose` snapshot step is only used on the change path).
* Tools (all read-only): `show_command`, `ping`, `traceroute`, `get_running_config`, `diagnose_link`,
  `network_health`, `what_if_down`, `search_docs_tool`. A unit test asserts this exact set.
* Loop: up to 6 tool rounds, then a forced final answer from the gathered evidence.
* Robustness measures added for the local 7B model (measured while building this):
  * **Nudge**: if a question about this network is answered with zero tool calls (or the model narrates
    "let's run X"), it is told once to call a tool.
  * **Tool calls printed as text** (JSON in a code fence) are recovered and executed.
  * **Pre-retrieval for concept questions** ("How does OSPF DR election work?"): docs are fetched up front.
  * **Pre-diagnosis for link questions** (two adjacent routers, or r5/r6): `diagnose_link` runs first and its
    output is given to the model as evidence.
  * **Follow-ups** ("and from r2?") are rewritten into standalone questions; the rewrite is validated
    (may only mention routers the user wrote and must keep the follow-up's own routers), otherwise the original
    text is used. History is only used for short follow-ups.
* **Citation gate** (kept from before, now tolerant of noise): a cited SOURCE ID must have been returned by
  `search_docs` in the same run; unverifiable citations are removed and reported.
* **Grounding flag**: a network question answered with no evidence gets an explicit caution appended.
* Conversation memory: last 3 turns kept in graph state (per thread).
* Model: `NETOPS_MODEL` (default `qwen2.5:7b`). A larger model will follow tools more reliably.

### 2.2 Safer classification (`netops/agents/graph.py`)
* The regex fast path now covers more question words (which/is/are/does/can/list/check/ping/trace...) but is skipped
  when the text contains a change verb (set/add/remove/enable/shutdown/fix/...). Those go to the LLM classifier,
  which fails closed to "question" (read-only).

### 2.3 New tool modules (`netops/tools/`)
| File | Purpose |
|---|---|
| `topology.py` | Static model of the lab (routers, links, subnets, interfaces). `what_if_down()` predicts rerouting/connectivity loss for a router or link failure (hop-count model; ignores OSPF costs and BGP policy, and says so). |
| `health.py` | `collect()` + pure `analyze()`: per-router, per-link and per-session health from `show` output. |
| `linkdiag.py` | Pure config comparison for both ends of a link: OSPF area / hello / dead / network-type mismatch, passive, shutdown, subnet mismatch; BGP AS-number mismatch, missing neighbor statements, `neighbor ... shutdown`. |
| `faults.py` | Failure injection with exact undo commands (see 2.5). |
| `frr.py` (extended) | Strict `ping` and `traceroute` (plain IP only, no flag/shell injection, bounded count). |

### 2.4 Server (`backend/server.py`)
* **Live health monitor**: background task polls every `NETOPS_HEALTH_INTERVAL` seconds (default 10), broadcasts a
  `health` message when state changes (with `appeared` / `cleared` issue lists). New clients get the latest state on connect.
* **Tool progress events**: while the Q&A agent runs, `tool` / `tool_result` messages stream to the browser.
  Implemented with a per-session event sink (`EVENT_SINKS` in `graph.py`) because LangGraph's stream writer
  fails inside async runs on Python 3.10.
* `final` messages for answers now carry `evidence` (tool, args, output truncated to 1500 chars) and verified `citations`.
* REST endpoints (Origin-checked like the WebSocket, because CORS does not stop cross-site POSTs):
  * `GET  /api/faults`, `POST /api/faults/{id}/inject`, `POST /api/faults/reset`
  * `GET  /api/audit?limit=N` (newest finished runs, reads only the tail of `audit.jsonl`)

### 2.5 Failure injection
Out-of-band on purpose: it simulates the world breaking, and the agent must then notice and fix it.

| id | Effect | Undo |
|---|---|---|
| `link_r2_r4` | shut r2 eth2 | `no shutdown` |
| `link_r1_r3` | shut r3 eth1 | `no shutdown` |
| `bgp_r1_r5` | `neighbor 10.1.15.2 shutdown` on r1 | `no neighbor ... shutdown` |
| `passive_r3` | `passive-interface eth2` on r3 (subtle misconfig) | `no passive-interface eth2` |

Note: undoing `passive_r3` leaves an explicit `no ip ospf passive` line on r3 eth2 (FRR stores it). Harmless, but
it is a cosmetic difference from the original config.

## 3. Frontend (`frontend/src`)

* **3D scene (`App.jsx`)**: device chassis with 8 ports (LEDs blink faster while the agent works on that router);
  router symbol or globe; "Healthy / Scanning... / Problem detected / Unreachable" badge per router;
  labelled zones (own AS vs external ASes); `OSPF` / `eBGP` link labels with real subnets; red dashed link with no
  moving dots when a link is down; legend panel. Halo, projector cone and scan ring were removed as noise.
* **Themes**: `themes.css` (CSS tokens) + `theme.js` (3D palettes). All colours in `index.css` / `chat.css` were converted
  to tokens. The 3D scene gets its palette through a context re-provided inside the `<Canvas>`. Light theme disables bloom
  and stars. `?theme=light|amber|aurora` in the URL also selects a theme.
* **Lab control panel (`ControlPanel.jsx`, `controls.css`)**: Monitor (live health, router status, event timeline),
  Break (inject/reset faults, "ask the agent"), History (audit timeline). Top-right theme switcher.
* **Proactive alert banner**: shown when the monitor reports problems; one click asks the agent to investigate.
* **Chat (`ChatUI.jsx`)**: live tool steps inside the run card; expandable "Evidence" under each answer (commands and
  outputs, verified sources); new suggested questions.
* The agent's tool calls light up the targeted router in the 3D scene.

## 4. Lab facts discovered while testing (not changed)
The shipped lab configs contain two deliberate-looking faults, so the monitor correctly reports problems from the start:
1. **r1-r2 OSPF**: r1 `eth1` is in area 0 but r2 `eth1` is in area 1 (adjacency never forms).
2. **r1-r5 eBGP**: r1 has `neighbor 10.1.15.2 remote-as 65099` but r5 runs AS 65002 (session stays Idle).

These make good diagnosis demos ("What is wrong with the network right now?"). They are the reason four older tests fail (see 6).

## 5. How to run
```bash
# backend (restart it to load the new code)
source .venv/bin/activate
uvicorn backend.server:app --host localhost --port 8000

# frontend
cd frontend && npm run dev          # http://localhost:5173
```
Environment variables: `NETOPS_MODEL`, `NETOPS_FAST_MODEL`, `NETOPS_HEALTH_INTERVAL` (seconds, default 10),
`NETOPS_ALLOWED_ORIGINS`, `VITE_WS_URL`, `VITE_API_URL` (defaults to the WS host over http).

Suggested demo: open **Lab control > Break**, inject "Cut link r2-r4", watch the banner and the red link, click
**Investigate**, read the evidence panel, then ask for a fix ("Bring the r2-r4 link back up") and walk through the
approval gates. Press **Reset injected faults** afterwards (adjacencies need about 30 s to re-form).

## 6. Testing and verification status
* New: `tests/test_qa_agent.py` (29 tests, no lab or LLM needed): link diagnosis, health analysis, what-if, citation gate,
  tool-call recovery, classification, follow-up rewrite validation, link hints, ping injection guard, "no write tool" guarantee.
* Run against the live lab and the local 7B model: question, concept, what-if, link-diagnosis, follow-up, and fault
  inject / monitor / reset flows; a WebSocket round trip showing stage, tool and evidence messages.
* Existing suite: 61 pass, 4 fail (`test_checks::ospf_full_true...`, `test_checks::bgp_established_true...`,
  `test_gates::twin_blocks_bad_reachability`, `test_gates::rollback_on_failed_verify`). **The same 4 fail on the untouched
  commit `1cbfa85`**: the first two assume a healthy r1-r2 / r1-r5 (see section 4), the others depend on the 7B planner
  and the reviewer's RAG-citation check. `tests/test_twin.py` was not run.
* Frontend: production build passes; 2D layer checked in a headless Firefox for all three themes. **The 3D scene itself
  was not visually verified** (the headless browser has no WebGL), so check the new device models, zones and link
  labels in a real browser.

## 7. Known limitations
* Answer quality depends on the local 7B model: e.g. for the r1-r5 problem it finds the right root cause (AS 65099 vs 65002)
  but may suggest fixing the wrong side. The evidence panel is there so the reader can check.
* `what_if_down` is a topology model (hop count), not a simulation of FRR.
* Health shows "down" while an OSPF adjacency is re-forming (about 30 s after a repair).
* CPU-only inference makes tool-using answers take roughly 10 to 60 s.
* The health monitor runs about 10 `docker exec` calls per poll; raise `NETOPS_HEALTH_INTERVAL` on slow machines.
* Not done from the earlier idea list: config drift detection against intended config, camera fly-in on selection,
  an evaluation table for the new agent (the existing `evals/` do not cover it yet).
