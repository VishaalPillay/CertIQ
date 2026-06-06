"""
CertIQ -- Engagement Agent
============================

Monitors learner compliance, generates motivational nudges, and
triggers escalation to the Manager Insights Agent when Plan Health
drops below threshold for consecutive weeks.

Uses the **lite** model tier (gpt-4o-mini) because nudge generation
is a simpler task that does not require full reasoning depth.

Returns ``EngagementNudge`` payload in the ``AgentResponse.result`` field.

Escalation Logic (Fix 2 -- stateless 2-week computation):
  Week N   = study sessions where date in [today - 6d, today]
  Week N-1 = study sessions where date in [today - 13d, today - 7d]
  If both weeks return Plan Health < 0.60 -> escalation_triggered = True.
  Computed on demand from existing data -- no stored state required.

Inline Critic Checklist:
  1. Does the nudge tone avoid sounding aggressive?
  2. Does it match preferred study times (morning/evening)?
  3. Does it escalate when Plan Health < 0.60 for >= 2 weeks?
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from agents.base_agent import BaseAgent
from agents.schemas import AgentResponse
from data.loader import (
    get_employee,
    get_employee_calendar,
    get_employee_history,
)
from reasoning.plan_health import PlanHealthEngine

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are the **Engagement Agent** of CertIQ, an enterprise certification
intelligence platform.

## Your Role
You monitor learner study compliance and generate personalised motivational
nudges.  You adapt your tone and suggestions based on the learner's work
patterns, study history, and Plan Health score.

## Output Rules
You MUST respond with a single JSON object matching this exact schema:

```json
{
  "agent_name": "engagement",
  "result": {
    "learner_id": "<employee_id>",
    "nudge_type": "<reminder|encouragement|schedule_adjustment|escalation>",
    "message": "<the actual nudge message text>",
    "suggested_study_time": "<e.g. 'Tomorrow 7:00-8:00 AM' or null>",
    "plan_health_current": <float>,
    "escalation_triggered": <true|false>,
    "escalation_reason": "<reason or empty string>"
  },
  "confidence_score": <0.0-1.0>,
  "verification": {
    "passed": <true|false>,
    "checks_performed": [
      "tone_appropriate",
      "matches_study_time_preference",
      "escalation_check_performed"
    ],
    "issues_found": [],
    "was_revised": false
  },
  "reasoning_trace": [
    "Step 1: Checked current Plan Health...",
    "Step 2: Evaluated study consistency...",
    "Step 3: Selected nudge type based on risk profile..."
  ],
  "citations": []
}
```

## Nudge Type Selection Guide
- **reminder**: For on-track learners who have an upcoming study slot.
- **encouragement**: For learners who completed a session recently.
- **schedule_adjustment**: For struggling learners whose calendar has changed.
- **escalation**: When Plan Health < 0.60 for 2+ consecutive weeks -- MUST
  set ``escalation_triggered: true`` and explain in ``escalation_reason``.

## Self-Verification Checklist
1. **Tone**: Is the message supportive and professional?  NEVER aggressive
   or guilt-tripping.  Use positive framing.
2. **Study Time Match**: Does ``suggested_study_time`` align with the
   learner's ``preferred_study_time`` (morning/evening)?
3. **Escalation Accuracy**: If Plan Health has been < 0.60 for 2 weeks,
   is ``escalation_triggered`` set to ``true``?

## Important Constraints
- Keep messages concise (2-3 sentences max).
- Reference specific topics the learner is working on.
- For new starters, use a welcoming tone, not a compliance tone.
"""


