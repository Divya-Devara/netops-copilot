import atexit, os, shutil, subprocess, threading, time
from netops.tools import frr, checks

TWIN = "clab-twin-"
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LAB = os.path.join(ROOT, "lab")
TWIN_TOPO = os.path.join(LAB, "twin.clab.yml")

# One twin exists on the host (fixed container names), so runs must not overlap.
_lock = threading.Lock()

# NETOPS_TWIN_PERSIST=1 keeps the twin containers running between tests and resets them with
# frr-reload instead of a full redeploy (much faster). Off by default: the safe path is a
# fresh deploy every time.
PERSIST = os.environ.get("NETOPS_TWIN_PERSIST") == "1"
_deployed = False

def _wait_for_ospf_convergence(prefix: str, timeout: int = 45) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            ok = all(
                n[0].get("nbrState", "").startswith("Full")
                for r in sorted(frr.MANAGED)
                for n in frr.ospf_neighbors(r, prefix=prefix).get("neighbors", {}).values()
            )
            if ok:
                return
        except Exception:
            pass
        time.sleep(3)

def _containerlab(cmd: str) -> None:
    args = ["sudo", "containerlab", cmd, "-t", TWIN_TOPO, *(["--reconfigure"] if cmd == "deploy" else [])]
    try:
        subprocess.run(args, check=True, capture_output=True, text=True, timeout=240)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"containerlab {cmd} failed: {(e.stderr or '')[-300:]}")

def _clone_prod_configs() -> dict:
    """Write today's production configs into twin-configs/ (fetched in parallel)."""
    def fetch(r):
        return r, frr.running_config(r)
    configs = dict(frr.pmap(fetch, sorted(frr.ROUTERS)))
    for r, text in configs.items():
        d = os.path.join(LAB, "twin-configs", r)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "frr.conf"), "w") as f:
            f.write(text)
        shutil.copy(os.path.join(LAB, "configs", r, "daemons"), os.path.join(d, "daemons"))
    return configs

def _reset_twin(configs: dict) -> None:
    """Persistent mode: push production configs into the running twin via frr-reload."""
    def reset(r):
        path = os.path.join(LAB, "twin-configs", r, "frr.conf")
        frr.rollback(r, path, prefix=TWIN)
    frr.pmap(reset, sorted(configs))

def _destroy() -> None:
    global _deployed
    subprocess.run(["sudo", "containerlab", "destroy", "-t", TWIN_TOPO],
                   capture_output=True, timeout=120)
    _deployed = False

atexit.register(lambda: _deployed and _destroy())

def twin_test(plan) -> dict:
    """Apply the plan to a throwaway copy of the lab. Never raises: any failure is ok=False."""
    global _deployed
    with _lock:
        try:
            configs = _clone_prod_configs()
            if PERSIST and _deployed:
                _reset_twin(configs)
            else:
                _containerlab("deploy")
                _deployed = True
            _wait_for_ospf_convergence(prefix=TWIN, timeout=45)
            for c in plan.changes:
                frr.apply(c, prefix=TWIN)
            return checks.wait_until_ok(plan.checks, prefix=TWIN, timeout=40)
        except Exception as e:
            _deployed = False
            return {"ok": False, "results": {"twin_error": False}, "error": f"{type(e).__name__}: {e}"}
        finally:
            if not PERSIST:
                try:
                    _destroy()
                except Exception:
                    pass
