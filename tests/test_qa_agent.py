import sys; sys.path.insert(0, '.')
import pytest
from netops.agents import qa_agent as qa
from netops.agents.graph import classify
from netops.tools import faults, frr, health, linkdiag, topology

# ───────── link diagnosis (pure config parsing) ─────────
R1 = """interface eth1
 ip address 10.0.12.1/30
 ip ospf area 0
 ip ospf cost 100
exit
router bgp 65001
 neighbor 10.1.15.2 remote-as 65099
exit
"""
R2 = """interface eth1
 ip address 10.0.12.2/30
 ip ospf area 1
exit
"""
R5 = """interface eth1
 ip address 10.1.15.2/30
exit
router bgp 65002
 neighbor 10.1.15.1 remote-as 65001
exit
"""

def test_ospf_area_mismatch_is_found():
    out = linkdiag.diagnose_ospf(linkdiag.parse_config(R1), "eth1", linkdiag.parse_config(R2), "eth1", "r1", "r2")
    assert any("area mismatch" in f and "area 0" in f and "area 1" in f for f in out)

def test_ospf_cost_difference_is_only_a_note():
    same_area = R1.replace("ip ospf cost 100\n", "")
    r1 = linkdiag.parse_config(R1)
    r2 = linkdiag.parse_config(same_area.replace("10.0.12.1", "10.0.12.2"))
    out = linkdiag.diagnose_ospf(r1, "eth1", r2, "eth1", "r1", "r2")
    assert out and all(f.startswith("note:") for f in out)

def test_passive_and_shutdown_detected():
    cfg = linkdiag.parse_config("interface eth2\n ip address 10.0.34.1/30\n ip ospf area 0\n shutdown\nexit\nrouter ospf\n passive-interface eth2\nexit\n")
    ok = linkdiag.parse_config("interface eth2\n ip address 10.0.34.2/30\n ip ospf area 0\nexit\n")
    out = linkdiag.diagnose_ospf(cfg, "eth2", ok, "eth2", "r3", "r4")
    assert any("shut down" in f for f in out) and any("passive" in f for f in out)

def test_bgp_as_mismatch_is_found():
    out = linkdiag.diagnose_bgp(linkdiag.parse_config(R1), linkdiag.parse_config(R5), "r1", "r5", "10.1.15.2")
    assert any("AS mismatch" in f and "65099" in f and "65002" in f for f in out)

def test_diagnose_link_rejects_non_adjacent_routers():
    assert "not a direct link" in linkdiag.diagnose_link("r2", "r3")

# ───────── health analysis (pure) ─────────
IDS = topology.ROUTER_IDS

def _full(*routers):
    return {"neighbors": {IDS[r]: [{"nbrState": "Full/DR"}] for r in routers}}

def _bgp(peers):
    return {"ipv4Unicast": {"peers": {ip: {"state": st} for ip, st in peers.items()}}}

def _snap(ospf_ok=True, ebgp_ok=True):
    return {
        "r1": {"ospf": _full("r2", "r3") if ospf_ok else _full("r3"),
               "bgp": _bgp({"4.4.4.4": "Established", "10.1.15.2": "Established" if ebgp_ok else "Idle"})},
        "r2": {"ospf": _full("r1", "r4"), "bgp": _bgp({})},
        "r3": {"ospf": _full("r1", "r4"), "bgp": _bgp({})},
        "r4": {"ospf": _full("r2", "r3"), "bgp": _bgp({"1.1.1.1": "Established", "10.1.46.2": "Established"})},
        "r5": {"bgp": _bgp({"10.1.15.1": "Established"})},
        "r6": {"bgp": _bgp({"10.1.46.1": "Established"})},
    }

def test_healthy_network():
    r = health.analyze(_snap())
    assert r["healthy"] and set(r["routers"].values()) == {"ok"} and set(r["links"].values()) == {"up"}

def test_missing_ospf_neighbor_marks_link_down_and_routers_degraded():
    r = health.analyze(_snap(ospf_ok=False))
    assert r["links"]["r1-r2"] == "down" and r["routers"]["r1"] == r["routers"]["r2"] == "degraded"
    assert r["routers"]["r3"] == "ok" and any("r1-r2" in i for i in r["issues"])

def test_ebgp_down_and_unreachable_router():
    assert health.analyze(_snap(ebgp_ok=False))["links"]["r1-r5"] == "down"
    s = _snap(); s["r3"] = None
    r = health.analyze(s)
    assert r["routers"]["r3"] == "down" and r["links"]["r1-r3"] == "down" and not r["healthy"]

# ───────── what-if (static topology) ─────────
def test_what_if_link_reroutes_without_losing_connectivity():
    out = topology.what_if_down("r2-r4")
    assert "none (the network stays fully connected)" in out and "r1-r3-r4" in out

