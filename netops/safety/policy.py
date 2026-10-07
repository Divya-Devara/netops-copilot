import re
from dataclasses import dataclass

MANAGED = {"r1", "r2", "r3", "r4"}
MAX_ROUTERS_PER_CHANGE = 2

DENY = [  # never allowed
    (r"^no router (ospf|bgp)", "Removes a whole routing process"),
    (r"^router bgp (?!65001\b)", "Touches a BGP process that is not ours"),
    (r"^no ip address", "Removes an interface address"),
    (r"^(clear|write|copy|do )", "Not a config line"),
]
HIGH_RISK = [  # allowed, but flagged for extra attention
    (r"^shutdown$", "Shuts an interface or session"),
    (r"neighbor \S+ shutdown", "Shuts a BGP session"),
    (r"route-map .* deny", "Adds a deny policy"),
    (r"remote-as", "Changes a BGP peering"),
]

@dataclass
class PolicyResult:
    allowed: bool
    violations: list[str]
    warnings: list[str]

def check(plan) -> PolicyResult:
    v, w = [], []
    if len(plan.changes) > MAX_ROUTERS_PER_CHANGE:
        v.append(f"Touches {len(plan.changes)} routers; max is {MAX_ROUTERS_PER_CHANGE}")
    for c in plan.changes:
        if c.router not in MANAGED:
            v.append(f"{c.router} is not managed by us")
        for line in c.commands:
            line = line.strip()
            v += [f"{c.router}: '{line}' - {why}" for pat, why in DENY if re.search(pat, line)]
            w += [f"{c.router}: '{line}' - {why}" for pat, why in HIGH_RISK if re.search(pat, line)]
    return PolicyResult(allowed=not v, violations=v, warnings=w)
