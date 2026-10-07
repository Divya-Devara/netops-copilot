import sys; sys.path.insert(0, '.')
from netops.tools import frr, checks

def test_ospf_full_true_for_healthy_neighbor():
    c = frr.Check(type="ospf_full", router="r1", target="2.2.2.2")
    assert checks.run_check(c) is True

def test_bgp_established_true_for_healthy_peer():
    c = frr.Check(type="bgp_established", router="r1", target="10.1.15.2")
    assert checks.run_check(c) is True

def test_route_nexthop_true_for_correct_path():
    c = frr.Check(type="route_nexthop", router="r1", target="4.4.4.4", expect="10.0.13.2")
    assert checks.run_check(c) is True

def test_route_nexthop_false_for_wrong_path():
    c = frr.Check(type="route_nexthop", router="r1", target="4.4.4.4", expect="9.9.9.9")
    assert checks.run_check(c) is False

def test_bgp_established_false_for_nonexistent_peer():
    c = frr.Check(type="bgp_established", router="r1", target="192.0.2.1")
    assert checks.run_check(c) is False
