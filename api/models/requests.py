# api/models/requests.py
from pydantic import BaseModel, Field

class ChatRequest(BaseModel):
    user_query: str = Field(..., min_length=3, max_length=500)

class RoadmapRequest(BaseModel):
    target_certification: str = Field(..., description="E.g. AZ-204")

class StudyPlanRequest(BaseModel):
    target_certification: str = Field(..., description="E.g. AZ-204")
    target_weeks: int = Field(default=8, ge=2, le=26)

class AssessmentStartRequest(BaseModel):
    certification_id: str = Field(..., description="Certification code or ID (e.g. AZ-204 or cert_az204)")
    num_questions: int = Field(default=5, ge=1, le=10)

class AssessmentAnswerRequest(BaseModel):
    question_id: str = Field(..., description="ID of the question being answered")
    selected_option: int = Field(..., ge=0, le=3, description="Index of selected option (0 to 3)")

class ManagerQueryRequest(BaseModel):
    query: str = Field(..., min_length=3, max_length=500)

class HITLApprovalRequest(BaseModel):
    employee_id: str = Field(...)
    certification_id: str = Field(...)
    decision: str = Field(..., description="'approved' or 'deferred'")
    manager_notes: str = ""
