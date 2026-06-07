# api/routes/learner.py
import asyncio
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from api.dependencies import get_orchestrator, get_work_iq
from api.models.requests import ChatRequest, RoadmapRequest, StudyPlanRequest
from api.models.responses import AgentAPIResponse, PlanHealthResponse
from data.loader import get_employee, get_employee_history
from reasoning.plan_health import PlanHealthEngine

router = APIRouter(prefix="/learner", tags=["Learner"])

def wrap_agent_response(resp) -> AgentAPIResponse:
    """Helper to convert AgentResponse schema to AgentAPIResponse model."""
    citations = []
    for c in resp.citations:
        if hasattr(c, "model_dump"):
            citations.append(c.model_dump())
        elif hasattr(c, "dict"):
            citations.append(c.dict())
        else:
            citations.append(c)
            
    return AgentAPIResponse(
        success=resp.verification.passed,
        agent=resp.agent_name,
        confidence=resp.confidence_score,
        result=resp.result,
        reasoning_trace=resp.reasoning_trace,
        citations=citations,
        verification_passed=resp.verification.passed,
        was_reflected=resp.verification.was_revised
    )

@router.get("/{employee_id}")
async def get_learner_profile(employee_id: str):
    """Get employee profile and a brief summary of progress."""
    emp = get_employee(employee_id)
    if not emp:
        raise HTTPException(status_code=404, detail=f"Employee {employee_id} not found")
        
    history = get_employee_history(employee_id) or {"sessions": []}
    sessions = history.get("sessions", [])
    completed_hours = sum(s.get("duration_minutes", 0) / 60.0 for s in sessions)
    
    return {
        "profile": emp,
        "progress": {
            "completed_study_hours": round(completed_hours, 2),
            "sessions_count": len(sessions),
        }
    }

@router.post("/{employee_id}/chat", response_model=AgentAPIResponse)
async def chat_with_orchestrator(
    employee_id: str,
    req: ChatRequest,
    orchestrator = Depends(get_orchestrator)
):
    """Free-text chat with the orchestrator, which plans and routes requests."""
    emp = get_employee(employee_id)
    if not emp:
        raise HTTPException(status_code=404, detail=f"Employee {employee_id} not found")

    context = {"employee_id": employee_id}
    # MANDATORY: execute sync agent in thread pool
    resp = await asyncio.to_thread(
        orchestrator.orchestrate,
        user_query=req.user_query,
        context=context
    )
    return wrap_agent_response(resp)

@router.post("/{employee_id}/roadmap", response_model=AgentAPIResponse)
async def generate_certification_roadmap(
    employee_id: str,
    req: RoadmapRequest,
    orchestrator = Depends(get_orchestrator)
):
    """Generate a certification roadmap using the Curator agent."""
    emp = get_employee(employee_id)
    if not emp:
        raise HTTPException(status_code=404, detail=f"Employee {employee_id} not found")

    context = {
        "employee_id": employee_id,
        "target_cert_code": req.target_certification
    }
    user_query = f"Create a certification roadmap for {req.target_certification}"
    
    resp = await asyncio.to_thread(
        orchestrator.orchestrate,
        user_query=user_query,
        context=context
    )
    return wrap_agent_response(resp)

@router.post("/{employee_id}/study-plan", response_model=AgentAPIResponse)
async def generate_study_plan(
    employee_id: str,
    req: StudyPlanRequest,
    orchestrator = Depends(get_orchestrator)
):
    """Generate a calendar-aware weekly study plan using the Study Plan Generator agent."""
    emp = get_employee(employee_id)
    if not emp:
        raise HTTPException(status_code=404, detail=f"Employee {employee_id} not found")

    context = {
        "employee_id": employee_id,
        "target_cert_code": req.target_certification,
        "target_weeks": req.target_weeks
    }
    user_query = f"Create a calendar-aware study plan for {req.target_certification} over {req.target_weeks} weeks"
    
    resp = await asyncio.to_thread(
        orchestrator.orchestrate,
        user_query=user_query,
        context=context
    )
    return wrap_agent_response(resp)

@router.get("/{employee_id}/plan-health", response_model=PlanHealthResponse)
async def get_plan_health(employee_id: str, work_iq = Depends(get_work_iq)):
    """Compute Plan Health score and availability factor."""
    emp = get_employee(employee_id)
    if not emp:
        raise HTTPException(status_code=404, detail=f"Employee {employee_id} not found")
        
    history = get_employee_history(employee_id) or {"sessions": []}
    sessions = history.get("sessions", [])
    
    # completed hours over last 14 days
    completed = sum(s.get("duration_minutes", 0) / 60.0 for s in sessions[-14:])
    # 5 hours recommended weekly hours -> 10 hours for 2 weeks
    recommended = 10.0
    
    af = work_iq.compute_availability_factor(employee_id)
    ph = PlanHealthEngine.calculate(completed, recommended, af)
    
    return PlanHealthResponse(
        employee_id=employee_id,
        plan_health=ph.model_dump(),
        availability_factor=af,
        computed_at=datetime.utcnow().isoformat()
    )

@router.get("/{employee_id}/progress")
async def get_learner_progress(employee_id: str):
    """Get detailed learning history metrics."""
    emp = get_employee(employee_id)
    if not emp:
        raise HTTPException(status_code=404, detail=f"Employee {employee_id} not found")
        
    history = get_employee_history(employee_id) or {"sessions": []}
    sessions = history.get("sessions", [])
    
    completed_hours = sum(s.get("duration_minutes", 0) / 60.0 for s in sessions)
    quiz_scores = [s.get("quiz_score", 0.0) for s in sessions if "quiz_score" in s]
    avg_score = sum(quiz_scores) / len(quiz_scores) if quiz_scores else 0.0
    
    topics = list(set(s.get("topic", "") for s in sessions if s.get("topic")))
    
    return {
        "employee_id": employee_id,
        "total_study_hours": round(completed_hours, 2),
        "sessions_count": len(sessions),
        "avg_quiz_score": round(avg_score, 2),
        "topics_covered": topics
    }
