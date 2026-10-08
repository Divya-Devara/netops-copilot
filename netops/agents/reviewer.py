from pydantic import BaseModel, Field
from langchain_ollama import ChatOllama
from netops.agents.prompts import REVIEWER_PROMPT
import json

class Review(BaseModel):
    approve: bool = Field(description="True if the plan is safe and achieves the intent")
    concerns: list[str] = Field(description="List of specific risks, missing steps, or rule violations")

llm = ChatOllama(model="qwen2.5:7b", temperature=0)

def run_reviewer(intent: str, plan_dict: dict, state_dict: dict) -> dict:
    """Wraps the structured LLM call for the Reviewer."""
    prompt = REVIEWER_PROMPT.format(
        intent=intent, 
        plan=json.dumps(plan_dict, indent=2), 
        state=json.dumps(state_dict)
    )
    
    # We use with_structured_output to force the LLM to return our Review Pydantic model
    review = llm.with_structured_output(Review).invoke(prompt)
    return review.model_dump()
