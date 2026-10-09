import difflib, ipaddress, json, os, subprocess, time
from concurrent.futures import ThreadPoolExecutor
from typing import Literal

from pydantic import BaseModel, Field, field_validator

PREFIX = "clab-netops-"
ROUTERS = {"r1", "r2", "r3", "r4", "r5", "r6"}

class ToolError(Exception):
    pass

def _exec(router: str, args: list[str], timeout: int = 20, prefix: str = PREFIX) -> str:
    if router not in ROUTERS:
        raise ToolError(f"Unknown router {router}")
    try:
        res = subprocess.run(["docker", "exec", prefix + router, *args],
                             capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise ToolError(f"Timed out after {timeout}s running {args[:3]} on {router}")
    if res.returncode != 0:
        raise ToolError(res.stderr.strip() or res.stdout.strip())
    return res.stdout

def show(router: str, command: str, prefix: str = PREFIX) -> str:
    if (not command.strip().startswith("show ")
            or any(c in command for c in ";|&`$")
            or any(ord(c) < 32 for c in command)):
        raise ToolError("Only plain single-line 'show' commands are allowed")
    return _exec(router, ["vtysh", "-c", command], prefix=prefix)

def show_json(router: str, command: str, prefix: str = PREFIX) -> dict:
    return json.loads(show(router, command + " json", prefix=prefix))

def ospf_neighbors(router: str, prefix: str = PREFIX) -> dict:
    return show_json(router, "show ip ospf neighbor", prefix=prefix)

def bgp_summary(router: str, prefix: str = PREFIX) -> dict:
    return show_json(router, "show bgp summary", prefix=prefix)

def routes(router: str, prefix: str = PREFIX) -> dict:
    return show_json(router, "show ip route", prefix=prefix)

def running_config(router: str, prefix: str = PREFIX) -> str:
    raw = show(router, "show running-config", prefix=prefix)
    lines = [line for line in raw.splitlines() if line != "Building configuration..." and line != "Current configuration:"]
    return "\n".join(lines)

MANAGED = {"r1", "r2", "r3", "r4"}

def pmap(fn, items):
    """Run fn over items in parallel threads (each call is an independent docker exec)."""
    items = list(items)
    with ThreadPoolExecutor(max_workers=max(1, len(items))) as ex:
        return list(ex.map(fn, items))

def valid_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value.split("/")[0])
        return True
    except ValueError:
        return False

def network_snapshot(prefix: str = PREFIX) -> dict:
    def one(r):
        d = {"bgp": bgp_summary(r, prefix=prefix)}
        if r in MANAGED:
            d["ospf"] = ospf_neighbors(r, prefix=prefix)
        return r, d
    return dict(pmap(one, sorted(ROUTERS)))

def summarize(snapshot: dict) -> dict:
    out = {}
    for r, data in snapshot.items():
        s = {}
        if "ospf" in data:
            s["ospf"] = [
                {"neighbor": nid, "state": n[0].get("nbrState", n[0].get("state")),
                 "iface": n[0].get("ifaceName")}
                for nid, n in data["ospf"].get("neighbors", {}).items()]
        peers = data["bgp"].get("ipv4Unicast", {}).get("peers", {})
        s["bgp"] = [{"peer": ip, "state": p.get("state"),
                     "pfxRcd": p.get("pfxRcd")} for ip, p in peers.items()]
        out[r] = s
    return out

class RouterChange(BaseModel):
    router: str
    commands: list[str] = Field(description="Config-mode lines, in order")

class Check(BaseModel):
    type: Literal["ospf_full", "bgp_established", "route_nexthop", "ping"]
    router: str
    target: str                 
    expect: str | None = None

    @field_validator("router")
    @classmethod
    def _router_known(cls, v):
        if v not in ROUTERS:
            raise ValueError(f"unknown router {v}")
        return v

class ChangePlan(BaseModel):
    intent: str
    rationale: str
    changes: list[RouterChange]
    expected_outcome: str = Field(description="What should be true after the change")
    risk: str = Field(description="low, medium or high, with a reason")
    checks: list[Check] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list, description="List of exact SOURCE IDs used from the documentation")

SNAP_DIR = "snapshots"

def snapshot(router: str, prefix: str = PREFIX) -> str:
    os.makedirs(SNAP_DIR, exist_ok=True)
    path = f"{SNAP_DIR}/{router}-{time.time_ns()}.conf"
    with open(path, "w") as f:
        f.write(running_config(router, prefix=prefix))
    return path

def dry_run(change: RouterChange, prefix: str = PREFIX) -> str:
    before = running_config(change.router, prefix=prefix).splitlines()
    after = before + [c for c in change.commands if c.strip().lower() != "configure terminal"]
    return "\n".join(difflib.unified_diff(before, after, "running", "candidate", lineterm=""))

def apply(change: RouterChange, prefix: str = PREFIX) -> str:
    args = ["vtysh", "-c", "configure terminal"]
    for line in change.commands:
        if any(ord(c) < 32 for c in line):
            raise ToolError("Control characters are not allowed in config lines")
        if line.strip().lower() == "configure terminal":
            continue
        args += ["-c", line]
    return _exec(change.router, args, prefix=prefix)

def rollback(router: str, snapshot_path: str, prefix: str = PREFIX) -> None:
    remote = "/tmp/rollback.conf"
    subprocess.run(["docker", "cp", snapshot_path, f"{prefix}{router}:{remote}"], check=True)
    _exec(router, ["/usr/lib/frr/frr-reload.py", "--reload", "--overwrite", remote], timeout=60, prefix=prefix)

def normalize_config(text: str) -> list[str]:
    """Config lines with comments/blank lines removed, for exact before/after comparison."""
    return [l.rstrip() for l in text.splitlines() if l.strip() and not l.lstrip().startswith("!")]

def config_matches_snapshot(router: str, snapshot_path: str, prefix: str = PREFIX) -> bool:
    """True if the router's running config equals the saved snapshot (rollback correctness)."""
    with open(snapshot_path) as f:
        saved = normalize_config(f.read())
    return normalize_config(running_config(router, prefix=prefix)) == saved
