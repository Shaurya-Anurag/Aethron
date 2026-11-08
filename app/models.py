from pydantic import BaseModel, Field

class AssessmentCreate(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    objective: str = Field(min_length=8, max_length=1200)
    scope_text: str = Field(min_length=1, max_length=8000)
    mode: str = "live"  # live | demo

class ActionProposal(BaseModel):
    action: str
    target: str | None = None
    rationale: str = ""
