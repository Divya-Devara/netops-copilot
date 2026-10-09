"""Deterministic root-cause helper: compare both ends of a link/session and list configuration mismatches.
parse_config / diagnose_ospf / diagnose_bgp are pure (config text in, findings out) so they are unit tested."""
import ipaddress, re
from netops.tools import frr
from netops.tools.topology import LINKS, link_key

def parse_config(text: str) -> dict:
    """{section header: [indented lines]} for top-level blocks such as 'interface eth1' or 'router ospf'."""
    sections, cur = {}, None
    for raw in text.splitlines():
        if not raw.strip() or raw.startswith("!"):
            continue
        if raw.startswith(" "):
            if cur is not None:
                sections[cur].append(raw.strip())
        elif raw.strip() == "exit":
            cur = None
        else:
            cur = raw.strip()
            sections.setdefault(cur, [])
    return sections

def _iface(cfg, name):
    lines = cfg.get(f"interface {name}")
    return lines if lines is not None else []

def _opt(lines, prefix, default=None):
    for l in lines:
        if l.startswith(prefix):
            return l[len(prefix):].strip()
    return default

def _network(lines):
    ip = _opt(lines, "ip address ")
    return ipaddress.ip_interface(ip).network if ip else None

def diagnose_ospf(cfg_a, ia, cfg_b, ib, a, b) -> list[str]:
    la, lb, out = _iface(cfg_a, ia), _iface(cfg_b, ib), []
    for r, i, l in ((a, ia, la), (b, ib, lb)):
        if "shutdown" in l:
            out.append(f"{r} {i} is administratively shut down")
    na, nb = _network(la), _network(lb)
    if na is None or nb is None:
        out.append("an interface has no IP address configured")
    elif na != nb:
        out.append(f"subnet mismatch: {a} {i_str(la)} vs {b} {i_str(lb)}")
    aa, ab = _opt(la, "ip ospf area "), _opt(lb, "ip ospf area ")
    if aa is None or ab is None:
        out.append(f"OSPF is not enabled on {a if aa is None else b} {ia if aa is None else ib} (no 'ip ospf area')")
    elif aa != ab:
        out.append(f"area mismatch: {a} {ia} is in area {aa} but {b} {ib} is in area {ab}")
    for opt, default in (("ip ospf hello-interval ", "10"), ("ip ospf dead-interval ", "40"), ("ip ospf network ", "broadcast")):
        va, vb = _opt(la, opt, default), _opt(lb, opt, default)
        if va != vb:
            out.append(f"'{opt.strip()}' mismatch: {a}={va}, {b}={vb}")
    for r, cfg, i in ((a, cfg_a, ia), (b, cfg_b, ib)):
        ospf = cfg.get("router ospf", [])
        if f"passive-interface {i}" in ospf or ("passive-interface default" in ospf and f"no passive-interface {i}" not in ospf):
            out.append(f"{r} {i} is passive in OSPF (it sends no hellos, so no adjacency can form)")
    ca, cb = _opt(la, "ip ospf cost "), _opt(lb, "ip ospf cost ")
    if ca != cb:
        out.append(f"note: OSPF cost differs (informational, does not break the adjacency): {a}={ca or 'default'}, {b}={cb or 'default'}")
    return out

def i_str(lines):
    return _opt(lines, "ip address ", "no address")

def diagnose_bgp(cfg_a, cfg_b, a, b, peer_ip_from_a) -> list[str]:
    out = []
    asn_a = next((h.split()[-1] for h in cfg_a if h.startswith("router bgp ")), None)
    asn_b = next((h.split()[-1] for h in cfg_b if h.startswith("router bgp ")), None)
    if asn_a is None or asn_b is None:
        return [f"BGP is not configured on {a if asn_a is None else b}"]
    bgp_a = cfg_a[f"router bgp {asn_a}"]
    expect = next((l.split()[3] for l in bgp_a if l.startswith(f"neighbor {peer_ip_from_a} remote-as ")), None)
    if expect is None:
        out.append(f"{a} has no 'neighbor {peer_ip_from_a} remote-as ...' statement")
    elif expect != asn_b:
        out.append(f"AS mismatch: {a} expects {peer_ip_from_a} ({b}) to be AS {expect}, but {b} actually runs AS {asn_b}")
    a_ip = None
    for h, lines in cfg_a.items():
        if h.startswith("interface ") and any(l.startswith("ip address ") for l in lines):
            net = _network(lines)
            if net and ipaddress.ip_address(peer_ip_from_a) in net:
                a_ip = _opt(lines, "ip address ").split("/")[0]
    bgp_b = cfg_b[f"router bgp {asn_b}"]
    if a_ip:
        back = next((l.split()[3] for l in bgp_b if l.startswith(f"neighbor {a_ip} remote-as ")), None)
        if back is None:
            out.append(f"{b} has no 'neighbor {a_ip} remote-as ...' statement for {a}")
        elif back != asn_a:
            out.append(f"AS mismatch: {b} expects {a_ip} ({a}) to be AS {back}, but {a} actually runs AS {asn_a}")
    for r, lines, ip in ((a, bgp_a, peer_ip_from_a), (b, bgp_b, a_ip)):
        if ip and f"neighbor {ip} shutdown" in lines:
            out.append(f"{r} has 'neighbor {ip} shutdown' (session administratively down)")
    return out

def diagnose_link(a: str, b: str) -> str:
    key = link_key(a, b)
    link = next((l for l in LINKS if link_key(l[0], l[1]) == key), None)
    if link is None:
        return f"{a}-{b} is not a direct link in this lab. Direct links: " + ", ".join(link_key(l[0], l[1]) for l in LINKS)
    x, y, proto, subnet, ix, iy, peer = link
    cfg = {r: parse_config(frr.running_config(r)) for r in (x, y)}
    if proto == "ospf":
        found = diagnose_ospf(cfg[x], ix, cfg[y], iy, x, y)
        state = f"{x} {ix} <-> {y} {iy}, subnet {subnet}"
    else:
        found = diagnose_bgp(cfg[x], cfg[y], x, y, peer)
        state = f"eBGP {x} <-> {y}, subnet {subnet}, peer {peer}"
    real = [f for f in found if not f.startswith("note:")]
    head = f"Link {key} ({proto.upper()}): {state}"
    if not real:
        return head + "\nNo configuration mismatch found between the two ends." + ("".join("\n- " + f for f in found))
    return head + "\nConfiguration problems found:" + "".join("\n- " + f for f in found)
