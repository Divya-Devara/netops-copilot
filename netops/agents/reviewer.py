import json, os
from functools import lru_cache
from pydantic import BaseModel, Field
from netops.agents.llm import make_llm
from netops.agents.prompts import REVIEWER_PROMPT

class Review(BaseModel):
    approve: bool = Field(description="True if the plan is safe and achieves the intent")
    concerns: list[str] = Field(description="List of specific risks, missing steps, or rule violations")

@lru_cache(maxsize=1)
def _llm():
    # A different model than the planner reduces correlated mistakes (set NETOPS_REVIEWER_MODEL).
    model = os.environ.get("NETOPS_REVIEWER_MODEL") or os.environ.get("NETOPS_MODEL", "qwen2.5:7b")
    return make_llm(model)

def run_reviewer(intent: str, plan_dict: dict, state_dict: dict) -> dict:
    """Wraps the structured LLM call for the Reviewer."""
    prompt = REVIEWER_PROMPT.format(
        intent=intent,
        plan=json.dumps(plan_dict, indent=2),
        state=json.dumps(state_dict),
    )
    return _llm().with_structured_output(Review).invoke(prompt).model_dump()
