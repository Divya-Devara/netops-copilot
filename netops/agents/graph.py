import json, time
from typing import TypedDict, Literal
from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt
from langgraph.checkpoint.memory import MemorySaver
from langchain_ollama import ChatOllama
from pydantic import BaseModel

from netops.tools import frr
from netops.tools.frr import ChangePlan
from netops.agents.prompts import TOPOLOGY, PLANNER_PROMPT

llm = ChatOllama(model="qwen2.5:7b", temperature=0)

class Kind(BaseModel):
    kind: Literal["question", "change"]

class State(TypedDict, total=False):
    intent: str
    kind: str
    net: dict
    plan: ChangePlan
    diffs: dict
    approved: bool
    snaps: dict
    ok: bool
    answer: str
CLASSIFY_PROMPT = """Classify the user's message as exactly one of: "question" or "change".

"question" = the user wants information, an explanation, or a diagnosis. No network device should be modified.
Examples: "Is r3 adjacent?", "Why can't r5 reach r6?", "What's the OSPF cost on r1?"

"change" = the user wants some configuration modified, even if phrased indirectly or as a goal rather than a literal command.
Examples: "Make traffic prefer path X", "Shut down the session to Y", "Increase the cost on this link", "Prefer route through r3".

If the user describes a desired *outcome* or *behavior change* in the network (routing preference, session state, any config value), classify as "change" even if no explicit command syntax is given.

Message: {intent}
"""

def classify(s):
    k = llm.with_structured_output(Kind).invoke(CLASSIFY_PROMPT.format(intent=s["intent"]))
    return {"kind": k.kind}

def inspect(s):
    return {"net": frr.summarize(frr.network_snapshot())}

def answer(s):
    msg = f"Topology:\n{TOPOLOGY}\nState:\n{json.dumps(s['net'])}\nQuestion: {s['intent']}"
    return {"answer": llm.invoke(msg).content}

def plan(s):
    prompt = PLANNER_PROMPT.format(topology=TOPOLOGY, state=json.dumps(s["net"]), intent=s["intent"])
    return {"plan": llm.with_structured_output(ChangePlan).invoke(prompt)}

def dry_run(s):
    return {"diffs": {c.router: frr.dry_run(c) for c in s["plan"].changes}}

def approval(s):
    decision = interrupt({"plan": s["plan"].model_dump(), "diffs": s["diffs"]})
    return {"approved": decision == "approve"}

def apply(s):
    snaps = {}
    for c in s["plan"].changes:
        snaps[c.router] = frr.snapshot(c.router)
        frr.apply(c)
    return {"snaps": snaps}

def verify(s):
    time.sleep(15)  # let OSPF and BGP converge
    net = frr.summarize(frr.network_snapshot())
    ospf_ok = all(n["state"].startswith("Full") for r in net.values() for n in r.get("ospf", []))
    bgp_ok = all(p["state"] == "Established" for r in net.values() for p in r["bgp"])
    return {"ok": ospf_ok and bgp_ok, "net": net}

def rollback(s):
    for router, path in s["snaps"].items():
        frr.rollback(router, path)
    return {}

g = StateGraph(State)
for name, fn in [("classify", classify), ("inspect", inspect), ("answer", answer),
                 ("plan", plan), ("dry_run", dry_run), ("approval", approval),
                 ("apply", apply), ("verify", verify), ("rollback", rollback)]:
    g.add_node(name, fn)

g.add_edge(START, "classify")
g.add_edge("classify", "inspect")
g.add_conditional_edges("inspect", lambda s: "answer" if s["kind"] == "question" else "plan")
g.add_edge("answer", END)
g.add_edge("plan", "dry_run")
g.add_edge("dry_run", "approval")
g.add_conditional_edges("approval", lambda s: "apply" if s["approved"] else END)
g.add_edge("apply", "verify")
g.add_conditional_edges("verify", lambda s: END if s["ok"] else "rollback")
g.add_edge("rollback", END)

graph = g.compile(checkpointer=MemorySaver())
