import subprocess, sys

PREFIX = "clab-netops-"

FAILURES = {
    "ospf_area_mismatch": {"router": "r2", "vtysh": [
        "interface eth1", "no ip ospf area", "ip ospf area 1"]},
    "ospf_hello_mismatch": {"router": "r2", "vtysh": [
        "interface eth1", "ip ospf hello-interval 3"]},
    "ospf_passive": {"router": "r3", "vtysh": [
        "router ospf", "passive-interface eth2"]},
    "bgp_wrong_asn": {"router": "r1", "vtysh": [
        "router bgp 65001", "neighbor 10.1.15.2 remote-as 65099"]},
    "bgp_deny_all_in": {"router": "r4", "vtysh": [
        "route-map DENY-ALL deny 10", "exit",
        "router bgp 65001", "address-family ipv4 unicast",
        "neighbor 10.1.46.2 route-map DENY-ALL in"]},
    "link_down": {"router": "r2", "shell": "ip link set eth2 down"},
    "mtu_mismatch": {"router": "r3", "shell": "ip link set eth2 mtu 1400"},
}

def inject(name: str) -> None:
    f = FAILURES[name]
    container = PREFIX + f["router"]
    if "shell" in f:
        cmd = ["docker", "exec", container, "sh", "-c", f["shell"]]
    else:
        cmd = ["docker", "exec", container, "vtysh", "-c", "configure terminal"]
        for line in f["vtysh"]:
            cmd += ["-c", line]
    subprocess.run(cmd, check=True)
    print(f"Injected {name} on {f['router']}")

if __name__ == "__main__":
    inject(sys.argv[1])
