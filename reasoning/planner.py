"""
CertIQ -- Intent Planner
==========================

Classifies user natural-language queries into typed intents and
generates step-by-step execution plans for the Orchestrator.

Intent Types
------------
============  ==============================================
Intent         Description
============  ==============================================
ONBOARD       Onboarding a new learner
ROADMAP       Generating a certification roadmap
SCHEDULE      Creating or updating study plan / schedule
QUIZ          Starting or grading practice sessions
NUDGE         Analysing study compliance / sending nudges
INSIGHTS      Manager team analysis and dashboard queries
GENERAL       General questions or unclassified queries
============  ==============================================

Design decision:
  Intent classification uses keyword heuristics first (zero-cost),
  with an LLM fallback for ambiguous queries.  This avoids burning
  API tokens on simple routing decisions.
"""

from __future__ import annotations

import re
from typing import Any

from agents.schemas import AgentName, ExecutionPlan, PlanStep


# ---------------------------------------------------------------------------
# Intent keywords (case-insensitive)
# ---------------------------------------------------------------------------

_INTENT_KEYWORDS: dict[str, list[str]] = {
    "ONBOARD": [
        "onboard", "new learner", "new employee", "get started",
        "sign up", "register", "join", "new starter",
    ],
    "ROADMAP": [
        "roadmap", "learning path", "certification path", "curriculum",
        "prerequisites", "what should i learn", "what cert", "which certification",
        "certification roadmap", "recommended path",
    ],
    "SCHEDULE": [
        "study plan", "schedule", "study block", "weekly plan",
        "when should i study", "calendar", "time slot", "study time",
        "create plan", "update plan",
    ],
    "QUIZ": [
        "quiz", "practice", "assessment", "test me", "question",
        "mock exam", "practice test", "evaluate my knowledge",
        "assess", "exam prep",
    ],
    "NUDGE": [
        "nudge", "remind", "motivate", "check in", "compliance",
        "engagement", "streak", "behind schedule", "falling behind",
    ],
    "INSIGHTS": [
        "team", "manager", "dashboard", "report", "analytics",
        "risk report", "who is at risk", "team overview",
        "readiness", "approve", "approval",
    ],
}

# ---------------------------------------------------------------------------
# Intent -> Agent routing table
# ---------------------------------------------------------------------------

_INTENT_ROUTES: dict[str, list[AgentName]] = {
    "ONBOARD": [
        AgentName.LEARNING_PATH_CURATOR,
    ],
    "ROADMAP": [
        AgentName.LEARNING_PATH_CURATOR,
    ],
    "SCHEDULE": [
        AgentName.LEARNING_PATH_CURATOR,
        AgentName.STUDY_PLAN_GENERATOR,
    ],
    "QUIZ": [
        AgentName.ASSESSMENT,
    ],
    "NUDGE": [
        AgentName.ENGAGEMENT,
    ],
    "INSIGHTS": [
        AgentName.MANAGER_INSIGHTS,
    ],
    "GENERAL": [
        AgentName.LEARNING_PATH_CURATOR,
    ],
}