def test_what_if_router_isolates_external_as():
    assert "r2<->r5" in topology.what_if_down("r1")      # r5 only hangs off r1

def test_what_if_rejects_unknown_element():
    assert "Unknown element" in topology.what_if_down("r9")

# ───────── agent helpers ─────────
def test_citations_must_come_from_retrieved_docs():
    cited, bad = qa.check_citations("answer\nSources: a-1, fake-9", ["a-1"])
    assert cited == ["a-1", "fake-9"] and bad == ["fake-9"]

def test_sources_noise_is_not_a_citation():
    cited, bad = qa.check_citations("answer\nSources: No Sources line applicable", [])
    assert cited == [] and bad == []

def test_tool_call_printed_as_text_is_recovered():
    text = 'Let me check.\n```json\n{"name": "show_command", "arguments": {"router": "r1", "command": "show ip route"}}\n```'
    calls = qa._recover_tool_call(text, {"show_command"})
    assert calls and calls[0]["args"]["router"] == "r1"
    assert qa._recover_tool_call('{"name": "rm_rf", "arguments": {}}', {"show_command"}) is None

def test_concept_vs_live_questions():
    assert qa.is_concept_question("How does OSPF DR election work?")
    assert not qa.is_concept_question("Why is the OSPF adjacency on r1 down?")
    assert not qa.is_concept_question("What is wrong with my network right now?")

def test_history_only_for_follow_ups():
    assert qa.wants_history("and from r2?")
    assert not qa.wants_history("Why is the OSPF adjacency between r1 and r2 not forming right now?")

# ───────── classification: questions stay read-only, changes never take the fast path ─────────
@pytest.mark.parametrize("q", ["What is wrong with the network?", "ping 6.6.6.6 from r5", "Why is r1 down?",
                               "Is r3 healthy?", "Show OSPF neighbors on r1"])
def test_questions_use_fast_path(q):
    assert classify({"intent": q}) == {"kind": "question"}

def test_question_shaped_change_skips_the_fast_path(monkeypatch):
    from netops.agents import graph as G
    calls = []
    class Fake:
        def with_structured_output(self, _):
            calls.append("llm")
            return self
        def invoke(self, _):
            return G.Kind(kind="change")
    monkeypatch.setattr(G, "fast_llm", lambda: Fake())
    assert G.classify({"intent": "Can you set the OSPF cost on r1 eth1 to 100?"}) == {"kind": "change"}
    assert calls == ["llm"]          # went to the LLM classifier instead of the regex shortcut

# ───────── read-only tool safety ─────────
def test_ping_rejects_non_ip_and_flag_injection():
    for bad in ("1.1.1.1; reboot", "-f", "example.com", "1.1.1.1/24"):
        with pytest.raises(frr.ToolError):
            frr.ping("r1", bad)

def test_qa_agent_has_no_config_changing_tool():
    names = {t.name for t in qa.make_tools({})}
    assert names == {"show_command", "ping", "traceroute", "get_running_config", "diagnose_link",
                     "network_health", "what_if_down", "search_docs_tool"}
    with pytest.raises(frr.ToolError):
        frr.show("r1", "configure terminal")

def test_fault_catalog_has_exact_undo_for_each_fault():
    for f in faults.FAULTS.values():
        assert f["inject"] and f["undo"] and f["router"] in frr.ROUTERS
    assert {c["id"] for c in faults.catalog()} == set(faults.FAULTS)

# ───────── follow-up rewriting is validated, never trusted blindly ─────────
class _Say:
    def __init__(self, text): self.text = text
    def invoke(self, _):
        class R: pass
        r = R(); r.content = self.text
        return r

HIST = [{"q": "ping 6.6.6.6 from r5", "a": "failed"}]

def test_condense_accepts_faithful_rewrite():
    assert qa.condense("and from r2?", HIST, _Say("ping 6.6.6.6 from r2")) == "ping 6.6.6.6 from r2"

def test_condense_rejects_invented_router():
    assert qa.condense("and the BGP session to r5?", HIST, _Say("Why is the BGP session between r2 and r5 down?")) == "and the BGP session to r5?"

def test_condense_rejects_dropping_the_followups_router():
    assert qa.condense("and from r2?", HIST, _Say("ping 6.6.6.6 from r5")) == "and from r2?"

def test_link_hint_picks_the_named_link():
    assert qa.link_hint("Why is the OSPF adjacency between r1 and r2 down?") == ("r1", "r2")
    assert qa.link_hint("and the BGP session to r5?") == ("r1", "r5")          # r5 has exactly one peer
    assert qa.link_hint("Is r6 reachable?") is None                              # no link words
    assert qa.link_hint("Why is the session between r2 and r3 down?") is None   # not adjacent
