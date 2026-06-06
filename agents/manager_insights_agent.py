"""
CertIQ -- Manager Insights Agent
====================================

Generates team readiness analytics, risk alerts, and actionable
recommendations for managers.  Computes:

  - Per-member Plan Health and readiness scores
  - Team-level aggregate metrics
  - Risk alerts for struggling/at-risk employees
  - Predicted completion dates and pass probabilities

Returns ``TeamInsights`` payload in the ``AgentResponse.result`` field.

Inline Critic Checklist:
  1. Are all calculations (averages, counts) mathematically correct?
  2. Are risk alerts limited to struggling/at-risk employees?
  3. Are recommendations actionable (e.g. meeting reduction)?
"""

from __future__ import annotations

import logging
from typing import Any

from agents.base_agent import BaseAgent
from agents.schemas import AgentResponse
from data.loader import (
    get_direct_reports,
    get_employee,
    get_employee_calendar,
    get_employee_history,
    get_managers,
    get_team_employees,
    load_certifications,
)
from reasoning.plan_health import PlanHealthEngine

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are the **Manager Insights Agent** of CertIQ, an enterprise certification
intelligence platform.

## Your Role
You provide team-level certification readiness analytics for managers.
Given a manager's team data (employee profiles, study histories, calendar
loads, Plan Health scores), you produce structured insights with risk
alerts and actionable recommendations.

## Output Rules
You MUST respond with a single JSON object matching this exact schema:

```json
{
  "agent_name": "manager_insights",
  "result": {
    "team_id": "<team name>",
    "team_name": "<team name>",
    "total_members": <int>,
    "members_at_risk": <int>,
    "members_on_track": <int>,
    "members_excelling": <int>,
    "overall_readiness": <0.0-1.0>,
    "member_readiness": [
      {
        "employee_id": "<id>",
        "employee_name": "<name>",
        "target_certification": "<cert code>",
        "plan_health": <float>,
        "plan_health_status": "<excelling|on_track|struggling|at_risk|unknown>",
        "completion_percentage": <0.0-1.0>,
        "predicted_pass_probability": <0.0-1.0>,
        "predicted_completion_date": "<YYYY-MM-DD>",
        "risk_factors": ["<factor 1>", "<factor 2>"],
        "weeks_at_risk": <int>
      }
    ],
    "risk_alerts": [
      "<alert text>"
    ],
    "recommendations": [
      "<actionable recommendation>"
    ]
  },
  "confidence_score": <0.0-1.0>,
  "verification": {
    "passed": <true|false>,
    "checks_performed": [
      "member_counts_match_total",
      "risk_alerts_only_for_at_risk",
      "recommendations_are_actionable",
      "averages_mathematically_correct"
    ],
    "issues_found": [],
    "was_revised": false
  },
  "reasoning_trace": [
    "Step 1: Retrieved team member profiles...",
    "Step 2: Computed Plan Health for each member...",
    "Step 3: Identified risk patterns...",
    "Step 4: Generated actionable recommendations..."
  ],
  "citations": []
}
```

## Self-Verification Checklist
1. **Counts**: Does ``members_at_risk + members_on_track + members_excelling``
   (plus other categories) equal ``total_members``?
2. **Risk Alerts**: Are alerts ONLY for employees with ``plan_health_status``
   of ``struggling`` or ``at_risk``?  Do NOT alert for on_track/excelling.
3. **Recommendations**: Is each recommendation specific and actionable?
   Good: "Reduce emp_003's weekly meetings from 28 to 20 hours."
   Bad: "Improve study habits."
4. **Pass Probability**: Is ``predicted_pass_probability`` based on actual
   quiz scores and completion percentage, not guessed?

