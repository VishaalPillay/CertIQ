# api/models/responses.py
from pydantic import BaseModel
from typing import Any

class HealthResponse(BaseModel):
    status: str                  # "ok"
    agents: int                  # 7
    knowledge_chunks: int        # 62
    version: str                 # "1.0.0"

class AgentAPIResponse(BaseModel):
    """Wraps AgentResponse for HTTP transport."""
    success: bool
    agent: str
    confidence: float
    result: Any
    reasoning_trace: list[str]
    citations: list[Any]
    verification_passed: bool
    was_reflected: bool          # True if confidence triggered a reflection retry

class PlanHealthResponse(BaseModel):
    employee_id: str
    plan_health: dict[str, Any]  # PlanHealth schema serialised
    availability_factor: float
    computed_at: str             # ISO datetime

class TeamReadinessResponse(BaseModel):
    manager_id: str
    team: dict[str, Any]         # FabricIQ.get_team_readiness() output
    heatmap: list[dict[str, Any]]  # FabricIQ.get_heatmap_data() output

class HITLApprovalResponse(BaseModel):
    employee_id: str
    certification_id: str
    decision: str
    approved_by: str             # manager_id
    timestamp: str

class APIError(BaseModel):
    error: str
    detail: str
    agent: str | None = None
    confidence: float | None = None