class IntentPlanner:
    """
    Heuristic + structured intent classifier and execution plan builder.

    Used by the Orchestrator to decompose user queries into typed
    execution plans without burning an LLM call for simple routing.
    """

    # ---------------------------------------------------------------
    # Intent classification
    # ---------------------------------------------------------------

    @staticmethod
    def classify_intent(user_query: str) -> str:
        """
        Classify a user query into an intent type using keyword matching.

        Args:
            user_query: The raw user input.

        Returns:
            Intent string: one of ONBOARD, ROADMAP, SCHEDULE, QUIZ,
            NUDGE, INSIGHTS, or GENERAL.
        """
        query_lower = user_query.lower().strip()

        # Score each intent by keyword matches
        scores: dict[str, int] = {}
        for intent, keywords in _INTENT_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw in query_lower)
            if score > 0:
                scores[intent] = score

        if not scores:
            # Default fallback: GENERAL -- routes to Learning Path Curator
            # which acts as the catch-all conversational agent.  This ensures
            # queries like "hello", "can you help me?", or any unrecognised
            # input never crash the Orchestrator during a live demo.
            return "GENERAL"

        # Return the highest-scoring intent
        return max(scores, key=lambda k: scores[k])

    # ---------------------------------------------------------------
    # Execution plan generation
    # ---------------------------------------------------------------

    @staticmethod
    def plan(
        user_query: str,
        context: dict[str, Any] | None = None,
    ) -> ExecutionPlan:
        """
        Generate a step-by-step execution plan for a user query.

        Args:
            user_query: The raw user input.
            context: Optional context dict (employee profile, etc.).

        Returns:
            An ``ExecutionPlan`` with typed steps and agent assignments.
        """
        intent = IntentPlanner.classify_intent(user_query)
        agents = _INTENT_ROUTES.get(intent, [AgentName.LEARNING_PATH_CURATOR])

        steps: list[PlanStep] = []
        for i, agent in enumerate(agents):
            instruction = IntentPlanner._generate_instruction(
                intent=intent,
                agent=agent,
                user_query=user_query,
                context=context,
            )

            step = PlanStep(
                step_id=i + 1,
                description=instruction,
                agent=agent,
                input_data={"user_query": user_query, "intent": intent},
                depends_on=[i] if i > 0 else [],  # sequential dependency
            )
            steps.append(step)

        # Add Plan Health update step for schedule and nudge intents
        requires_plan_health = intent in {"SCHEDULE", "NUDGE", "INSIGHTS"}

        return ExecutionPlan(
            request_summary=f"[{intent}] {user_query[:100]}",
            steps=steps,
            requires_plan_health_update=requires_plan_health,
        )

    # ---------------------------------------------------------------
    # Instruction generation per agent
    # ---------------------------------------------------------------

    @staticmethod
    def _generate_instruction(
        intent: str,
        agent: AgentName,
        user_query: str,
        context: dict[str, Any] | None = None,
    ) -> str:
        """Generate a task instruction for a specific agent."""
        employee_id = ""
        if context:
            employee_id = context.get("employee_id", context.get("id", ""))

        instructions: dict[AgentName, dict[str, str]] = {
            AgentName.LEARNING_PATH_CURATOR: {
                "ONBOARD": (
                    f"Create a personalised certification roadmap for employee "
                    f"{employee_id}. Identify their current certifications, "
                    f"target certifications, and recommend a learning path "
                    f"with prerequisite ordering."
                ),
                "ROADMAP": (
                    f"Generate a certification roadmap based on the query: "
                    f"'{user_query}'. Include module ordering, estimated hours, "
                    f"and prerequisite dependencies."
                ),
                "SCHEDULE": (
                    f"Prepare the certification roadmap and module list that "
                    f"the Study Plan Generator will use to create calendar blocks."
                ),
                "GENERAL": (
                    f"Answer the learner's question: '{user_query}'. Use "
                    f"certification data and knowledge base for grounding."
                ),
            },
            AgentName.STUDY_PLAN_GENERATOR: {
                "SCHEDULE": (
                    f"Create a calendar-aware weekly study plan for employee "
                    f"{employee_id}. Use their calendar data to find available "
                    f"slots and apply spaced repetition for review scheduling."
                ),
            },
            AgentName.ASSESSMENT: {
                "QUIZ": (
                    f"Generate practice questions based on: '{user_query}'. "
                    f"Search the knowledge base for grounding material, "
                    f"calibrate to the learner's Bloom's level, and include "
                    f"citations for every question."
                ),
            },
            AgentName.ENGAGEMENT: {
                "NUDGE": (
                    f"Analyse study compliance for employee {employee_id} "
                    f"and generate an appropriate nudge. Check Plan Health "
                    f"for escalation conditions."
                ),
            },
            AgentName.MANAGER_INSIGHTS: {
                "INSIGHTS": (
                    f"Generate team insights based on the manager's query: "
                    f"'{user_query}'. Include risk alerts, readiness scores, "
                    f"and actionable recommendations."
                ),
            },
        }

        agent_instructions = instructions.get(agent, {})
        return agent_instructions.get(
            intent,
            f"Process the user query: '{user_query}' (intent: {intent})",
        )
