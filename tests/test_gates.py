import uuid
import pytest
from unittest.mock import patch
from netops.agents.graph import graph
from langgraph.types import Command

def test_policy_blocks_unsafe_plan():
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    out = graph.invoke({"intent": "Remove OSPF from r2"}, config)
    assert "blocked_reason" in out
    assert "Blocked by policy" in out["blocked_reason"]

def test_twin_blocks_bad_reachability():
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    # Changes the BGP AS, passing policy but breaking the network
    out = graph.invoke({"intent": "Set remote-as for neighbor 10.1.15.2 to 65099 on r1"}, config)
    assert "blocked_reason" in out
    assert "Twin test failed" in out["blocked_reason"]

def test_rollback_on_failed_verify():
    with patch("netops.safety.twin.twin_test") as mock_twin, \
         patch("netops.tools.checks.wait_until_ok") as mock_checks:
        
        mock_twin.return_value = {"ok": True, "results": {}}
        mock_checks.return_value = {"ok": False, "results": {"ping:r5:6.6.6.6": False}}
        
        config = {"configurable": {"thread_id": str(uuid.uuid4())}}
        out = graph.invoke({"intent": "Set ospf cost on r1 eth2 to 75"}, config)
        
        # Graph pauses at approval
        assert "__interrupt__" in out
        
        # Resume graph with approval
        out = graph.invoke(Command(resume="approve"), config)
        
        # Verify failed, so graph should route to rollback and END
        assert out["ok"] is False
        assert out.get("verify_results", {}).get("ping:r5:6.6.6.6") is False
