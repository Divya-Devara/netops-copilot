from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from langgraph.types import Command
import uuid

# Import your working graph from Phase 6
from netops.agents.graph import graph

app = FastAPI()

# Crucial: This allows your React app (running on a different port) to talk to this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # In production, restrict this to your frontend URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class RunRequest(BaseModel):
    thread_id: str
    intent: str

class ResumeRequest(BaseModel):
    thread_id: str
    decision: str  # Must be exactly "approve" or "reject"

@app.post("/api/run")
def run_agent(req: RunRequest):
    """Starts the graph. It will run until the interrupt() gate."""
    config = {"configurable": {"thread_id": req.thread_id}}
    
    # Run the graph with the user's intent
    out = graph.invoke({"intent": req.intent}, config)
    
    # If the graph pauses at our approval gate, return the pending plan data
    if "__interrupt__" in out:
        pending_data = out["__interrupt__"][0].value
        return {"status": "pending_approval", "data": pending_data}
    
    # If it didn't pause (e.g., read-only question or blocked by policy), return final state
    return {"status": "completed", "data": out}

@app.post("/api/resume")
def resume_agent(req: ResumeRequest):
    """Resumes the graph after human approval."""
    config = {"configurable": {"thread_id": req.thread_id}}
    
    # Resume the graph using the Command object, passing "approve" or "reject"
    out = graph.invoke(Command(resume=req.decision), config)
    
    return {"status": "completed", "data": out}