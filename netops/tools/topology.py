"""Static model of the lab (mirrors lab/topology.clab.yml and lab/configs). Used for what-if analysis
and for mapping live router state onto links. Keep in sync with the frontend's ROUTERS/LINKS."""
from collections import deque

ROUTER_IDS = {"r1": "1.1.1.1", "r2": "2.2.2.2", "r3": "3.3.3.3", "r4": "4.4.4.4", "r5": "5.5.5.5", "r6": "6.6.6.6"}

# (a, b, protocol, subnet, a_iface, b_iface, ebgp peer ip seen from `a` (None for OSPF links))
LINKS = [
    ("r1", "r2", "ospf", "10.0.12.0/30", "eth1", "eth1", None),
    ("r1", "r3", "ospf", "10.0.13.0/30", "eth2", "eth1", None),
    ("r2", "r4", "ospf", "10.0.24.0/30", "eth2", "eth1", None),
    ("r3", "r4", "ospf", "10.0.34.0/30", "eth2", "eth2", None),
    ("r1", "r5", "bgp",  "10.1.15.0/30", "eth3", "eth1", "10.1.15.2"),
    ("r4", "r6", "bgp",  "10.1.46.0/30", "eth3", "eth1", "10.1.46.2"),
]

DESCRIPTION = """r1-r4: our routers, AS 65001, OSPF area 0 core (square r1-r2-r4-r3).
Links: r1-r2 10.0.12.0/30, r1-r3 10.0.13.0/30, r2-r4 10.0.24.0/30, r3-r4 10.0.34.0/30.
r5 (AS 65002) peers with r1 over eBGP (10.1.15.0/30). r6 (AS 65003) peers with r4 over eBGP (10.1.46.0/30).
r1 and r4 run iBGP between loopbacks 1.1.1.1 and 4.4.4.4.
Loopbacks: r1 1.1.1.1, r2 2.2.2.2, r3 3.3.3.3, r4 4.4.4.4, r5 5.5.5.5, r6 6.6.6.6."""

def link_key(a: str, b: str) -> str:
    return "-".join(sorted((a, b)))

def _graph(down_routers=frozenset(), down_links=frozenset()):
    g = {r: set() for r in ROUTER_IDS}
    for a, b, *_ in LINKS:
        if a in down_routers or b in down_routers or link_key(a, b) in down_links:
            continue
        g[a].add(b); g[b].add(a)
    return g

def _shortest(g, src, dst):
    prev, q = {src: None}, deque([src])
    while q:
        n = q.popleft()
        if n == dst:
            path = []
            while n is not None:
                path.append(n); n = prev[n]
            return path[::-1]
        for m in sorted(g[n]):
            if m not in prev:
                prev[m] = n; q.append(m)
    return None

def what_if_down(element: str) -> str:
    """Predict the impact of losing one router ('r2') or one link ('r2-r4') from the static topology.
    Hop-count model: it ignores OSPF costs and BGP policy, so treat it as a first approximation."""
    el = element.strip().lower().replace(" ", "").replace("–", "-").replace("_", "-")
    if el in ROUTER_IDS:
        base, after = _graph(), _graph(down_routers={el})
        what, skip = f"router {el} failing", {el}
    else:
        parts = el.split("-")
        if len(parts) != 2 or link_key(*parts) not in {link_key(l[0], l[1]) for l in LINKS}:
            return f"Unknown element '{element}'. Use a router (r1..r6) or a link such as r2-r4."
        base, after = _graph(), _graph(down_links={link_key(*parts)})
        what, skip = f"link {link_key(*parts)} failing", set()
    lost, rerouted = [], []
    names = sorted(r for r in ROUTER_IDS if r not in skip)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            p0, p1 = _shortest(base, a, b), _shortest(after, a, b)
            if p1 is None:
                lost.append(f"{a}<->{b}")
            elif p1 != p0:
                rerouted.append(f"{a}->{b}: {'-'.join(p0)} becomes {'-'.join(p1)}")
    out = [f"What-if: {what} (hop-count model from the lab topology; ignores OSPF costs and BGP policy)."]
    out.append("Connectivity LOST for: " + (", ".join(lost) if lost else "none (the network stays fully connected)"))
    out.append("Paths that would change:" + ("\n  " + "\n  ".join(rerouted) if rerouted else " none"))
    return "\n".join(out)
