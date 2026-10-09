import re
from dataclasses import dataclass

MANAGED = {"r1", "r2", "r3", "r4"}
MAX_ROUTERS_PER_CHANGE = 2

# Allowlist: a config line must match one of these to be accepted. Anything else is
# rejected, so a command nobody thought about can't slip through a denylist gap.
ALLOW = [
    r"^interface \S+$",
    r"^exit$",
    r"^exit-address-family$",
    r"^end$",
    r"^ip ospf (cost \d+|area \d+|hello-interval \d+|dead-interval \d+|priority \d+)$",
    r"^no ip ospf (cost|hello-interval|dead-interval|priority)( \d+)?$",
    r"^router ospf$",
    r"^(no )?passive-interface \S+$",
    r"^router bgp 65001$",
    r"^address-family ipv4 unicast$",
    r"^(no )?neighbor \S+ shutdown$",
    r"^neighbor \S+ (remote-as \d+|next-hop-self|update-source \S+|description .+)$",
    r"^neighbor \S+ route-map \S+ (in|out)$",
    r"^neighbor \S+ prefix-list \S+ (in|out)$",
    r"^neighbor \S+ weight \d+$",
    r"^bgp (local-preference|default local-preference) \d+$",
    r"^network \d+\.\d+\.\d+\.\d+/\d+$",
    r"^(ip prefix-list \S+ (seq \d+ )?(permit|deny) \S+( (le|ge) \d+)*)$",
    r"^route-map \S+ (permit|deny) \d+$",
    r"^set (local-preference|metric|weight|as-path prepend) .+$",
    r"^match (ip address prefix-list|ip next-hop|as-path|community) \S+$",
    r"^description .+$",
    r"^(no )?shutdown$",
]

DENY = [  # explicit reasons, reported even though the allowlist would also reject these
    (r"^no router (ospf|bgp)", "Removes a whole routing process"),
    (r"^router bgp (?!65001$)", "Touches a BGP process that is not ours"),
    (r"^no ip address", "Removes an interface address"),
    (r"^no ip ospf area", "Removes an interface from OSPF"),
    (r"^no network", "Withdraws a network statement"),
    (r"^(clear|write|copy|do|configure|reload|erase|delete)\b", "Not a config line"),
]
HIGH_RISK = [  # allowed, but flagged for extra attention
    (r"^(no )?shutdown$", "Shuts or re-enables an interface or session"),
    (r"neighbor \S+ shutdown", "Shuts a BGP session"),
    (r"route-map .* deny", "Adds a deny policy"),
    (r"remote-as", "Changes a BGP peering"),
    (r"^ip ospf area", "Moves an interface to another OSPF area"),
    (r"passive-interface", "Changes OSPF hello behaviour"),
]

@dataclass
class PolicyResult:
    allowed: bool
    violations: list[str]
    warnings: list[str]

def normalize(line: str) -> str:
    """Collapse whitespace and lowercase keywords so spacing/case tricks don't dodge the rules."""
    return re.sub(r"\s+", " ", line.strip())

def check(plan) -> PolicyResult:
    v, w = [], []
    if not plan.changes:
        v.append("Plan contains no changes")
    routers = {c.router for c in plan.changes}
    if len(routers) > MAX_ROUTERS_PER_CHANGE:
        v.append(f"Touches {len(routers)} routers; max is {MAX_ROUTERS_PER_CHANGE}")
    if plan.changes and not getattr(plan, "checks", None):
        v.append("Plan has no intent-specific checks; it must state how success is verified")
    for c in plan.changes:
        if c.router not in MANAGED:
            v.append(f"{c.router} is not managed by us")
        if not c.commands:
            v.append(f"{c.router}: empty command list")
        for raw in c.commands:
            if any(ord(ch) < 32 for ch in raw):
                v.append(f"{c.router}: control characters in command")
                continue
            line = normalize(raw)
            denied = [why for pat, why in DENY if re.search(pat, line, re.I)]
            v += [f"{c.router}: '{line}' - {why}" for why in denied]
            if not denied and not any(re.search(p, line, re.I) for p in ALLOW):
                v.append(f"{c.router}: '{line}' - not in the allowed command set")
            w += [f"{c.router}: '{line}' - {why}" for pat, why in HIGH_RISK if re.search(pat, line, re.I)]
    return PolicyResult(allowed=not v, violations=v, warnings=w)
