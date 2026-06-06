"""
CertIQ -- Study Plan Generator Agent
========================================

Converts certification roadmaps into calendar-aware weekly study
schedules.  Integrates:
  - Calendar data (Work IQ) to find available study slots
  - Spaced repetition (SM-2) for review scheduling
  - Plan Health engine for feasibility projection

Returns ``StudyPlan`` payload in the ``AgentResponse.result`` field.

Inline Critic Checklist (embedded in system prompt):
  1. Do study blocks overlap with calendar meetings?  (Fail if yes)
  2. Are study blocks in focus windows or high-quality slots?
  3. Is there spacing between new topics and review sessions?
"""

from __future__ import annotations

import json
import logging
from typing import Any

from agents.base_agent import BaseAgent
from agents.schemas import AgentResponse
from data.loader import (
    get_certification_by_code,
    get_employee,
    get_employee_calendar,
    get_employee_history,
)
from reasoning.plan_health import PlanHealthEngine
from reasoning.spaced_repetition import SpacedRepetitionEngine

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are the **Study Plan Generator** agent of CertIQ, an enterprise certification
intelligence platform.

## Your Role
You create calendar-aware weekly study plans for learners.  Given a learner's
profile, certification roadmap, calendar data, and study history, you produce
a structured multi-week study plan with spaced repetition review sessions.

## Output Rules
You MUST respond with a single JSON object matching this exact schema:

```json
{
  "agent_name": "study_plan_generator",
  "result": {
    "learner_id": "<employee_id>",
    "certification_code": "<e.g. AZ-204>",
    "weeks": [
      {
        "week_number": 1,
        "focus_modules": ["az204_m01", "az204_m02"],
        "study_blocks": [
          {
            "day": "Monday",
            "start_time": "07:00",
            "end_time": "08:00",
            "topic": "Azure App Service Web Apps",
            "module_id": "az204_m01",
            "activity_type": "new_material",
            "duration_minutes": 60
          }
        ],
        "review_sessions": [
          {
            "day": "Thursday",
            "start_time": "07:00",
            "end_time": "07:45",
            "topic": "Azure App Service Web Apps",
            "module_id": "az204_m01",
            "activity_type": "review",
            "duration_minutes": 45
          }
        ],
        "total_study_hours": 5.0,
        "plan_health_projection": 0.82
      }
    ],
    "total_weeks": 8,
    "target_completion_date": "2026-08-01",
    "spaced_repetition_schedule": {
      "az204_m01": ["2026-06-12", "2026-06-18", "2026-07-02"],
      "az204_m02": ["2026-06-14", "2026-06-20"]
    }
  },
  "confidence_score": <0.0-1.0>,
  "verification": {
    "passed": <true|false>,
    "checks_performed": [
      "no_meeting_overlap",
      "uses_focus_windows",
      "spaced_repetition_applied",
      "weekly_hours_feasible"
    ],
    "issues_found": [],
    "was_revised": false
  },
  "reasoning_trace": [
    "Step 1: Analysed calendar for available slots...",
    "Step 2: Applied SM-2 spaced repetition intervals...",
    "Step 3: Projected Plan Health for each week..."
  ],
  "citations": [],
  "plan_health_impact": <float or null>
}
```

## Self-Verification Checklist (run BEFORE returning)
1. **No Meeting Overlap**: Do ANY study blocks overlap with calendar meetings?
   If yes, FAIL and list the conflict.
2. **Focus Window Priority**: Are study blocks scheduled during focus windows
   or high-quality available slots when possible?
3. **Spaced Repetition**: Is there at least one review session per module
   within the SM-2 calculated interval?
4. **Weekly Hours Feasible**: Are total weekly study hours realistic given
   the learner's available time (check avg_study_hours_per_week)?

If ANY check fails, set ``verification.passed`` to ``false``, list issues,
and lower ``confidence_score``.

## Important Constraints
- Respect the learner's ``preferred_study_time`` (morning/evening).
- Match ``session_duration_preference_minutes`` when possible.
- New Starters (risk_profile: new_starter) should get a gentler ramp-up:
  fewer hours in week 1, gradually increasing.
