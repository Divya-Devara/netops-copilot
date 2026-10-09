import functools, json, os, re, sys, time
from functools import lru_cache
from typing import TypedDict, Literal

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt
from pydantic import BaseModel

from netops.agents.llm import make_llm
from netops.agents.prompts import TOPOLOGY, PLANNER_PROMPT
from netops.agents.reviewer import run_reviewer
from netops.agents.qa_agent import run_qa, HISTORY_TURNS
from netops.rag.retrieve import search_docs
from netops.safety import policy
from netops.tools import frr, checks
from netops.tools.frr import ChangePlan

MAX_ATTEMPTS = 2
AUDIT_FILE = "audit.jsonl"

CLASSIFY_PROMPT = """Classify the user's message as exactly one of: "question" or "change".

"question" = the user wants information, a tutorial, an explanation, or a diagnosis (e.g., "How do I...", "Why is..."). No network device should be modified.
"change" = the user explicitly wants you to apply a configuration modification to the lab devices.

Message: {intent}
"""

@lru_cache(maxsize=1)
def llm():
    return make_llm()

@lru_cache(maxsize=1)
def fast_llm():
    """Small model that fits fully on the GPU: used only for read-only work (classify, answer).
    Planning and review stay on the bigger model. Opt-in: set NETOPS_FAST_MODEL=qwen2.5:3b
    (about 2x faster, but it cites sources correctly less often; see the eval notes)."""
    model = os.environ.get("NETOPS_FAST_MODEL") or os.environ.get("NETOPS_MODEL", "qwen2.5:7b")
    return make_llm(model)

def run_id(config: RunnableConfig) -> str:
    return config.get("configurable", {}).get("thread_id", "unknown")

def log_audit(config: RunnableConfig, entry: dict) -> None:
    """One JSON line per event, all tied together by run_id. 'run_end' lines summarize a run."""
    entry = {"run_id": run_id(config), "ts": time.time(), **entry}
    with open(AUDIT_FILE, "a") as f:
        f.write(json.dumps(entry, default=str) + "\n")

