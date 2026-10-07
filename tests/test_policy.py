import sys; sys.path.insert(0, '.')
from netops.safety import policy
from netops.tools.frr import ChangePlan, RouterChange

def _plan(router, *commands):
    return ChangePlan(intent="test", rationale="test", changes=[
        RouterChange(router=router, commands=list(commands))],
        expected_outcome="test", risk="low")

def test_blocks_touching_unmanaged_router():
    p = _plan("r5", "ip ospf cost 100")
    assert not policy.check(p).allowed

def test_blocks_removing_ospf_process():
    p = _plan("r1", "no router ospf")
    assert not policy.check(p).allowed

def test_blocks_foreign_bgp_asn():
    p = _plan("r1", "router bgp 65099")
    assert not policy.check(p).allowed

def test_blocks_removing_interface_address():
    p = _plan("r1", "no ip address 10.0.12.1/30")
    assert not policy.check(p).allowed

def test_blocks_non_config_commands():
    p = _plan("r1", "write memory")
    assert not policy.check(p).allowed

def test_blocks_too_many_routers():
    p = ChangePlan(intent="t", rationale="t", expected_outcome="t", risk="low", changes=[
        RouterChange(router="r1", commands=["ip ospf cost 100"]),
        RouterChange(router="r2", commands=["ip ospf cost 100"]),
        RouterChange(router="r3", commands=["ip ospf cost 100"])])
    assert not policy.check(p).allowed

def test_allows_safe_cost_change():
    p = _plan("r1", "interface eth1", "ip ospf cost 100", "exit")
    r = policy.check(p)
    assert r.allowed and not r.violations

def test_flags_bgp_shutdown_as_high_risk_but_allows_it():
    p = _plan("r1", "neighbor 10.1.15.2 shutdown")
    r = policy.check(p)
    assert r.allowed and len(r.warnings) > 0
