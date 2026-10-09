import json, uuid
from langgraph.types import Command
from netops.agents.graph import graph

while True:
    intent = input("\nIntent> ")
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    out = graph.invoke({"intent": intent}, config)

    if out.get("blocked_reason"):
        print(f"\n[BLOCKED] {out['blocked_reason']}")
        continue

    if "__interrupt__" in out:
        info = out["__interrupt__"][0].value
        print(json.dumps(info["plan"], indent=2))
        for router, diff in info["diffs"].items():
            print(f"--- {router} ---\n{diff}")
        if info["policy"]["warnings"]:
            print("\n[POLICY WARNINGS]")
            for w in info["policy"]["warnings"]:
                print(f"  - {w}")
        print(f"\n[TWIN TEST] ok={info['twin']['ok']}")
        for k, v in info["twin"]["results"].items():
            print(f"  {k}: {v}")
        decision = input("\napprove / reject? ")
        out = graph.invoke(Command(resume=decision), config)

    print(out.get("answer") or ("Change OK" if out.get("ok") else "Rejected or rolled back"))