def timed(name, fn):
    """Wrap a node to log how long it took (stderr + audit 'timing' line)."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        t0 = time.perf_counter()
        try:
            return fn(*args, **kwargs)
        finally:
            dt = time.perf_counter() - t0
            print(f"[timing] {name}: {dt:.2f}s", file=sys.stderr, flush=True)
            config = kwargs.get("config") or next((a for a in args[1:] if isinstance(a, dict)), None)
            if config is not None:
                log_audit(config, {"type": "timing", "node": name, "seconds": round(dt, 3)})
    return wrapper

def end_run(config, s, outcome: str, **extra) -> dict:
    """Record the final outcome of a run and return it as state."""
    plan = s.get("plan")
    log_audit(config, {
        "type": "run_end", "outcome": outcome, "intent": s.get("intent"),
        "plan": plan.model_dump() if plan else None,
        "policy": s.get("policy_result"), "twin": s.get("twin_result"),
        "review": s.get("review_result"), "approved": s.get("approved"),
        "verify": s.get("verify_results"), **extra,
    })
    return {"outcome": outcome}

class Kind(BaseModel):
    kind: Literal["question", "change"]

class State(TypedDict, total=False):
    intent: str
    kind: str
    net: dict
    docs: str
    doc_ids: list[str]
    plan: ChangePlan | None
    review_result: dict
    diffs: dict
    policy_result: dict
    twin_result: dict
    approved: bool
    snaps: dict
    apply_error: str
    ok: bool
    verify_results: dict
    rollback_ok: bool
    answer: str
    blocked_reason: str
    outcome: str
    attempts: int
    feedback: str
    history: list[dict]
    evidence: list[dict]
    citations: list[str]

# ───────────────────────── read-only path ─────────────────────────

QUESTION_WORDS = ("how", "what", "why", "where", "which", "who", "when", "is ", "are ", "does ", "do ", "can ",
                  "explain", "show", "list", "check", "tell", "describe", "compare", "ping", "trace", "diagnose")
# A message that starts like a question but asks for a modification must go to the LLM classifier, never the fast path
CHANGE_VERBS = re.compile(r"\b(change|set|add|remove|delete|enable|disable|configure|apply|shut\w*|raise|lower|increase|decrease|"
                          r"make|update|modify|fix|replace|create|clear|reset|reload|restart|advertise|redistribute)\b", re.I)

def classify(s):
    intent_lower = s["intent"].lower().strip()
    # Fast path: bypass the LLM for obvious question formats (also the safe, read-only direction)
    if intent_lower.startswith(QUESTION_WORDS) and not CHANGE_VERBS.search(intent_lower):
        return {"kind": "question"}
    try:
        k = fast_llm().with_structured_output(Kind).invoke(CLASSIFY_PROMPT.format(intent=s["intent"]))
        return {"kind": k.kind}
    except Exception:
        return {"kind": "question"}  # if classification fails, stay read-only

def diagnose(s):
    """Read network state and retrieve docs concurrently (the intent itself is the search query)."""
    def safe_docs():
        try:
            return search_docs(s["intent"], k=3)
        except Exception:
            return "No documentation retrieved."

    net_state, docs_text = frr.pmap(lambda f: f(), [
        lambda: frr.summarize(frr.network_snapshot()), safe_docs])
    doc_ids = re.findall(r"--- SOURCE ID: (.*?) ---", docs_text)
    return {"net": net_state, "docs": docs_text, "doc_ids": doc_ids}

# Live progress events (which tool is running) go to a per-session sink registered by the server.
# LangGraph's own stream writer cannot be used here: on Python 3.10 it fails inside async runs.
EVENT_SINKS: dict = {}

def answer(s, config: RunnableConfig):
    """Read-only path: a tool-using agent investigates the live network and answers any question."""
    emit = EVENT_SINKS.get(run_id(config), lambda ev: None)
    res = run_qa(s["intent"], s.get("history", []), llm(), emit=emit)
    log_audit(config, {"type": "answer", "intent": s["intent"], "resolved_question": res["question"], "answer": res["answer"],
                       "tools": [{"tool": e["tool"], "args": e["args"]} for e in res["evidence"]],
                       "citations": res["citations"], "hallucinated": res["bad_citations"]})
    history = (s.get("history", []) + [{"q": s["intent"], "a": res["answer"]}])[-HISTORY_TURNS:]
    return {"answer": res["answer"], "evidence": res["evidence"], "citations": res["citations"],
            "history": history, **end_run(config, s, "answer")}

# ───────────────────────── change path ─────────────────────────

def plan(s):
    attempts = s.get("attempts", 0) + 1
    prompt = PLANNER_PROMPT.format(topology=TOPOLOGY, state=json.dumps(s["net"]),
                                   docs=s.get("docs", ""), intent=s["intent"])
    if s.get("feedback"):
        prompt += f"\n\nYour previous plan was rejected. Feedback:\n{s['feedback']}\n\nPlease fix the plan and try again."
    try:
        p = llm().with_structured_output(ChangePlan).invoke(prompt)
    except Exception as e:  # malformed structured output, unknown router in a check, LLM down...
        return {"plan": None, "attempts": attempts,
                "feedback": f"Your last answer was not a valid ChangePlan ({type(e).__name__}: {str(e)[:300]})"}
    return {"plan": p, "attempts": attempts, "feedback": ""}

def policy_check(s, config: RunnableConfig):
    result = policy.check(s["plan"])
    log_audit(config, {"type": "policy_check", "intent": s["intent"], "allowed": result.allowed,
                       "violations": result.violations, "warnings": result.warnings})
    feedback = "" if result.allowed else "Policy violations: " + "; ".join(result.violations)
    return {"policy_result": {"allowed": result.allowed, "violations": result.violations,
                              "warnings": result.warnings}, "feedback": feedback}

def review(s, config: RunnableConfig):
    # RAG anti-hallucination gate for execution: sources must come from this run's retrieval
    bad_cites = [c for c in s["plan"].sources if c not in s.get("doc_ids", [])]
    if bad_cites:
        feedback = f"RAG Safety Check Failed: Hallucinated SOURCE IDs {', '.join(bad_cites)}. You MUST only use the exact IDs provided."
        log_audit(config, {"type": "review", "intent": s["intent"], "approve": False, "concerns": [feedback]})
        return {"review_result": {"approve": False, "concerns": [feedback]}, "feedback": feedback}

    try:
        result = run_reviewer(s["intent"], s["plan"].model_dump(), s["net"])
    except Exception as e:  # fail closed: no review means no approval
        result = {"approve": False, "concerns": [f"Reviewer failed: {type(e).__name__}"]}
    log_audit(config, {"type": "review", "intent": s["intent"], "approve": result["approve"],
                       "concerns": result["concerns"]})
    feedback = "" if result["approve"] else "Reviewer rejected the plan with these concerns: " + "; ".join(result["concerns"])
    return {"review_result": result, "feedback": feedback}

def dry_run(s):
    diffs = frr.pmap(lambda c: (c.router, frr.dry_run(c)), s["plan"].changes)
    return {"diffs": dict(diffs)}

def twin(s, config: RunnableConfig):
    from netops.safety import twin as dtwin
    result = dtwin.twin_test(s["plan"])
    log_audit(config, {"type": "twin", "intent": s["intent"], "result": result})
    feedback = ""
    if not result["ok"]:
        failed = [k for k, v in result["results"].items() if not v]
        feedback = "Twin test failed post-checks: " + ", ".join(failed)
        if result.get("error"):
            feedback += f" ({result['error']})"
    return {"twin_result": result, "feedback": feedback}

def approval(s, config: RunnableConfig):
    decision = interrupt({
        "plan": s["plan"].model_dump(),
        "diffs": s["diffs"],
        "review": s["review_result"],
        "policy": s["policy_result"],
        "twin": s["twin_result"],
    })
    approved = decision == "approve"
    log_audit(config, {"type": "approval", "intent": s["intent"], "decision": decision})
    return {"approved": approved}

# ───────────── executor: the only nodes that can change the network ─────────────

def apply(s, config: RunnableConfig):
    # Defence in depth: re-validate the exact plan that was approved, right before touching routers
    recheck = policy.check(s["plan"])
    if not recheck.allowed:
        err = "Executor refused plan: " + "; ".join(recheck.violations)
        log_audit(config, {"type": "apply", "intent": s["intent"], "error": err})
        return {"snaps": {}, "apply_error": err, "ok": False}

    changes = s["plan"].changes
    # Snapshot every router first, so a failure part-way through can still be fully rolled back
    snaps = {c.router: p for c, p in zip(changes, frr.pmap(lambda c: frr.snapshot(c.router), changes))}
    try:
        for c in changes:
            frr.apply(c)
    except Exception as e:
        err = f"Apply failed on {c.router}: {e}"
        log_audit(config, {"type": "apply", "intent": s["intent"], "error": err})
        return {"snaps": snaps, "apply_error": err, "ok": False}
    log_audit(config, {"type": "apply", "intent": s["intent"], "routers": list(snaps)})
    return {"snaps": snaps, "apply_error": ""}

def verify(s, config: RunnableConfig):
    result = checks.wait_until_ok(s["plan"].checks, timeout=30)  # polls instead of a fixed sleep
    log_audit(config, {"type": "verify", "intent": s["intent"], "result": result})
    return {"ok": result["ok"], "verify_results": result["results"]}

def rollback(s, config: RunnableConfig):
    def undo(item):
        router, path = item
        try:
            frr.rollback(router, path)
            return router, frr.config_matches_snapshot(router, path), ""
        except Exception as e:
            return router, False, str(e)

    outcomes = frr.pmap(undo, list(s["snaps"].items()))
    ok = all(matched for _, matched, _ in outcomes)
    detail = {r: ("restored" if m else (err or "config differs from snapshot")) for r, m, err in outcomes}
    log_audit(config, {"type": "rollback", "intent": s["intent"], "routers": detail, "restored": ok})
    return {"ok": False, "rollback_ok": ok,
            **end_run(config, s, "rolled_back", rollback_restored=ok, apply_error=s.get("apply_error"))}

# ───────────────────────── terminal nodes ─────────────────────────

def done(s, config: RunnableConfig):
    return end_run(config, s, "applied")

def rejected(s, config: RunnableConfig):
    return end_run(config, s, "rejected")

def no_change(s, config: RunnableConfig):
    why = s["plan"].rationale if s.get("plan") else "no plan"
    return {"blocked_reason": f"No change proposed: {why}", **end_run(config, s, "no_change")}

def blocked(reason):
    def node(s, config: RunnableConfig):
        return {"blocked_reason": reason(s), **end_run(config, s, "blocked", reason=reason(s))}
    return node

def failed_checks(r):
    return [k for k, v in r["results"].items() if not v]

# ───────────────────────── graph wiring ─────────────────────────
# question: classify -> answer (tool-using agent)
# change:   classify -> diagnose -> plan -> policy -> review -> dry_run -> twin -> approval -> apply -> verify
# Cheap deterministic gates run before LLM review and the (slow) twin.

g = StateGraph(State)
for name, fn in [
    ("classify", classify), ("diagnose", diagnose), ("answer", answer),
    ("plan", plan), ("policy", policy_check), ("review", review), ("dry_run", dry_run),
    ("twin", twin), ("approval", approval),
    ("apply", apply), ("verify", verify), ("rollback", rollback),
    ("done", done), ("rejected", rejected), ("no_change", no_change),
    ("blocked_by_plan", blocked(lambda s: "Planner could not produce a valid plan: " + s.get("feedback", ""))),
    ("blocked_by_policy", blocked(lambda s: "Blocked by policy: " + "; ".join(s["policy_result"]["violations"]))),
    ("blocked_by_executor", blocked(lambda s: s["apply_error"])),
    ("blocked_by_review", blocked(lambda s: "Blocked by Reviewer: " + "; ".join(s["review_result"]["concerns"]))),
    ("blocked_by_twin", blocked(lambda s: "Twin test failed checks: " + ", ".join(failed_checks(s["twin_result"]))
                                          + (f" ({s['twin_result']['error']})" if s["twin_result"].get("error") else ""))),
]:
    g.add_node(name, timed(name, fn))

def retry_or(blocked_node, proceed):
    """Build a router: proceed on success, else re-plan (bounded by MAX_ATTEMPTS), else stop."""
    def route(s):
        if proceed(s):
            return "ok"
        return "plan" if s.get("attempts", 0) < MAX_ATTEMPTS else blocked_node
    return route

g.add_edge(START, "classify")
g.add_conditional_edges("classify", lambda s: "answer" if s["kind"] == "question" else "diagnose")
g.add_edge("diagnose", "plan")
g.add_edge("answer", END)

def route_plan(s):
    if s.get("plan") is None:
        return "plan" if s.get("attempts", 0) < MAX_ATTEMPTS else "blocked_by_plan"
    return "no_change" if not s["plan"].changes else "policy"
g.add_conditional_edges("plan", route_plan)

g.add_conditional_edges("policy", retry_or("blocked_by_policy", lambda s: s["policy_result"]["allowed"]),
                        {"ok": "review", "plan": "plan", "blocked_by_policy": "blocked_by_policy"})
g.add_conditional_edges("review", retry_or("blocked_by_review", lambda s: s["review_result"]["approve"]),
                        {"ok": "dry_run", "plan": "plan", "blocked_by_review": "blocked_by_review"})
g.add_edge("dry_run", "twin")
g.add_conditional_edges("twin", retry_or("blocked_by_twin", lambda s: s["twin_result"]["ok"]),
                        {"ok": "approval", "plan": "plan", "blocked_by_twin": "blocked_by_twin"})
g.add_conditional_edges("approval", lambda s: "apply" if s["approved"] else "rejected")
g.add_conditional_edges("apply", lambda s: ("rollback" if s["snaps"] else "blocked_by_executor") if s.get("apply_error") else "verify",
                        {"rollback": "rollback", "blocked_by_executor": "blocked_by_executor", "verify": "verify"})
g.add_conditional_edges("verify", lambda s: "done" if s["ok"] else "rollback")

for terminal in ("no_change", "blocked_by_plan", "blocked_by_policy", "blocked_by_review",
                 "blocked_by_twin", "blocked_by_executor", "rejected", "done", "rollback"):
    g.add_edge(terminal, END)

graph = g.compile(checkpointer=MemorySaver())
