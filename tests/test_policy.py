import sys; sys.path.insert(0, '.')
from netops.safety import policy
from netops.tools.frr import ChangePlan, RouterChange, Check

CHECK = Check(type="ospf_full", router="r1", target="2.2.2.2")

def _plan(router, *commands):
    return ChangePlan(intent="test", rationale="test", changes=[
        RouterChange(router=router, commands=list(commands))],
        expected_outcome="test", risk="low", checks=[CHECK])

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
    p = ChangePlan(intent="t", rationale="t", expected_outcome="t", risk="low", checks=[CHECK], changes=[
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


# ── allowlist / normalization: tricks that a plain denylist would miss ──
def test_blocks_whitespace_trick():
    assert not policy.check(_plan("r1", "no router   ospf")).allowed

def test_blocks_case_trick():
    assert not policy.check(_plan("r1", "No Router OSPF")).allowed

def test_blocks_vtysh_abbreviation():
    assert not policy.check(_plan("r1", "no rou ospf")).allowed

def test_blocks_unknown_command_not_in_allowlist():
    r = policy.check(_plan("r1", "ip route 0.0.0.0/0 Null0"))
    assert not r.allowed and "allowed command set" in r.violations[0]

def test_blocks_removing_interface_from_ospf():
    assert not policy.check(_plan("r1", "interface eth1", "no ip ospf area")).allowed

def test_blocks_newline_injection():
    assert not policy.check(_plan("r1", "ip ospf cost 5\nno router ospf")).allowed

def test_blocks_empty_plan():
    p = ChangePlan(intent="t", rationale="t", changes=[], expected_outcome="t", risk="low")
    assert not policy.check(p).allowed

def test_blocks_plan_without_checks():
    p = ChangePlan(intent="t", rationale="t", expected_outcome="t", risk="low",
                   changes=[RouterChange(router="r1", commands=["ip ospf cost 5"])])
    assert not policy.check(p).allowed

def test_router_limit_counts_distinct_routers():
    p = ChangePlan(intent="t", rationale="t", expected_outcome="t", risk="low", checks=[CHECK], changes=[
        RouterChange(router="r1", commands=["ip ospf cost 5"]),
        RouterChange(router="r1", commands=["ip ospf cost 6"]),
        RouterChange(router="r1", commands=["ip ospf cost 7"])])
    assert policy.check(p).allowed

def test_shutdown_is_allowed_but_warned():
    r = policy.check(_plan("r1", "router bgp 65001", "neighbor 10.1.15.2 shutdown"))
    assert r.allowed and r.warnings