## Important Constraints
- Only show data for the manager's direct reports.
- ``is_manager: true`` employees should be identified as managers.
- Sort ``member_readiness`` by Plan Health ascending (worst first).
"""


class ManagerInsightsAgent(BaseAgent):
    """
    Team readiness analytics and risk alerts for managers.
    Uses the ``primary`` model tier (gpt-4o).
    """

    def __init__(self) -> None:
        super().__init__(
            name="manager_insights",
            system_prompt=SYSTEM_PROMPT,
            model_tier="primary",
        )

    # ---------------------------------------------------------------
    # Public interface
    # ---------------------------------------------------------------

    def generate_insights(
        self,
        manager_id: str,
        query: str = "",
    ) -> AgentResponse:
        """
        Generate team insights for a manager.

        Args:
            manager_id: The manager's employee ID.
            query: Optional natural language query from the manager.

        Returns:
            ``AgentResponse`` with ``TeamInsights`` in ``result``.
        """
        context = self._build_context(manager_id)

        user_message = query or (
            f"Generate a comprehensive team readiness report for "
            f"manager {manager_id}. Include risk alerts, Plan Health "
            f"scores, and actionable recommendations for each team member."
        )

        return self.run(user_message=user_message, context=context)

    # ---------------------------------------------------------------
    # Context builder
    # ---------------------------------------------------------------

    def _build_context(self, manager_id: str) -> dict[str, Any]:
        """Build the context dict with team member data and Plan Health."""
        context: dict[str, Any] = {}

        # Manager profile
        manager = get_employee(manager_id)
        if not manager:
            context["error"] = f"Manager {manager_id} not found."
            return context

        context["manager"] = {
            "id": manager["id"],
            "name": manager["name"],
            "team": manager.get("team", ""),
            "is_manager": manager.get("is_manager", False),
        }

        # Direct reports
        reports = get_direct_reports(manager_id)
        if not reports:
            # Fallback: get team members
            reports = [
                e for e in get_team_employees(manager.get("team", ""))
                if e["id"] != manager_id
            ]

        # Build per-member readiness data
        member_data = []
        for emp in reports:
            emp_id = emp["id"]
            history = get_employee_history(emp_id)
            calendar = get_employee_calendar(emp_id)

            # Compute Plan Health
            plan_health = None
            if history and calendar:
                plan_health = PlanHealthEngine.calculate_from_data(
                    study_sessions=history.get("sessions", []),
                    calendar_entries=calendar,
                )

            # Compute completion percentage
            completion = self._compute_completion(emp, history)

            # Compute pass probability estimate
            pass_prob = self._estimate_pass_probability(history, completion)

            member_data.append({
                "employee_id": emp_id,
                "employee_name": emp.get("name", ""),
                "risk_profile": emp.get("risk_profile", "unknown"),
                "target_certifications": emp.get("target_certifications", []),
                "current_certifications": emp.get("current_certifications", []),
                "weekly_meeting_hours": emp.get("weekly_meeting_hours", 0),
                "avg_study_hours_per_week": emp.get("avg_study_hours_per_week", 0),
                "plan_health_score": plan_health.score if plan_health else 0.0,
                "plan_health_status": plan_health.status.value if plan_health else "unknown",
                "completion_percentage": round(completion, 2),
                "estimated_pass_probability": round(pass_prob, 2),
                "study_summary": history.get("summary_stats", {}) if history else {},
            })

        # Sort by Plan Health ascending (worst first)
        member_data.sort(key=lambda m: m.get("plan_health_score", 0))

        context["team_members"] = member_data
        context["team_summary"] = {
            "total_members": len(member_data),
            "at_risk": sum(1 for m in member_data if m["risk_profile"] in ("at_risk",)),
            "struggling": sum(1 for m in member_data if m["risk_profile"] in ("struggling",)),
            "on_track": sum(1 for m in member_data if m["risk_profile"] in ("on_track",)),
            "excelling": sum(1 for m in member_data if m["risk_profile"] in ("excelling",)),
            "new_starters": sum(1 for m in member_data if m["risk_profile"] in ("new_starter",)),
        }

        return context

    # ---------------------------------------------------------------
    # Helpers
    # ---------------------------------------------------------------

    @staticmethod
    def _compute_completion(
        employee: dict[str, Any],
        history: dict[str, Any] | None,
    ) -> float:
        """
        Estimate completion percentage based on modules completed
        vs total modules in the target certification.
        """
        if not history:
            return 0.0

        summary = history.get("summary_stats", {})
        modules_completed = summary.get("modules_completed", 0)

        # Get total modules for target cert
        target_certs = employee.get("target_certifications", [])
        if not target_certs:
            return 0.0

        cert = None
        for cert_code in target_certs:
            from data.loader import get_certification_by_code
            cert = get_certification_by_code(cert_code)
            if cert:
                break

        if not cert:
            return 0.0

        total_modules = len(cert.get("modules", []))
        if total_modules == 0:
            return 0.0

        return min(modules_completed / total_modules, 1.0)

    @staticmethod
    def _estimate_pass_probability(
        history: dict[str, Any] | None,
        completion: float,
    ) -> float:
        """
        Simple pass probability estimation based on average quiz
        scores and completion percentage.

        Formula: 0.4 * avg_quiz_score + 0.6 * completion_percentage
        """
        if not history:
            return 0.0

        summary = history.get("summary_stats", {})
        avg_score = summary.get("avg_quiz_score", 0.0)

        return 0.4 * avg_score + 0.6 * completion