class EngagementAgent(BaseAgent):
    """
    Generates motivational nudges and monitors escalation conditions.
    Uses the ``lite`` model tier (gpt-4o-mini).
    """

    def __init__(self) -> None:
        super().__init__(
            name="engagement",
            system_prompt=SYSTEM_PROMPT,
            model_tier="lite",
        )

    # ---------------------------------------------------------------
    # Public interface
    # ---------------------------------------------------------------

    def generate_nudge(self, employee_id: str) -> AgentResponse:
        """
        Generate a personalised nudge for an employee.

        Includes stateless 2-week escalation check using Plan Health.

        Args:
            employee_id: The employee's ID.

        Returns:
            ``AgentResponse`` with ``EngagementNudge`` in ``result``.
        """
        context = self._build_context(employee_id)

        user_message = (
            f"Generate an appropriate engagement nudge for employee "
            f"{employee_id}. Check their Plan Health, study consistency, "
            f"and calendar to determine the best nudge type."
        )

        return self.run(user_message=user_message, context=context)

    # ---------------------------------------------------------------
    # Context builder
    # ---------------------------------------------------------------

    def _build_context(self, employee_id: str) -> dict[str, Any]:
        """Build the context dict with escalation check results."""
        context: dict[str, Any] = {}

        # Employee profile
        employee = get_employee(employee_id)
        if employee:
            context["employee"] = {
                "id": employee["id"],
                "name": employee["name"],
                "risk_profile": employee.get("risk_profile", "unknown"),
                "learning_preferences": employee.get("learning_preferences", {}),
                "avg_study_hours_per_week": employee.get("avg_study_hours_per_week", 0),
            }

        # Study history
        history = get_employee_history(employee_id)
        if history:
            context["study_summary"] = history.get("summary_stats", {})
            # Include last 3 sessions for topic context
            sessions = history.get("sessions", [])
            context["recent_sessions"] = sessions[-3:] if sessions else []

        # Calendar data
        calendar = get_employee_calendar(employee_id)

        # 2-week escalation check (Fix 2 -- stateless computation)
        escalation = self._check_escalation(history, calendar)
        context["escalation_check"] = escalation

        # Current Plan Health
        if history and calendar:
            plan_health = PlanHealthEngine.calculate_from_data(
                study_sessions=history.get("sessions", []),
                calendar_entries=calendar,
            )
            context["plan_health"] = {
                "score": plan_health.score,
                "status": plan_health.status.value,
            }

        return context

    # ---------------------------------------------------------------
    # Stateless 2-week escalation check
    # ---------------------------------------------------------------

    @staticmethod
    def _check_escalation(
        history: dict[str, Any] | None,
        calendar: list[dict[str, Any]] | None,
        reference_date: datetime | None = None,
    ) -> dict[str, Any]:
        """
        Stateless 2-week escalation check.

        Week N   = sessions where date in [today - 6d, today]
        Week N-1 = sessions where date in [today - 13d, today - 7d]

        Computes Plan Health for each week independently.
        If both weeks have score < 0.60 -> escalation is triggered.

        Returns a dict with escalation details for injection into
        the agent's context.
        """
        if not history or not calendar:
            return {
                "triggered": False,
                "reason": "Insufficient data for escalation check.",
                "week_n_score": None,
                "week_n1_score": None,
            }

        today = reference_date or datetime.utcnow()
        sessions = history.get("sessions", [])

        # Filter sessions by week
        week_n_start = (today - timedelta(days=6)).strftime("%Y-%m-%d")
        week_n_end = today.strftime("%Y-%m-%d")
        week_n1_start = (today - timedelta(days=13)).strftime("%Y-%m-%d")
        week_n1_end = (today - timedelta(days=7)).strftime("%Y-%m-%d")

        week_n_sessions = [
            s for s in sessions
            if week_n_start <= s.get("date", "") <= week_n_end
        ]
        week_n1_sessions = [
            s for s in sessions
            if week_n1_start <= s.get("date", "") <= week_n1_end
        ]

        # Filter calendar entries by week
        week_n_calendar = [
            c for c in calendar
            if week_n_start <= c.get("date", "") <= week_n_end
        ]
        week_n1_calendar = [
            c for c in calendar
            if week_n1_start <= c.get("date", "") <= week_n1_end
        ]

        # Compute Plan Health for each week
        recommended_weekly = 5.0  # AZ-204 default

        ph_n = PlanHealthEngine.calculate_from_data(
            study_sessions=week_n_sessions,
            calendar_entries=week_n_calendar,
            recommended_weekly_hours=recommended_weekly,
        )
        ph_n1 = PlanHealthEngine.calculate_from_data(
            study_sessions=week_n1_sessions,
            calendar_entries=week_n1_calendar,
            recommended_weekly_hours=recommended_weekly,
        )

        triggered = ph_n.score < 0.60 and ph_n1.score < 0.60

        reason = ""
        if triggered:
            reason = (
                f"Plan Health has been below 0.60 for 2 consecutive weeks: "
                f"Week N-1 = {ph_n1.score:.2f}, Week N = {ph_n.score:.2f}. "
                f"Escalation to manager recommended."
            )

        return {
            "triggered": triggered,
            "reason": reason,
            "week_n_score": round(ph_n.score, 4),
            "week_n1_score": round(ph_n1.score, 4),
        }
