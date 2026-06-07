# api/routes/manager.py
import asyncio
from datetime import datetime
import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from api.dependencies import get_orchestrator, get_fabric_iq, get_hitl_store
from api.models.requests import ManagerQueryRequest, HITLApprovalRequest
from api.models.responses import AgentAPIResponse, TeamReadinessResponse, HITLApprovalResponse
from data.loader import get_employee, get_direct_reports, get_employee_history, get_employee_calendar
from reasoning.plan_health import PlanHealthEngine

router = APIRouter(prefix="/manager", tags=["Manager"])

HITL_LOG = Path("logs/hitl_approvals.jsonl")

@router.get("/{manager_id}/team", response_model=TeamReadinessResponse)
async def get_team_readiness_endpoint(manager_id: str, fabric_iq = Depends(get_fabric_iq)):
    """Get manager direct reports status and pass probabilities along with heatmap data."""
    emp = get_employee(manager_id)
    if not emp or not emp.get("is_manager"):
        raise HTTPException(status_code=404, detail="Manager not found or employee is not a manager")
    
    team_data = fabric_iq.get_team_readiness(manager_id)
    heatmap_data = fabric_iq.get_heatmap_data(manager_id)
    
    return TeamReadinessResponse(
        manager_id=manager_id,
        team=team_data,
        heatmap=heatmap_data
    )

@router.get("/{manager_id}/risks")
async def get_team_risks(manager_id: str):
    """List direct reports with struggling/at-risk profiles."""
    emp = get_employee(manager_id)
    if not emp or not emp.get("is_manager"):
        raise HTTPException(status_code=404, detail="Manager not found or employee is not a manager")
        
    reports = get_direct_reports(manager_id)
    risks = []
    
    for r in reports:
        emp_id = r["id"]
        risk_profile = r.get("risk_profile", "on_track")
        if risk_profile in ["at_risk", "struggling"]:
            history = get_employee_history(emp_id) or {"sessions": []}
            calendar = get_employee_calendar(emp_id)
            ph = PlanHealthEngine.calculate_from_data(history.get("sessions", []), calendar, recommended_weekly_hours=5.0)
            
            risks.append({
                "employee_id": emp_id,
                "name": r["name"],
                "risk_profile": risk_profile,
                "plan_health_score": ph.score,
                "plan_health_status": ph.status.value,
                "escalated": ph.score < 0.6
            })
            
    return {"risks": risks, "count": len(risks)}

@router.get("/{manager_id}/pending-approvals")
async def get_pending_approvals(manager_id: str, hitl_store = Depends(get_hitl_store)):
    """Fetch all pending readiness approvals for this manager's team."""
    reports = get_direct_reports(manager_id)
    report_ids = {r["id"] for r in reports}
    
    pending = []
    for emp_id, approval in hitl_store.items():
        if emp_id in report_ids and approval.get("status") == "pending_manager_approval":
            pending.append(approval)
            
    return {"approvals": pending, "count": len(pending)}

@router.post("/{manager_id}/approve/{employee_id}", response_model=HITLApprovalResponse)
async def approve_readiness(
    manager_id: str,
    employee_id: str,
    hitl = Depends(get_hitl_store)
):
    """Approve a team member's certification exam readiness."""
    if employee_id not in hitl:
        raise HTTPException(status_code=404, detail="No pending readiness decision found for this employee")
        
    approval = hitl[employee_id]
    approval["status"] = "approved"
    approval["approved_by"] = manager_id
    approval["approved_at"] = datetime.utcnow().isoformat()
    
    # Persist to JSONL file
    HITL_LOG.parent.mkdir(exist_ok=True)
    with open(HITL_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(approval) + "\n")
        
    return HITLApprovalResponse(
        employee_id=employee_id,
        certification_id=approval["certification_id"],
        decision="approved",
        approved_by=manager_id,
        timestamp=approval["approved_at"]
    )

@router.post("/{manager_id}/defer/{employee_id}", response_model=HITLApprovalResponse)
async def defer_readiness(
    manager_id: str,
    employee_id: str,
    hitl = Depends(get_hitl_store)
):
    """Defer a team member's certification exam readiness back to study."""
    if employee_id not in hitl:
        raise HTTPException(status_code=404, detail="No pending readiness decision found for this employee")
        
    approval = hitl[employee_id]
    approval["status"] = "deferred"
    approval["approved_by"] = manager_id
    approval["approved_at"] = datetime.utcnow().isoformat()
    
    # Persist to JSONL file
    HITL_LOG.parent.mkdir(exist_ok=True)
    with open(HITL_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(approval) + "\n")
        
    return HITLApprovalResponse(
        employee_id=employee_id,
        certification_id=approval["certification_id"],
        decision="deferred",
        approved_by=manager_id,
        timestamp=approval["approved_at"]
    )

@router.post("/{manager_id}/query", response_model=AgentAPIResponse)
async def query_manager_insights(
    manager_id: str,
    req: ManagerQueryRequest,
    orchestrator = Depends(get_orchestrator)
):
    """Submit natural language queries to the Manager Insights Agent."""
    emp = get_employee(manager_id)
    if not emp or not emp.get("is_manager"):
        raise HTTPException(status_code=404, detail="Manager not found or employee is not a manager")
        
    context = {"employee_id": manager_id}
    # Invoke Orchestrator
    resp = await asyncio.to_thread(
        orchestrator.orchestrate,
        user_query=req.query,
        context=context
    )
    
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
