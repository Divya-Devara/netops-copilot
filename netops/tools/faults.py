"""Out-of-band fault injection for demos. Each fault has an exact undo, so 'reset' is deterministic.
These bypass the agent on purpose: they simulate the world breaking, which the agent must then detect and fix."""
from netops.tools import frr

FAULTS = {
    "link_r2_r4": {"title": "Cut link r2-r4", "kind": "outage",
                   "desc": "Shuts r2 eth2: the OSPF adjacency to r4 drops and traffic must reroute via r1-r3.",
                   "router": "r2", "inject": ["interface eth2", "shutdown"], "undo": ["interface eth2", "no shutdown"]},
    "link_r1_r3": {"title": "Cut link r1-r3", "kind": "outage",
                   "desc": "Shuts r3 eth1: the OSPF adjacency r1-r3 drops.",
                   "router": "r3", "inject": ["interface eth1", "shutdown"], "undo": ["interface eth1", "no shutdown"]},
    "bgp_r1_r5": {"title": "Drop eBGP r1-r5", "kind": "outage",
                  "desc": "Administratively shuts the BGP session from r1 to r5 (10.1.15.2).",
                  "router": "r1", "inject": ["router bgp 65001", "neighbor 10.1.15.2 shutdown"],
                  "undo": ["router bgp 65001", "no neighbor 10.1.15.2 shutdown"]},
    "passive_r3": {"title": "Misconfig: passive eth2 on r3", "kind": "misconfig",
                   "desc": "Marks r3 eth2 passive in OSPF (a subtle config error): the r3-r4 adjacency silently disappears.",
                   "router": "r3", "inject": ["router ospf", "passive-interface eth2"],
                   "undo": ["router ospf", "no passive-interface eth2"]},
}

_active: set[str] = set()

def _run(router, commands):
    args = ["vtysh", "-c", "configure terminal"]
    for c in commands:
        args += ["-c", c]
    frr._exec(router, args)

def catalog() -> list[dict]:
    return [{"id": k, "title": v["title"], "desc": v["desc"], "kind": v["kind"], "active": k in _active}
            for k, v in FAULTS.items()]

def inject(fault_id: str) -> dict:
    f = FAULTS.get(fault_id)
    if not f:
        raise KeyError(fault_id)
    _run(f["router"], f["inject"])
    _active.add(fault_id)
    return {"id": fault_id, "title": f["title"]}

def reset() -> list[str]:
    """Undo every known fault (idempotent, so it is safe even after a server restart)."""
    undone = []
    for k, f in FAULTS.items():
        try:
            _run(f["router"], f["undo"]); undone.append(k)
        except frr.ToolError:
            pass
    _active.clear()
    return undone
