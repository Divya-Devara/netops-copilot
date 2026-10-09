"""Offline tests (no lab, no LLM): tool validation, executor failure handling, UI message mapping."""
import sys; sys.path.insert(0, '.')
import pytest
from unittest.mock import patch

from netops.tools import frr, checks
from netops.agents import graph as G
from backend.server import final_message, plan_routers

def test_show_rejects_newlines_and_config():
    for bad in ["show ip route\nconfigure terminal", "configure terminal", "show x; reboot", "show x | sh"]:
        with pytest.raises(frr.ToolError):
            frr.show("r1", bad)

def test_unknown_router_rejected():
    with pytest.raises(frr.ToolError):
        frr.show("r9", "show ip route")

def test_check_rejects_unknown_router():
    with pytest.raises(ValueError):
        frr.Check(type="ping", router="r9", target="1.1.1.1")

def test_ping_target_must_be_an_ip():
    c = frr.Check(type="ping", router="r1", target="-f")
    with patch.object(frr, "_exec") as ex:
        assert checks.run_check(c) is False
        ex.assert_not_called()

def test_check_error_counts_as_failure():
    c = frr.Check(type="ospf_full", router="r1", target="2.2.2.2")
    with patch.object(frr, "ospf_neighbors", side_effect=frr.ToolError("boom")):
        assert checks.run_check(c) is False

def test_normalize_config_ignores_comments_and_blanks():
    assert frr.normalize_config("a\n!\n\n b \n") == ["a", " b"]

def _state(cmds_by_router):
    plan = frr.ChangePlan(intent="t", rationale="t", expected_outcome="t", risk="low",
                          checks=[frr.Check(type="ospf_full", router="r1", target="2.2.2.2")],
                          changes=[frr.RouterChange(router=r, commands=c) for r, c in cmds_by_router.items()])
    return {"intent": "t", "plan": plan}

CFG = {"configurable": {"thread_id": "test"}}

def test_executor_rolls_back_everything_when_second_router_fails():
    s = _state({"r1": ["ip ospf cost 5"], "r2": ["ip ospf cost 5"]})
    def fake_apply(change, prefix=frr.PREFIX):
        if change.router == "r2":
            raise frr.ToolError("% Unknown command")
    with patch.object(frr, "snapshot", side_effect=lambda r, **k: f"snap-{r}"), \
         patch.object(frr, "apply", side_effect=fake_apply), \
         patch.object(G, "log_audit"):
        out = G.apply(s, CFG)
    assert out["apply_error"] and set(out["snaps"]) == {"r1", "r2"}  # both snapshotted -> both can be rolled back

def test_executor_refuses_plan_that_fails_policy():
    s = _state({"r5": ["ip ospf cost 5"]})
    with patch.object(frr, "apply") as ap, patch.object(G, "log_audit"):
        out = G.apply(s, CFG)
    ap.assert_not_called()
    assert out["apply_error"] and out["snaps"] == {}

def test_rollback_reports_when_config_does_not_match():
    s = {"intent": "t", "plan": _state({"r1": ["x"]})["plan"], "snaps": {"r1": "snap"}}
    with patch.object(frr, "rollback"), patch.object(frr, "config_matches_snapshot", return_value=False), \
         patch.object(G, "log_audit"):
        out = G.rollback(s, CFG)
    assert out["rollback_ok"] is False and out["outcome"] == "rolled_back"

def test_empty_plan_routes_to_no_change_without_twin():
    s = _state({})
    assert G.route_plan(s) == "no_change"

def test_invalid_plan_retries_then_blocks():
    assert G.route_plan({"plan": None, "attempts": 1}) == "plan"
    assert G.route_plan({"plan": None, "attempts": 2}) == "blocked_by_plan"

def test_final_message_covers_every_outcome():
    assert final_message({"outcome": "blocked", "blocked_reason": "Blocked by policy: x"})["outcome"] == "blocked"
    assert final_message({"outcome": "rejected"})["outcome"] == "rejected"
    assert final_message({"outcome": "applied"})["outcome"] == "applied"
    assert final_message({"outcome": "rolled_back", "rollback_ok": True})["outcome"] == "rolled_back"
    assert final_message({"outcome": "rolled_back", "rollback_ok": False})["outcome"] == "error"
    assert final_message({"outcome": "answer", "answer": "hi"})["text"] == "hi"

def test_plan_routers_dedupes():
    p = _state({"r1": ["a"], "r2": ["b"]})["plan"]
    assert plan_routers(p) == ["r1", "r2"]
