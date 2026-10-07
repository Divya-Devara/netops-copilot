import json, subprocess
from pydantic import BaseModel, Field
from typing import Literal
import difflib, os, time

PREFIX = "clab-netops-"
ROUTERS = {"r1", "r2", "r3", "r4", "r5", "r6"}

class ToolError(Exception):
    pass

def _exec(router: str, args: list[str], timeout: int = 20, prefix: str = PREFIX) -> str:
    if router not in ROUTERS:
        raise ToolError(f"Unknown router {router}")
    res = subprocess.run(["docker", "exec", prefix + router, *args],
                         capture_output=True, text=True, timeout=timeout)
    if res.returncode != 0:
        raise ToolError(res.stderr.strip() or res.stdout.strip())
    return res.stdout

def show(router: str, command: str, prefix: str = PREFIX) -> str:
    """Read-only. Only 'show' commands are allowed."""
    if not command.strip().startswith("show ") or any(c in command for c in ";|&`$"):
        raise ToolError("Only plain 'show' commands are allowed")
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
    # Strip the human-readable headers FRR adds so frr-reload doesn't choke on them
    lines = [line for line in raw.splitlines() if line != "Building configuration..." and line != "Current configuration:"]
    return "\n".join(lines)

def network_snapshot(prefix: str = PREFIX) -> dict:
    """One call that gives the agent a picture of the whole network."""
    snap = {}
    for r in sorted(ROUTERS):
        snap[r] = {"bgp": bgp_summary(r, prefix=prefix)}
        if r in {"r1", "r2", "r3", "r4"}:
            snap[r]["ospf"] = ospf_neighbors(r, prefix=prefix)
    return snap

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
    target: str                 # neighbor ID, peer IP, prefix, or destination IP
    expect: str | None = None   # e.g. the expected next hop for route_nexthop

class ChangePlan(BaseModel):
    intent: str
    rationale: str
    changes: list[RouterChange]
    expected_outcome: str = Field(description="What should be true after the change")
    risk: str = Field(description="low, medium or high, with a reason")
    checks: list[Check] = Field(default_factory=list)

SNAP_DIR = "snapshots"

def snapshot(router: str, prefix: str = PREFIX) -> str:
    os.makedirs(SNAP_DIR, exist_ok=True)
    path = f"{SNAP_DIR}/{router}-{int(time.time())}.conf"
    with open(path, "w") as f:
        f.write(running_config(router, prefix=prefix))
    return path

def dry_run(change: RouterChange, prefix: str = PREFIX) -> str:
    """Show what would change, without touching the router."""
    before = running_config(change.router, prefix=prefix).splitlines()
    after = before + change.commands
    return "\n".join(difflib.unified_diff(before, after, "running", "candidate", lineterm=""))

def apply(change: RouterChange, prefix: str = PREFIX) -> str:
    args = ["vtysh", "-c", "configure terminal"]
    for line in change.commands:
        if line.strip().lower() == "configure terminal":
            continue  # already entered by the line above; avoid double-entry
        args += ["-c", line]
    return _exec(change.router, args, prefix=prefix)

def rollback(router: str, snapshot_path: str, prefix: str = PREFIX) -> None:
    """Restore a saved config using FRR's reload tool, which applies only the diff."""
    remote = "/tmp/rollback.conf"
    subprocess.run(["docker", "cp", snapshot_path, f"{prefix}{router}:{remote}"], check=True)
    _exec(router, ["/usr/lib/frr/frr-reload.py", "--reload", "--overwrite", remote], timeout=60, prefix=prefix)
