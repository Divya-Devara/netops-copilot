import os, subprocess, time
from netops.tools import frr, checks

TWIN = "clab-twin-"

def _wait_for_ospf_convergence(prefix: str, timeout: int = 45) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            ok = all(
                n[0].get("nbrState", "").startswith("Full")
                for r in ("r1", "r2", "r3", "r4")
                for n in frr.ospf_neighbors(r, prefix=prefix).get("neighbors", {}).values()
            )
            if ok:
                return
        except Exception:
            pass
        time.sleep(3)

def _wait_for_bgp_convergence(prefix: str, timeout: int = 30) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            ok = all(
                p.get("state") == "Established"
                for r in ("r1", "r4")
                for p in frr.bgp_summary(r, prefix=prefix).get("ipv4Unicast", {}).get("peers", {}).values()
            )
            if ok:
                return
        except Exception:
            pass
        time.sleep(3)


def twin_test(plan) -> dict:
    # 1. Clone today's production configs into the twin
    for r in sorted(frr.ROUTERS):
        os.makedirs(f"lab/twin-configs/{r}", exist_ok=True)
        with open(f"lab/twin-configs/{r}/frr.conf", "w") as f:
            f.write(frr.running_config(r))
        subprocess.run(["cp", "lab/configs/" + r + "/daemons", f"lab/twin-configs/{r}/daemons"], check=True)
    subprocess.run(["sudo", "containerlab", "deploy", "-t", "lab/twin.clab.yml",
                    "--reconfigure"], check=True, capture_output=True)
    try:
        _wait_for_ospf_convergence(prefix=TWIN, timeout=45)
        for c in plan.changes:
            frr.apply(c, prefix=TWIN)
        _wait_for_bgp_convergence(prefix=TWIN, timeout=30)
        return checks.run_all(plan.checks, prefix=TWIN)
    

    finally:
        subprocess.run(["sudo", "containerlab", "destroy", "-t", "lab/twin.clab.yml"],
                       capture_output=True)
