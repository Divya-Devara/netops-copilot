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
        hops = [h.get("ip") for e in r.get(c.target, []) for h in e.get("nexthops", [])]
        return c.expect in hops

    if c.type == "ospf_full":
        n = frr.ospf_neighbors(c.router, prefix=prefix)
        states = [nbr[0].get("nbrState", "") for nbr in n.get("neighbors", {}).values()
                  if nbr[0].get("ifaceName", "").split(":")[0] == c.target
                  or c.target in n.get("neighbors", {})]
        return any(s.startswith("Full") for s in states) if states else \
               any(nbrs[0].get("nbrState", "").startswith("Full")
                   for nid, nbrs in n.get("neighbors", {}).items() if nid == c.target)

    if c.type == "bgp_established":
        b = frr.bgp_summary(c.router, prefix=prefix)
        peers = b.get("ipv4Unicast", {}).get("peers", {})
        return peers.get(c.target, {}).get("state") == "Established"

    return False

def run_all(plan_checks: list, prefix: str = frr.PREFIX) -> dict:
    results = {f"{c.type}:{c.router}:{c.target}": run_check(c, prefix)
               for c in [*plan_checks, *INVARIANTS]}
    return {"ok": all(results.values()), "results": results}
