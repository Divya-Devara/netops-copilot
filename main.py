import json, uuid
from langgraph.types import Command
from netops.agents.graph import graph

while True:
    intent = input("\nIntent> ")
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    out = graph.invoke({"intent": intent}, config)
    if "__interrupt__" in out:
        info = out["__interrupt__"][0].value
        print(json.dumps(info["plan"], indent=2))
        for router, diff in info["diffs"].items():
            print(f"--- {router} ---\n{diff}")
        decision = input("approve / reject? ")
        out = graph.invoke(Command(resume=decision), config)
    print(out.get("answer") or ("Change OK" if out.get("ok") else "Rejected or rolled back"))

