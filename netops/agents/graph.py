import json, time, uuid
from typing import TypedDict, Literal
from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt
from langgraph.checkpoint.memory import MemorySaver
from langchain_ollama import ChatOllama
from pydantic import BaseModel

from netops.tools import frr, checks
from netops.tools.frr import ChangePlan
from netops.safety import policy
from netops.agents.prompts import TOPOLOGY, PLANNER_PROMPT
from netops.agents.reviewer import run_reviewer

llm = ChatOllama(model="qwen2.5:7b", temperature=0)

CLASSIFY_PROMPT = """Classify the user's message as exactly one of: "question" or "change".

"question" = the user wants information, an explanation, or a diagnosis. No network device should be modified.
"change" = the user wants some configuration modified, even if phrased indirectly.

Message: {intent}
"""

def log_audit(entry: dict) -> None:
    entry["ts"] = time.time()
    with open("audit.jsonl", "a") as f:
        f.write(json.dumps(entry, default=str) + "\n")

class Kind(BaseModel):
    kind: Literal["question", "change"]

class State(TypedDict, total=False):
    intent: str
    kind: str
    net: dict
    plan: ChangePlan
    review_result: dict
    diffs: dict
    policy_result: dict
    twin_result: dict
    approved: bool
    snaps: dict
    ok: bool
    verify_results: dict
    answer: str
    blocked_reason: str
    attempts: int
    feedback: str

def classify(s):
    k = llm.with_structured_output(Kind).invoke(CLASSIFY_PROMPT.format(intent=s["intent"]))
    return {"kind": k.kind}

def inspect(s):
    return {"net": frr.summarize(frr.network_snapshot())}

def answer(s):
    msg = f"Topology:\n{TOPOLOGY}\nState:\n{json.dumps(s['net'])}\nQuestion: {s['intent']}"
    result = llm.invoke(msg).content
    log_audit({"type": "answer", "intent": s["intent"], "answer": result})
    return {"answer": result}

def plan(s):
    attempts = s.get("attempts", 0) + 1
    prompt = PLANNER_PROMPT.format(topology=TOPOLOGY, state=json.dumps(s["net"]), intent=s["intent"])
    
    if s.get("feedback"):
        prompt += f"\n\nYour previous plan was rejected. Feedback:\n{s['feedback']}\n\nPlease fix the plan and try again."
        
    p = llm.with_structured_output(ChangePlan).invoke(prompt)
    return {"plan": p, "attempts": attempts, "feedback": ""}

def review_plan(s):
    result = run_reviewer(s["intent"], s["plan"].model_dump(), s["net"])
    log_audit({"type": "review", "intent": s["intent"], "approve": result["approve"], "concerns": result["concerns"]})
    
    feedback = ""
    if not result["approve"]:
        feedback = "Reviewer rejected the plan with these concerns: " + "; ".join(result["concerns"])
        
    return {"review_result": result, "feedback": feedback}

def dry_run(s):
    return {"diffs": {c.router: frr.dry_run(c) for c in s["plan"].changes}}

def policy_check(s):
    result = policy.check(s["plan"])
    log_audit({"type": "policy_check", "intent": s["intent"], "allowed": result.allowed})
    feedback = ""
    if not result.allowed:
        feedback = "Policy violations: " + "; ".join(result.violations)
    return {"policy_result": {"allowed": result.allowed, "violations": result.violations, "warnings": result.warnings}, "feedback": feedback}

def twin_test_node(s):
    from netops.safety import twin
    result = twin.twin_test(s["plan"])
    log_audit({"type": "twin_test", "intent": s["intent"], "result": result})
    feedback = ""
    if not result["ok"]:
        failed = [k for k, v in result["results"].items() if not v]
        feedback = "Twin test failed post-checks: " + ", ".join(failed)
    return {"twin_result": result, "feedback": feedback}

def approval(s):
    decision = interrupt({
        "plan": s["plan"].model_dump(),
        "diffs": s["diffs"],
        "review": s["review_result"],
        "policy": s["policy_result"],
        "twin": s["twin_result"],
    })
    approved = decision == "approve"
    log_audit({"type": "approval", "intent": s["intent"], "decision": decision})
    return {"approved": approved}

def apply(s):
    snaps = {}
    for c in s["plan"].changes:
        snaps[c.router] = frr.snapshot(c.router)
        frr.apply(c)
    return {"snaps": snaps}

def verify(s):
    time.sleep(15)
    result = checks.run_all(s["plan"].checks)
    log_audit({"type": "verify", "intent": s["intent"], "result": result})
    return {"ok": result["ok"], "verify_results": result["results"]}

def rollback(s):
    for router, path in s["snaps"].items():
        frr.rollback(router, path)
    log_audit({"type": "rollback", "intent": s["intent"], "routers": list(s["snaps"].keys())})
    return {}

def blocked_by_review(s):
    return {"blocked_reason": "Blocked by Reviewer: " + "; ".join(s["review_result"]["concerns"])}

def blocked_by_policy(s):
    return {"blocked_reason": "Blocked by policy: " + "; ".join(s["policy_result"]["violations"])}

def blocked_by_twin(s):
    failed = [k for k, v in s["twin_result"]["results"].items() if not v]
    return {"blocked_reason": "Twin test failed checks: " + ", ".join(failed)}

g = StateGraph(State)
for name, fn in [
    ("classify", classify), ("inspect", inspect), ("answer", answer),
    ("plan", plan), ("review_plan", review_plan), ("dry_run", dry_run), ("policy_check", policy_check),
    ("twin_test_node", twin_test_node), ("approval", approval),
    ("apply", apply), ("verify", verify), ("rollback", rollback),
    ("blocked_by_review", blocked_by_review), ("blocked_by_policy", blocked_by_policy), ("blocked_by_twin", blocked_by_twin),
]:
    g.add_node(name, fn)

g.add_edge(START, "classify")
g.add_edge("classify", "inspect")
g.add_conditional_edges("inspect", lambda s: "answer" if s["kind"] == "question" else "plan")
g.add_edge("answer", END)

g.add_edge("plan", "review_plan")
def route_review(s):
    if s["review_result"]["approve"]:
        return "dry_run"
    if s["attempts"] < 2:
        return "plan"
    return "blocked_by_review"
g.add_conditional_edges("review_plan", route_review)
g.add_edge("blocked_by_review", END)

g.add_edge("dry_run", "policy_check")
def route_policy(s):
    if s["policy_result"]["allowed"]:
        return "twin_test_node"
    if s["attempts"] < 2:
        return "plan"
    return "blocked_by_policy"
g.add_conditional_edges("policy_check", route_policy)
g.add_edge("blocked_by_policy", END)

def route_twin(s):
    if s["twin_result"]["ok"]:
        return "approval"
    if s["attempts"] < 2:
        return "plan"
    return "blocked_by_twin"
g.add_conditional_edges("twin_test_node", route_twin)
g.add_edge("blocked_by_twin", END)

g.add_conditional_edges("approval", lambda s: "apply" if s["approved"] else END)
g.add_edge("apply", "verify")
g.add_conditional_edges("verify", lambda s: END if s["ok"] else "rollback")
g.add_edge("rollback", END)

graph = g.compile(checkpointer=MemorySaver())
