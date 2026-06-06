"""
CertIQ -- Learning Path Curator Agent
========================================

Builds personalised certification roadmaps by analysing:
  - Target certifications and their prerequisite graphs
  - Current skill levels and existing certifications
  - Module ordering based on exam weight and logical dependencies

Returns ``CertificationRoadmap`` payload in the ``AgentResponse.result`` field.

Inline Critic Checklist (embedded in system prompt):
  1. Are all target modules listed in correct logical order?
  2. Are module hour estimations realistic and sum to the cert total?
  3. Are all prerequisite requirements met?
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
    get_employee_history,
    load_certifications,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are the **Learning Path Curator** agent of CertIQ, an enterprise certification
intelligence platform.

## Your Role
You build personalised certification roadmaps for learners.  Given a learner's
profile (current certifications, target certifications, skill levels) and the
full certification catalogue, you produce a structured learning path.

## Output Rules
You MUST respond with a single JSON object matching this exact schema:

```json
{
  "agent_name": "learning_path_curator",
  "result": {
    "target_certification": "<cert name>",
    "certification_code": "<e.g. AZ-204>",
    "prerequisites": ["<list of prerequisite cert codes>"],
    "recommended_order": ["<module_id in recommended study order>"],
    "modules": [
      {
        "module_id": "<e.g. az204_m01>",
        "title": "<module title>",
        "estimated_hours": <float>,
        "skills": ["<skill 1>", "<skill 2>"],
        "bloom_level": "<remember|understand|apply|analyze|evaluate|create>"
      }
    ],
    "total_estimated_hours": <float>,
    "rationale": "<explanation of why this ordering was chosen>"
  },
  "confidence_score": <0.0-1.0>,
  "verification": {
    "passed": <true|false>,
    "checks_performed": [
      "prerequisite_ordering_valid",
      "hours_sum_matches_total",
      "all_modules_included"
    ],
    "issues_found": [],
    "was_revised": false
  },
  "reasoning_trace": [
    "Step 1: Identified target certification...",
    "Step 2: Checked prerequisites...",
    "Step 3: Ordered modules by dependency and exam weight..."
  ],
  "citations": [
    {
      "source": "<document name>",
      "section": "<section heading>",
      "relevance": <0.0-1.0>,
      "quote": ""
    }
  ]
}
```

## Self-Verification Checklist (run BEFORE returning)
1. **Prerequisite Order**: Are prerequisites listed before dependent certs?
2. **Hours Accuracy**: Do individual module hours sum to total_estimated_hours?
3. **Module Coverage**: Are ALL modules for the target cert included?
4. **Skill Alignment**: Do recommended modules address the learner's weakest skills first?

If ANY check fails, set ``verification.passed`` to ``false``, list the issue
in ``issues_found``, and lower your ``confidence_score`` accordingly.

## Important Constraints
- Never invent certifications or modules that do not exist in the provided data.
- If the learner already holds a prerequisite, note it but still include it in
  the prerequisites list for completeness.
- Prioritise modules with higher exam_weight_percentage earlier in the path.
"""


class LearningPathCuratorAgent(BaseAgent):
    """
    Builds certification roadmaps using prerequisite graphs and
    learner profiles.  Uses the ``primary`` model tier (gpt-4o).
    """

    def __init__(self) -> None:
        super().__init__(
            name="learning_path_curator",
            system_prompt=SYSTEM_PROMPT,
            model_tier="primary",
        )

    # ---------------------------------------------------------------
    # Public interface
    # ---------------------------------------------------------------

    def generate_roadmap(
        self,
        employee_id: str,
        target_cert_code: str = "AZ-204",
    ) -> AgentResponse:
        """
        Generate a certification roadmap for an employee.

        Args:
            employee_id: The employee's ID (e.g. ``emp_001``).
            target_cert_code: Target certification code (default ``AZ-204``).

        Returns:
            ``AgentResponse`` with a ``CertificationRoadmap`` in the
            ``result`` field.
        """
        # Build context from data loader
        context = self._build_context(employee_id, target_cert_code)

        user_message = (
            f"Create a personalised certification roadmap for employee "
            f"{employee_id} targeting {target_cert_code}. "
            f"Consider their current certifications, skill gaps, and "
            f"order modules by exam weight and logical dependencies."
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
                "role": employee["role"],
                "team": employee["team"],
                "current_certifications": employee.get("current_certifications", []),
                "target_certifications": employee.get("target_certifications", []),
                "skill_levels": employee.get("skill_levels", {}),
                "risk_profile": employee.get("risk_profile", "unknown"),
            }

        # Target certification details
        cert = get_certification_by_code(target_cert_code)
        if cert:
            context["target_certification"] = cert

        # Study history summary (for skill gap analysis)
        history = get_employee_history(employee_id)
        if history:
            context["study_summary"] = history.get("summary_stats", {})
            # Include which modules have been started
            started_modules = set()
            for session in history.get("sessions", []):
                started_modules.add(session.get("module_id", ""))
            context["modules_started"] = list(started_modules)

        # All certifications (for prerequisite graph)
        all_certs = load_certifications()
        context["certification_catalogue"] = [
            {
                "code": c.get("code", ""),
                "name": c.get("name", ""),
                "level": c.get("level", ""),
                "prerequisites": c.get("prerequisites", []),
            }
            for c in all_certs
        ]

        return context
