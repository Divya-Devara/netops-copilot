import time
from netops.tools import frr

INVARIANTS = [  # must hold after every change, regardless of intent
    frr.Check(type="ping", router="r5", target="6.6.6.6"),
    frr.Check(type="ping", router="r1", target="4.4.4.4"),
    frr.Check(type="ping", router="r2", target="3.3.3.3"),
]

def run_check(c: frr.Check, prefix: str = frr.PREFIX) -> bool:
    try:
        return _run_check(c, prefix)
    except (frr.ToolError, ValueError, KeyError, IndexError):
        return False  # a check that cannot be evaluated counts as failed

def _run_check(c: frr.Check, prefix: str) -> bool:
    if c.type in ("ping", "route_nexthop") and not frr.valid_ip(c.target):
        return False  # LLM-supplied targets must be plain IPs, never options like '-f'
    if c.type == "ping":
        n = c.router[1]  # 'r5' -> '5'
        src = f"{n}.{n}.{n}.{n}"  # r5 -> 5.5.5.5
        try:
            frr._exec(c.router, ["ping", "-c", "2", "-W", "2", "-I", src, c.target], prefix=prefix)
            return True
        except frr.ToolError:
            return False

    if c.type == "route_nexthop":
        r = frr.show_json(c.router, f"show ip route {c.target}", prefix=prefix)
        entries = next((v for k, v in r.items() if k.split("/")[0] == c.target), [])
        hops = [h.get("ip") for e in entries for h in e.get("nexthops", [])]
        return c.expect in hops

    if c.type == "ospf_full":
        n = frr.ospf_neighbors(c.router, prefix=prefix)
        nbrs = n.get("neighbors", {})
        if c.target in nbrs:
            return nbrs[c.target][0].get("nbrState", "").startswith("Full")
        for nid, entries in nbrs.items():
            if entries[0].get("ifaceName", "").split(":")[0] == c.target:
                return entries[0].get("nbrState", "").startswith("Full")
        return False

    if c.type == "bgp_established":
        b = frr.bgp_summary(c.router, prefix=prefix)
        peers = b.get("ipv4Unicast", {}).get("peers", {})
        return peers.get(c.target, {}).get("state") == "Established"

    return False

def run_all(plan_checks: list, prefix: str = frr.PREFIX) -> dict:
    all_checks = [*plan_checks, *INVARIANTS]
    outcomes = frr.pmap(lambda c: run_check(c, prefix), all_checks)
    results = {f"{c.type}:{c.router}:{c.target}": ok for c, ok in zip(all_checks, outcomes)}
    return {"ok": all(results.values()), "results": results}

def wait_until_ok(plan_checks: list, prefix: str = frr.PREFIX,
                  timeout: int = 45, interval: float = 3) -> dict:
    """Poll run_all until every check passes or the timeout expires (replaces fixed sleeps)."""
    deadline = time.time() + timeout
    while True:
        result = run_all(plan_checks, prefix)
        if result["ok"] or time.time() >= deadline:
            return result
        time.sleep(interval)