- Schedule new material BEFORE review sessions for the same module.
"""


class StudyPlanGeneratorAgent(BaseAgent):
    """
    Creates calendar-aware study plans with spaced repetition.
    Uses the ``primary`` model tier (gpt-4o).
    """

    def __init__(self) -> None:
        super().__init__(
            name="study_plan_generator",
            system_prompt=SYSTEM_PROMPT,
            model_tier="primary",
        )

    # ---------------------------------------------------------------
    # Public interface
    # ---------------------------------------------------------------

    def generate_plan(
        self,
        employee_id: str,
        target_cert_code: str = "AZ-204",
    ) -> AgentResponse:
        """
        Generate a calendar-aware study plan for an employee.

        Args:
            employee_id: The employee's ID.
            target_cert_code: Target certification code.

        Returns:
            ``AgentResponse`` with ``StudyPlan`` in the ``result`` field.
        """
        context = self._build_context(employee_id, target_cert_code)

        user_message = (
            f"Create a calendar-aware weekly study plan for employee "
            f"{employee_id} targeting {target_cert_code}. "
            f"Use their calendar data to find available study slots, "
            f"apply spaced repetition for reviews, and project Plan Health "
            f"for each week."
        )

        return self.run(user_message=user_message, context=context)

    # ---------------------------------------------------------------
    # Context builder
    # ---------------------------------------------------------------

    def _build_context(
        self,
        employee_id: str,
        target_cert_code: str,
    ) -> dict[str, Any]:
        """Build the context dict injected into the system prompt."""
        context: dict[str, Any] = {}

        # Employee profile
        employee = get_employee(employee_id)
        if employee:
            context["employee"] = {
                "id": employee["id"],
                "name": employee["name"],
                "risk_profile": employee.get("risk_profile", "unknown"),
                "avg_study_hours_per_week": employee.get("avg_study_hours_per_week", 0),
                "weekly_meeting_hours": employee.get("weekly_meeting_hours", 0),
                "learning_preferences": employee.get("learning_preferences", {}),
            }

        # Calendar data (available slots, meetings, focus blocks)
        calendar = get_employee_calendar(employee_id)
        if calendar:
            # Summarise calendar to avoid context window bloat
            context["calendar_summary"] = {
                "total_days": len(calendar),
                "avg_meeting_hours": round(
                    sum(d.get("meeting_hours_total", 0) for d in calendar) / max(len(calendar), 1), 1
                ),
                "avg_focus_hours": round(
                    sum(d.get("deep_work_hours", 0) for d in calendar) / max(len(calendar), 1), 1
                ),
                "avg_fragmentation": round(
                    sum(d.get("fragmentation_score", 0) for d in calendar) / max(len(calendar), 1), 2
                ),
            }
            # Include first 5 days of detailed calendar for slot identification
            context["calendar_sample"] = calendar[:5]

        # Study history and spaced repetition data
        history = get_employee_history(employee_id)
        if history:
            context["study_summary"] = history.get("summary_stats", {})

            # Compute spaced repetition schedules for studied topics
            topic_scores = self._extract_topic_scores(history)
            if topic_scores:
                sr_schedules = SpacedRepetitionEngine.schedule_reviews(topic_scores)
                context["spaced_repetition"] = sr_schedules

        # Plan Health calculation
        if history and calendar:
            plan_health = PlanHealthEngine.calculate_from_data(
                study_sessions=history.get("sessions", []),
                calendar_entries=calendar,
            )
            context["current_plan_health"] = {
                "score": plan_health.score,
                "status": plan_health.status.value,
            }

        # Certification details
        cert = get_certification_by_code(target_cert_code)
        if cert:
            context["certification"] = {
                "code": cert.get("code", ""),
                "name": cert.get("name", ""),
                "total_estimated_hours": cert.get("total_estimated_hours", 40),
                "modules": cert.get("modules", []),
            }

        return context

    # ---------------------------------------------------------------
    # Helpers
    # ---------------------------------------------------------------

    @staticmethod
    def _extract_topic_scores(history: dict) -> list[dict]:
        """
        Extract per-module quiz scores from study history for
        spaced repetition scheduling.
        """
        module_scores: dict[str, list[float]] = {}
        for session in history.get("sessions", []):
            mid = session.get("module_id", "")
            score = session.get("quiz_score", 0)
            if mid and score:
                module_scores.setdefault(mid, []).append(score)

        return [
            {
                "module_id": mid,
                "quiz_score": scores[-1],  # latest score
                "repetitions": len(scores) - 1,
                "previous_interval": 7,  # default assumption
                "easiness_factor": 2.5,
            }
            for mid, scores in module_scores.items()
        ]
