"""Live health of the lab, derived from `show` output. analyze() is pure so it can be unit tested."""
from netops.tools import frr
from netops.tools.topology import LINKS, ROUTER_IDS, link_key

def _fetch(router):
    try:
        d = {"bgp": frr.bgp_summary(router)}
        if router in frr.MANAGED:
            d["ospf"] = frr.ospf_neighbors(router)
        return router, d
    except Exception:
        return router, None          # unreachable / daemon down

def collect() -> dict:
    return dict(frr.pmap(_fetch, sorted(ROUTER_IDS)))

def _ospf_full(snap, a, b):
    nbrs = ((snap.get(a) or {}).get("ospf") or {}).get("neighbors", {})
    states = nbrs.get(ROUTER_IDS[b]) or []
    return any(str(n.get("nbrState", "")).startswith("Full") for n in states)

def _bgp_established(snap, a, peer_ip):
    peers = (((snap.get(a) or {}).get("bgp") or {}).get("ipv4Unicast") or {}).get("peers", {})
    return (peers.get(peer_ip) or {}).get("state") == "Established"

def analyze(snap: dict) -> dict:
    """snap: {router: {'ospf':..., 'bgp':...} | None}. Returns routers/links status and a list of issues."""
    links, issues = {}, []
    down = {r for r, d in snap.items() if d is None}
    for r in sorted(down):
        issues.append(f"{r} is unreachable (not answering `show` commands)")
    for a, b, proto, subnet, *_rest, peer in LINKS:
        key = link_key(a, b)
        if a in down or b in down:
            links[key] = "down"; continue
        up = _ospf_full(snap, a, b) and _ospf_full(snap, b, a) if proto == "ospf" else _bgp_established(snap, a, peer)
        links[key] = "up" if up else "down"
        if not up:
            issues.append(f"{'OSPF adjacency' if proto == 'ospf' else 'eBGP session'} {a}-{b} is down ({subnet})")
    ibgp = None
    if snap.get("r1") and snap.get("r4"):
        ibgp = _bgp_established(snap, "r1", ROUTER_IDS["r4"]) and _bgp_established(snap, "r4", ROUTER_IDS["r1"])
        if not ibgp:
            issues.append("iBGP session r1-r4 (loopback to loopback) is down")
    routers = {}
    for r in ROUTER_IDS:
        if r in down:
            routers[r] = "down"
        elif any(v == "down" and r in k.split("-") for k, v in links.items()) or (ibgp is False and r in ("r1", "r4")):
            routers[r] = "degraded"
        else:
            routers[r] = "ok"
    return {"routers": routers, "links": links, "issues": issues, "healthy": not issues}

def check_health() -> dict:
    return analyze(collect())
