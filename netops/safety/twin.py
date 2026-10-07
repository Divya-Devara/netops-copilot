import os, subprocess, time
from netops.tools import frr, checks

TWIN = "clab-twin-"

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
        time.sleep(30)  # converge
        for c in plan.changes:
            frr.apply(c, prefix=TWIN)
        time.sleep(20)
        return checks.run_all(plan.checks, prefix=TWIN)
    finally:
        subprocess.run(["sudo", "containerlab", "destroy", "-t", "lab/twin.clab.yml"],
                       capture_output=True)
