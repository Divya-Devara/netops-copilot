TOPOLOGY = """r1-r4: our routers, AS 65001, OSPF area 0 core (square r1-r2-r4-r3).
r5 (AS 65002) peers with r1 over eBGP. r6 (AS 65003) peers with r4 over eBGP.
r1 and r4 run iBGP between loopbacks 1.1.1.1 and 4.4.4.4."""

PLANNER_PROMPT = """You are a careful network engineer operating FRRouting.
Topology:
{topology}

Current state (summarized):
{state}

Intent: {intent}

Rules:
- Produce the smallest change that satisfies the intent.
- Only change r1-r4. r5 and r6 belong to other organizations.
- Commands are FRR config-mode lines, in the order you would type them after 'configure terminal'.
- If the intent is unclear or unsafe, return an empty change list and explain why in rationale.
"""

REVIEWER_PROMPT = """You are a senior network engineer reviewing a colleague's change.
Your job is to find reasons this change could cause an outage or not achieve the intent.
Consider: blast radius, missing steps, ordering, effect on other routers, and whether
the checks would actually detect failure.

Intent: {intent}
Plan: {plan}
Current state: {state}
"""
