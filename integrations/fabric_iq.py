# integrations/fabric_iq.py
from functools import lru_cache
from typing import Any

from data.loader import (
    get_employee,
    get_employee_history,
    get_employee_calendar,
    get_certification,
    get_certification_by_code,
    get_direct_reports,
)
from reasoning.plan_health import PlanHealthEngine
from integrations.work_iq import get_work_iq, get_iso_week

class FabricIQ:
    """
    Semantic analytics layer. Computes ontology-derived insights about
    workforce certification readiness, skill gaps, and team health.
    All computations are deterministic from synthetic data — no LLM calls.
    """

    def get_skill_gaps(self, employee_id: str) -> dict[str, Any]:
        """
        Compares employee.skill_levels against required skills for their
        target certification. Returns gaps and overall readiness percentage.
        """
        emp = get_employee(employee_id)
        if not emp:
            return {
                "employee_id": employee_id,
                "target_certification": "",
                "gaps": [],
                "overall_readiness_pct": 0.0
            }
            
        target_certs = emp.get("target_certifications", [])
        target_cert = target_certs[0] if target_certs else "AZ-204"
        
        emp_skills = emp.get("skill_levels", {})
        gaps = []
        total_required = 0.0
        total_current = 0.0
        
        # Default required level is 0.7 for associate certs
        required_level = 0.7
        
        for skill, current_val in emp_skills.items():
            gap_val = max(0.0, required_level - current_val)
            gaps.append({
                "skill": skill.replace("_", " ").title(),
                "current_level": round(current_val, 2),
                "required_level": required_level,
                "gap": round(gap_val, 2)
            })
            total_required += required_level
            total_current += min(current_val, required_level)
            
        readiness_pct = (total_current / total_required * 100.0) if total_required > 0 else 100.0
        
        return {
            "employee_id": employee_id,
            "target_certification": target_cert,
            "gaps": gaps,
            "overall_readiness_pct": round(readiness_pct, 2)
        }

    def predict_pass_probability(self, employee_id: str) -> dict[str, Any]:
        """
        Estimates exam pass likelihood using:
          - avg practice score from study_history
          - hours studied vs recommended hours
          - Plan Health score
        Returns: {"probability": float, "confidence": str, "key_factors": list[str]}
        """
        emp = get_employee(employee_id)
        if not emp:
            return {
                "probability": 0.0,
                "confidence": "unknown",
                "key_factors": ["No profile found"]
            }
            
        history = get_employee_history(employee_id) or {"sessions": []}
        sessions = history.get("sessions", [])
        
        # 1. Practice score
        quiz_scores = [s.get("quiz_score", 0.0) for s in sessions if "quiz_score" in s]
        avg_practice_score = sum(quiz_scores) / len(quiz_scores) if quiz_scores else 0.5
        
        # 2. Hours studied vs recommended
        completed_hours = sum(s.get("duration_minutes", 0) / 60.0 for s in sessions)
        target_cert_code = emp.get("target_certifications", ["AZ-204"])[0]
        cert = get_certification_by_code(target_cert_code)
        recommended_hours = cert.get("total_estimated_hours", 40.0) if cert else 40.0
        study_hours_ratio = min(completed_hours / recommended_hours, 1.0) if recommended_hours > 0 else 1.0
        
        # 3. Plan Health over recent rolling window
        calendar = get_employee_calendar(employee_id)
        recent_sessions = sessions[-14:] if len(sessions) >= 14 else sessions
        recent_calendar = calendar[-14:] if len(calendar) >= 14 else calendar
        ph = PlanHealthEngine.calculate_from_data(recent_sessions, recent_calendar, recommended_weekly_hours=5.0)
        plan_health_score = min(ph.score, 1.0)
        
        # Pass probability formula: 50% quiz score, 30% curriculum coverage, 20% plan health consistency
        prob = (avg_practice_score * 0.5) + (study_hours_ratio * 0.3) + (plan_health_score * 0.2)
        prob = round(max(0.0, min(1.0, prob)), 2)
        
        # Determine confidence level based on history volume
        if len(sessions) > 10:
            confidence = "high"
        elif len(sessions) > 5:
            confidence = "medium"
        else:
            confidence = "low"
            
        # Build key factors
        factors = []
        if avg_practice_score >= 0.75:
            factors.append(f"Strong quiz performance (avg: {avg_practice_score*100:.0f}%)")
        else:
            factors.append(f"Quiz scores need improvement (avg: {avg_practice_score*100:.0f}%)")
            
        if study_hours_ratio >= 0.8:
            factors.append(f"Curriculum target completed ({completed_hours:.1f}/{recommended_hours:.0f} hrs)")
        else:
            factors.append(f"Behind on total study hours ({completed_hours:.1f}/{recommended_hours:.0f} hrs)")
            
        if plan_health_score >= 0.7:
            factors.append("Consistent study habit (Plan Health is on track)")
        else:
            factors.append("Inconsistent study habits (Plan Health is at risk)")
            
        return {
            "probability": prob,
            "confidence": confidence,
            "key_factors": factors
        }

    def get_team_readiness(self, manager_id: str) -> dict[str, Any]:
        """
        Aggregates readiness metrics for all employees reporting to manager_id.
        """
        reports = get_direct_reports(manager_id)
        members = []
        at_risk_count = 0
        on_track_count = 0
        ready_for_exam_count = 0
        total_ph = 0.0
        total_pass = 0.0
        
        for r in reports:
            emp_id = r["id"]
            pass_pred = self.predict_pass_probability(emp_id)
            pass_prob = pass_pred["probability"]
            
            history = get_employee_history(emp_id) or {"sessions": []}
            calendar = get_employee_calendar(emp_id)
            ph = PlanHealthEngine.calculate_from_data(history.get("sessions", []), calendar, recommended_weekly_hours=5.0)
            
            is_ready = pass_prob >= 0.75
            if is_ready:
                ready_for_exam_count += 1
                
            if ph.status.value in ["at_risk", "struggling"]:
                at_risk_count += 1
            else:
                on_track_count += 1
                
            members.append({
                "employee_id": emp_id,
                "name": r["name"],
                "risk_profile": r.get("risk_profile", "unknown"),
                "plan_health_score": ph.score,
                "plan_health_status": ph.status.value,
                "pass_probability": pass_prob,
                "target_certification": r.get("target_certifications", ["AZ-204"])[0],
                "is_ready_for_exam": is_ready
            })
            
            total_ph += ph.score
            total_pass += pass_prob
            
        num_members = len(reports)
        avg_ph = round(total_ph / num_members, 2) if num_members > 0 else 0.0
        avg_pass = round(total_pass / num_members, 2) if num_members > 0 else 0.0
        
        return {
            "team_size": num_members,
            "members": members,
            "summary": {
                "at_risk_count": at_risk_count,
                "on_track_count": on_track_count,
                "ready_for_exam_count": ready_for_exam_count,
                "avg_plan_health": avg_ph,
                "avg_pass_probability": avg_pass
            }
        }

    def get_certification_ontology(self, cert_id: str) -> dict[str, Any]:
        """
        Returns the full semantic model for a certification.
        """
        cert = get_certification(cert_id)
        if not cert:
            return {}
        return {
            "id": cert["id"],
            "code": cert["code"],
            "name": cert["name"],
            "level": cert["level"],
            "role_alignment": cert.get("role_alignment", []),
            "prerequisites": cert.get("prerequisites", []),
            "prerequisite_type": cert.get("prerequisite_type", "none"),
            "total_estimated_hours": cert.get("total_estimated_hours", 0.0),
            "pass_score": cert.get("pass_score", 700),
            "skills_measured": cert.get("skills_measured", []),
            "modules_count": len(cert.get("modules", []))
        }

    def get_heatmap_data(self, manager_id: str) -> list[dict[str, Any]]:
        """
        Returns data for the Manager Dashboard heatmap.
        Each row = one team member. Columns = Plan Health per week (last 4 weeks).
        """
        reports = get_direct_reports(manager_id)
        heatmap = []
        
        for r in reports:
            emp_id = r["id"]
            history = get_employee_history(emp_id) or {"sessions": []}
            calendar = get_employee_calendar(emp_id)
            
            # Group by ISO week
            weeks_map = {}
            for entry in calendar:
                date_str = entry.get("date", "")
                week_num = get_iso_week(date_str)
                if week_num not in weeks_map:
                    weeks_map[week_num] = {"calendar": [], "sessions": []}
                weeks_map[week_num]["calendar"].append(entry)
                
            for session in history.get("sessions", []):
                date_str = session.get("date", "")
                week_num = get_iso_week(date_str)
                if week_num in weeks_map:
                    weeks_map[week_num]["sessions"].append(session)
                    
            sorted_weeks = sorted(weeks_map.keys())
            
            weeks_data = []
            if sorted_weeks:
                latest_week = sorted_weeks[-1]
                target_weeks = [latest_week - 3, latest_week - 2, latest_week - 1, latest_week]
            else:
                target_weeks = [21, 22, 23, 24]
                
            for w in target_weeks:
                if w in weeks_map:
                    w_sessions = weeks_map[w]["sessions"]
                    w_calendar = weeks_map[w]["calendar"]
                    ph = PlanHealthEngine.calculate_from_data(w_sessions, w_calendar, recommended_weekly_hours=5.0)
                    score = ph.score
                    status = ph.status.value
                else:
                    # Backfill based on risk profile
                    risk = r.get("risk_profile", "on_track")
                    if risk == "at_risk":
                        score = 0.4 + (w % 10) * 0.02
                    elif risk == "struggling":
                        score = 0.58 + (w % 10) * 0.01
                    elif risk == "excelling":
                        score = 0.92 + (w % 10) * 0.01
                    else:
                        score = 0.75 + (w % 10) * 0.02
                    
                    ph_status = PlanHealthEngine.classify_status(score)
                    status = ph_status.value
                    
                weeks_data.append({
                    "week": f"Week {w}",
                    "score": round(score, 2),
                    "status": status
                })
                
            heatmap.append({
                "employee_id": emp_id,
                "name": r["name"],
                "weeks": weeks_data
            })
            
        return heatmap

@lru_cache(maxsize=1)
def get_fabric_iq() -> FabricIQ:
    return FabricIQ()
