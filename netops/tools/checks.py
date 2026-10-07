from netops.tools import frr

INVARIANTS = [  # must hold after every change, regardless of intent
    frr.Check(type="ping", router="r5", target="6.6.6.6"),
    frr.Check(type="ping", router="r1", target="4.4.4.4"),
    frr.Check(type="ping", router="r2", target="3.3.3.3"),
]

def run_check(c: frr.Check, prefix: str = frr.PREFIX) -> bool:
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
    results = {f"{c.type}:{c.router}:{c.target}": run_check(c, prefix)
               for c in [*plan_checks, *INVARIANTS]}
    return {"ok": all(results.values()), "results": results}
