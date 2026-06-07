# api/routes/assessment.py
import asyncio
from datetime import datetime
import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from api.dependencies import get_orchestrator, get_assessment_sessions, get_hitl_store, get_fabric_iq
from api.models.requests import AssessmentStartRequest, AssessmentAnswerRequest
from data.loader import get_employee, get_employee_history, get_certification_by_code

router = APIRouter(prefix="/assessment", tags=["Assessment"])

HITL_LOG = Path("logs/hitl_approvals.jsonl")

@router.post("/{employee_id}/start")
async def start_assessment(
    employee_id: str,
    req: AssessmentStartRequest,
    orchestrator = Depends(get_orchestrator),
    sessions = Depends(get_assessment_sessions)
):
    """Start a practice assessment session, calibrating Bloom's taxonomy and returning the first question."""
    emp = get_employee(employee_id)
    if not emp:
        raise HTTPException(status_code=404, detail=f"Employee {employee_id} not found")
        
    assessment_agent = orchestrator._get_agent("assessment")
    
    # Generate all questions via LLM
    resp = await asyncio.to_thread(
        assessment_agent.generate_questions,
        employee_id=employee_id,
        cert_code=req.certification_id,
        num_questions=req.num_questions
    )
    
    if not resp.verification.passed:
        # Fallback or log if verification failed but proceed with questions generated
        pass
        
    session_data = resp.result
    if not session_data or "questions" not in session_data or not session_data["questions"]:
        raise HTTPException(status_code=500, detail="Failed to generate assessment questions")
        
    # Inject session state trackers
    session_data["current_question_index"] = 0
    session_data["answers"] = []
    session_data["start_time"] = datetime.utcnow().isoformat()
    session_data["completed"] = False
    
    sessions[employee_id] = session_data
    
    # Mask answer/explanation from the first question served
    first_question = dict(session_data["questions"][0])
    first_question.pop("correct_answer", None)
    first_question.pop("explanation", None)
    
    return {
        "session_id": session_data["session_id"],
        "learner_id": employee_id,
        "certification_code": session_data["certification_code"],
        "question": first_question,
        "total_questions": len(session_data["questions"]),
        "current_question_index": 0,
        "current_bloom_level": session_data["current_bloom_level"],
        "completed": False
    }

@router.post("/{employee_id}/answer")
async def submit_answer(
    employee_id: str,
    req: AssessmentAnswerRequest,
    sessions = Depends(get_assessment_sessions)
):
    """Submit an answer to the current question, recording score and moving to the next question."""
    if employee_id not in sessions:
        raise HTTPException(status_code=404, detail="No active assessment session found")
        
    session = sessions[employee_id]
    if session.get("completed", False):
        raise HTTPException(status_code=400, detail="Session is already completed")
        
    cur_idx = session["current_question_index"]
    questions = session["questions"]
    
    if cur_idx >= len(questions):
        raise HTTPException(status_code=400, detail="No more questions in session")
        
    question = questions[cur_idx]
    
    # Check answer option index (0-3) maps to choice letters (A, B, C, D)
    options_letters = ["A", "B", "C", "D"]
    selected_letter = options_letters[req.selected_option]
    correct_letter = question.get("correct_answer", "A")
    is_correct = selected_letter == correct_letter
    
    # Record current answer
    session["answers"].append({
        "question_id": req.question_id,
        "selected_option": req.selected_option,
        "selected_letter": selected_letter,
        "correct_letter": correct_letter,
        "is_correct": is_correct,
        "explanation": question.get("explanation", ""),
        "citations": question.get("citations", [])
    })
    
    # Progress index
    session["current_question_index"] += 1
    next_idx = session["current_question_index"]
    
    result_data = {
        "is_correct": is_correct,
        "correct_answer": correct_letter,
        "explanation": question.get("explanation", ""),
        "citations": question.get("citations", []),
        "completed": False
    }
    
    # End of assessment check
    if next_idx >= len(questions):
        session["completed"] = True
        correct_count = sum(1 for a in session["answers"] if a["is_correct"])
        score = correct_count / len(questions)
        session["score"] = score
        
        result_data["completed"] = True
        result_data["score"] = score
        result_data["total_questions"] = len(questions)
        result_data["correct_count"] = correct_count
        
        # Append completed session to in-memory history cache
        history = get_employee_history(employee_id)
        if history:
            history["sessions"].append({
                "date": datetime.utcnow().strftime("%Y-%m-%d"),
                "module_id": question.get("module_id", ""),
                "topic": question.get("topic", "Assessment Quiz"),
                "duration_minutes": 15,
                "activity_type": "quiz",
                "quiz_score": score,
                "retention_rate": 0.8
            })
    else:
        # Fetch next question and mask answer fields
        next_question = dict(questions[next_idx])
        next_question.pop("correct_answer", None)
        next_question.pop("explanation", None)
        
        result_data["next_question"] = next_question
        result_data["current_question_index"] = next_idx
        result_data["total_questions"] = len(questions)
        
    return result_data

@router.get("/{employee_id}/results")
async def get_assessment_results(employee_id: str, sessions = Depends(get_assessment_sessions)):
    """Fetch completed results for the active/latest assessment session."""
    if employee_id not in sessions:
        raise HTTPException(status_code=404, detail="No active or completed session found")
        
    session = sessions[employee_id]
    if not session.get("completed", False):
        return {
            "completed": False,
            "current_question_index": session["current_question_index"],
            "total_questions": len(session["questions"])
        }
        
    correct_count = sum(1 for a in session["answers"] if a["is_correct"])
    
    return {
        "completed": True,
        "session_id": session["session_id"],
        "certification_code": session["certification_code"],
        "score": session["score"],
        "correct_count": correct_count,
        "total_questions": len(session["questions"]),
        "answers": session["answers"]
    }

@router.get("/{employee_id}/readiness")
async def check_exam_readiness(
    employee_id: str,
    fabric_iq = Depends(get_fabric_iq),
    hitl = Depends(get_hitl_store)
):
    """Evaluate pass probability and automatically queue for manager HITL approval if ready."""
    emp = get_employee(employee_id)
    if not emp:
        raise HTTPException(status_code=404, detail=f"Employee {employee_id} not found")
        
    target_certs = emp.get("target_certifications", [])
    cert_code = target_certs[0] if target_certs else "AZ-204"
    cert = get_certification_by_code(cert_code)
    cert_id = cert["id"] if cert else "cert_az204"
    
    pass_pred = fabric_iq.predict_pass_probability(employee_id)
    pass_prob = pass_pred["probability"]
    
    is_ready = pass_prob >= 0.75
    status = "not_ready"
    
    if is_ready:
        status = "pending_manager_approval"
        hitl[employee_id] = {
            "employee_id": employee_id,
            "employee_name": emp["name"],
            "certification_id": cert_id,
            "certification_code": cert_code,
            "status": "pending_manager_approval",
            "readiness_score": pass_prob,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        # Persist HITL approval entry
        HITL_LOG.parent.mkdir(exist_ok=True)
        with open(HITL_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(hitl[employee_id]) + "\n")
            
    return {
        "employee_id": employee_id,
        "certification_code": cert_code,
        "pass_probability": pass_prob,
        "is_ready_for_exam": is_ready,
        "status": status,
        "key_factors": pass_pred["key_factors"]
    }
