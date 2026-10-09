import sys; sys.path.insert(0, '.')
from netops.tools import frr
from netops.safety import twin

def test_twin_end_to_end_safe_change():
    plan = frr.ChangePlan(
        intent="Raise OSPF cost on r1 eth1 toward r2",
        rationale="Digital twin integration test",
        changes=[frr.RouterChange(router="r1", commands=["interface eth1", "ip ospf cost 100", "exit"])],
        expected_outcome="r1 to r4 traffic prefers the r3 path",
        risk="low",
        checks=[
            frr.Check(type="ospf_full", router="r1", target="2.2.2.2"),
            frr.Check(type="route_nexthop", router="r1", target="4.4.4.4", expect="10.0.13.2"),
        ]
    )
    result = twin.twin_test(plan)
    assert result["ok"] is True, result["results"]

