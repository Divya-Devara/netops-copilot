from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent
from langchain_ollama import ChatOllama
from netops.tools import frr
from netops.agents.prompts import TOPOLOGY

@tool
def show_command(router: str, command: str) -> str:
    """Run a read-only FRR 'show' command on a router (r1, r2, r3, r4, r5, r6) and return the output.
    Focus on 'show bgp summary', 'show ip ospf neighbor', and 'show ip route'. 
    IGNORE any 172.x.x.x routes on eth0; those are Docker management routes."""
    try:
        return frr.show(router, command)[:4000]
    except frr.ToolError as e:
        return f"ERROR: {e}"

llm = ChatOllama(model="qwen2.5:7b", temperature=0)
tools = [show_command]

diagnoser_agent = create_react_agent(llm, tools)

def run_diagnoser(issue: str) -> str:
    system_prompt = f"""You are an expert network diagnoser. 
Here is the network topology:
{TOPOLOGY}

Rules:
1. You MUST use 'show_command' to investigate. 
2. Trace the path: r5 peers with r1. r1 and r4 peer via iBGP. r6 peers with r4.
3. Check BGP summaries on r1, r5, r4, and r6 to see if any sessions are 'Active' or 'Idle' instead of 'Established'.
4. IGNORE 172.x.x.x Docker routes.
5. Provide a FINAL DIAGNOSIS stating the root cause, affected routers, and the exact CLI output that proves it.
"""
    messages = [
        ("system", system_prompt),
        ("user", issue)
    ]
    
    print("Starting Diagnoser loop...")
    for chunk in diagnoser_agent.stream({"messages": messages}):
        if "agent" in chunk:
            msg = chunk["agent"]["messages"][0]
            if hasattr(msg, 'tool_calls') and msg.tool_calls:
                for tc in msg.tool_calls:
                    print(f"🕵️ Agent running: {tc['name']} with {tc['args']}")
                    
    result = diagnoser_agent.invoke({"messages": messages})
    return "\n--- FINAL DIAGNOSIS ---\n" + result["messages"][-1].content
