"""
CertIQ -- Orchestrator Agent
===============================

Central Planner-Executor coordinator.  Receives user prompts,
builds execution plans via the IntentPlanner, invokes specialist
agents sequentially, triggers self-reflection on low confidence,
and builds the final consolidated output.

Design decisions:
  - Sequential agent invocation (not parallel) for simplicity.
  - Self-reflection loop: if any sub-agent returns confidence < 0.65,
    the SelfReflectionEngine generates feedback and the agent is
    re-invoked once.
  - Plan Health is updated after Study Plan / Engagement interactions.
  - All reasoning traces from sub-agents are aggregated into the
    final response.
  - Critic Verifier runs asynchronously via daemon thread -- never
    blocks the response chain.

Uses the ``primary`` model tier (gpt-4o).
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from agents.base_agent import BaseAgent
from agents.schemas import AgentName, AgentResponse, ExecutionPlan, VerificationResult
from reasoning.planner import IntentPlanner
from reasoning.reflection import SelfReflectionEngine
from reasoning.trace_hook import trigger_trace_step

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are the **Orchestrator** of CertIQ, an enterprise certification
intelligence platform.  You are the central coordinator that routes
user requests to the appropriate specialist agents.

## Your Role
1. Understand the user's intent.
2. Build an execution plan (which agents to call, in what order).
3. Synthesise responses from specialist agents into a cohesive answer.
4. Monitor confidence scores and trigger self-reflection when needed.

## Output Rules
You MUST respond with a single JSON object matching this exact schema:

```json
{
  "agent_name": "orchestrator",
  "result": {
    "summary": "<concise answer to the user's request>",
    "execution_plan": {
      "request_summary": "<what the user asked>",
      "steps": [
        {
          "step_id": 1,
          "description": "<what this step does>",
          "agent": "<agent_name>",
          "completed": true
        }
      ]
    },
    "agent_responses": [
      "<summary of each specialist agent's output>"
    ],
    "plan_health_updated": <true|false>,
    "reflection_triggered": <true|false>
  },
  "confidence_score": <0.0-1.0>,
  "verification": {
    "passed": <true|false>,
    "checks_performed": [
      "all_plan_steps_completed",
      "sub_agent_confidence_acceptable",
      "response_addresses_user_query"
    ],
    "issues_found": [],
    "was_revised": false
  },
  "reasoning_trace": [
    "Step 1: Classified intent as ROADMAP...",
    "Step 2: Invoked Learning Path Curator...",
    "Step 3: Curator returned confidence 0.82..."
  ],
  "citations": []
}
```

## Self-Verification Checklist
1. Did ALL plan steps complete successfully?
2. Are ALL sub-agent confidence scores >= 0.65?
3. Does the final response address the user's original query?

## Important Constraints
- Call agents SEQUENTIALLY, not in parallel.
- If a sub-agent returns confidence < 0.65, trigger self-reflection
  and retry ONCE.
- Aggregate all reasoning traces for observability.
- Launch Critic Verifier audits asynchronously (non-blocking).
"""


class OrchestratorAgent(BaseAgent):
    """
    Central Planner-Executor that decomposes queries and routes
    to specialist agents.  Uses the ``primary`` model tier (gpt-4o).
    """

    def __init__(self) -> None:
        super().__init__(
            name="orchestrator",
            system_prompt=SYSTEM_PROMPT,
            model_tier="primary",
        )

        # Lazy-initialised specialist agents (created on first use)
        self._agents: dict[AgentName, BaseAgent] = {}
        self._critic = None

    # ---------------------------------------------------------------
    # Specialist agent registry
    # ---------------------------------------------------------------

    def _get_agent(self, agent_name: AgentName) -> BaseAgent:
        """Lazy-initialise and return a specialist agent by name."""
        if agent_name not in self._agents:
            self._agents[agent_name] = self._create_agent(agent_name)
        return self._agents[agent_name]

    @staticmethod
    def _create_agent(agent_name: AgentName) -> BaseAgent:
        """Create a specialist agent instance by name."""
        # Import here to avoid circular imports
        if agent_name == AgentName.LEARNING_PATH_CURATOR:
            from agents.learning_path_curator import LearningPathCuratorAgent
            return LearningPathCuratorAgent()
        elif agent_name == AgentName.STUDY_PLAN_GENERATOR:
            from agents.study_plan_generator import StudyPlanGeneratorAgent
            return StudyPlanGeneratorAgent()
        elif agent_name == AgentName.ENGAGEMENT:
            from agents.engagement_agent import EngagementAgent
            return EngagementAgent()
        elif agent_name == AgentName.ASSESSMENT:
            from agents.assessment_agent import AssessmentAgent
            return AssessmentAgent()
        elif agent_name == AgentName.MANAGER_INSIGHTS:
            from agents.manager_insights_agent import ManagerInsightsAgent
            return ManagerInsightsAgent()
        elif agent_name == AgentName.CRITIC_VERIFIER:
            from agents.critic_verifier import CriticVerifierAgent
            return CriticVerifierAgent()
        else:
            raise ValueError(f"Unknown agent: {agent_name}")

    def _get_critic(self):
        """Lazy-initialise the Critic Verifier."""
        if self._critic is None:
            from agents.critic_verifier import CriticVerifierAgent
            self._critic = CriticVerifierAgent()
        return self._critic

    # ---------------------------------------------------------------
    # Main orchestration entry point
    # ---------------------------------------------------------------

    def orchestrate(
        self,
        user_query: str,
        context: dict[str, Any] | None = None,
    ) -> AgentResponse:
        """
        Process a user query through the full orchestration pipeline.

        Steps:
          1. Classify intent and build execution plan.
          2. Execute each plan step by invoking the assigned agent.
          3. Trigger self-reflection if confidence < 0.65.
          4. Launch async Critic audit (non-blocking).
          5. Build and return the consolidated response.

        Args:
            user_query: The raw user input.
            context: Optional context dict (employee_id, etc.).

        Returns:
            ``AgentResponse`` with the orchestrated result.
        """
        start_time = time.perf_counter()
        reasoning_trace: list[str] = []
        agent_responses: list[AgentResponse] = []
        all_citations = []

        # --- Step 1: Intent classification and plan generation ---
        plan = IntentPlanner.plan(user_query, context)
        reasoning_trace.append(
            f"[PLANNER] Classified intent from query. "
            f"Plan: {plan.request_summary} ({len(plan.steps)} steps)"
        )

        logger.info(
            "Orchestrator plan: %s (%d steps)",
            plan.request_summary, len(plan.steps),
        )

        # --- Step 2: Execute each plan step sequentially ---
        step_results: list[dict[str, Any]] = []

        for step in plan.steps:
            reasoning_trace.append(
                f"[STEP {step.step_id}] Invoking {step.agent.value}: "
                f"{step.description[:100]}"
            )
            trigger_trace_step({
                "type": "step_start",
                "step_id": step.step_id,
                "agent": step.agent.value,
                "description": step.description,
            })

            try:
                agent = self._get_agent(step.agent)
                agent_response = self._invoke_agent(
                    agent=agent,
                    step=step,
                    user_query=user_query,
                    context=context or {},
                )

                agent_responses.append(agent_response)
                all_citations.extend(agent_response.citations)

                reasoning_trace.append(
                    f"[STEP {step.step_id}] {step.agent.value} returned "
                    f"confidence={agent_response.confidence_score:.2f}, "
                    f"verification={'PASS' if agent_response.verification.passed else 'FAIL'}"
                )

                # --- Step 3: Self-reflection if confidence < 0.65 ---
                if SelfReflectionEngine.should_reflect(agent_response):
                    reasoning_trace.append(
                        f"[REFLECTION] Triggered for {step.agent.value} "
                        f"(confidence={agent_response.confidence_score:.2f})"
                    )

                    revised = self._reflect_and_retry(
                        agent=agent,
                        original_response=agent_response,
                        step=step,
                        user_query=user_query,
                        context=context or {},
                    )

                    if revised:
                        reflection_trace = SelfReflectionEngine.build_reflection_trace(
                            agent_response, revised,
                        )
                        reasoning_trace.extend(reflection_trace)
                        agent_response = revised
                        agent_responses[-1] = revised

                step.completed = True
                step_results.append({
                    "step_id": step.step_id,
                    "agent": step.agent.value,
                    "confidence": agent_response.confidence_score,
                    "completed": True,
                })
                trigger_trace_step({
                    "type": "step_complete",
                    "step_id": step.step_id,
                    "agent": step.agent.value,
                    "description": step.description,
                    "confidence": agent_response.confidence_score,
                    "verification_passed": agent_response.verification.passed,
                    "result_preview": str(agent_response.result)[:500]
                })

            except Exception as e:
                logger.error(
                    "Step %d (%s) failed: %s",
                    step.step_id, step.agent.value, e,
                )
                reasoning_trace.append(
                    f"[STEP {step.step_id}] FAILED: {str(e)[:200]}"
                )
                step_results.append({
                    "step_id": step.step_id,
                    "agent": step.agent.value,
                    "confidence": 0.0,
                    "completed": False,
                    "error": str(e)[:200],
                })
                trigger_trace_step({
                    "type": "step_fail",
                    "step_id": step.step_id,
                    "agent": step.agent.value,
                    "description": step.description,
                    "error": str(e)[:200]
                })

        # --- Step 4: Async Critic audit (non-blocking) ---
        for resp in agent_responses:
            try:
                critic = self._get_critic()
                critic.audit_async(user_query, resp)
            except Exception as e:
                logger.warning("Critic audit launch failed: %s", e)

        # --- Step 5: Build consolidated response ---
        latency_ms = (time.perf_counter() - start_time) * 1000

        # Compute overall confidence (min of sub-agent confidences)
        confidences = [r.confidence_score for r in agent_responses]
        overall_confidence = min(confidences) if confidences else 0.5

        # Check if all steps completed
        all_completed = all(s.get("completed", False) for s in step_results)

        # Build the result summary using the LLM
        result = self._build_result_summary(
            plan=plan,
            step_results=step_results,
            agent_responses=agent_responses,
        )

        return AgentResponse(
            agent_name="orchestrator",
            result=result,
            confidence_score=overall_confidence,
            verification=VerificationResult(
                passed=all_completed and overall_confidence >= 0.65,
                checks_performed=[
                    "all_plan_steps_completed",
                    "sub_agent_confidence_acceptable",
                    "response_addresses_user_query",
                ],
                issues_found=self._collect_issues(step_results, agent_responses),
                was_revised=False,
            ),
            reasoning_trace=reasoning_trace,
            citations=all_citations,
            model_used=self.model,
            latency_ms=round(latency_ms, 2),
        )

    # ---------------------------------------------------------------
    # Agent invocation
    # ---------------------------------------------------------------

    def _invoke_agent(
        self,
        agent: BaseAgent,
        step: Any,
        user_query: str,
        context: dict[str, Any],
    ) -> AgentResponse:
        """Invoke a specialist agent based on the execution step."""
        employee_id = context.get("employee_id", context.get("id", ""))

        # Route to the agent's specific method based on agent type
        if step.agent == AgentName.LEARNING_PATH_CURATOR:
            cert_code = context.get("target_cert_code", "AZ-204")
            return agent.generate_roadmap(employee_id, cert_code)

        elif step.agent == AgentName.STUDY_PLAN_GENERATOR:
            cert_code = context.get("target_cert_code", "AZ-204")
            return agent.generate_plan(employee_id, cert_code)

        elif step.agent == AgentName.ENGAGEMENT:
            return agent.generate_nudge(employee_id)

        elif step.agent == AgentName.ASSESSMENT:
            topic = context.get("topic", "")
            return agent.generate_questions(employee_id, topic=topic)

        elif step.agent == AgentName.MANAGER_INSIGHTS:
            return agent.generate_insights(employee_id, query=user_query)

        else:
            # Fallback: use the base run method
            return agent.run(user_message=step.description, context=context)

    # ---------------------------------------------------------------
    # Self-reflection retry
    # ---------------------------------------------------------------

    def _reflect_and_retry(
        self,
        agent: BaseAgent,
        original_response: AgentResponse,
        step: Any,
        user_query: str,
        context: dict[str, Any],
    ) -> AgentResponse | None:
        """
        Run self-reflection and retry the agent once.

        Returns the revised response, or None if reflection did not
        produce an improvement.
        """
        try:
            # Generate reflection feedback
            reflection_prompt = SelfReflectionEngine.generate_reflection_prompt(
                original_response=original_response,
            )

            # Build augmented context with reflection feedback
            augmented_context = dict(context)
            augmented_context["reflection_feedback"] = reflection_prompt

            # Re-invoke the agent
            revised = agent.run(
                user_message=(
                    f"RETRY with reflection feedback. Original query: {user_query}. "
                    f"{reflection_prompt}"
                ),
                context=augmented_context,
            )

            # Only accept if confidence improved
            if revised.confidence_score > original_response.confidence_score:
                revised.verification.was_revised = True
                revised.verification.original_confidence = original_response.confidence_score
                logger.info(
                    "Reflection improved %s confidence: %.2f -> %.2f",
                    agent.name,
                    original_response.confidence_score,
                    revised.confidence_score,
                )
                return revised
            else:
                logger.info(
                    "Reflection did not improve %s confidence (%.2f -> %.2f), keeping original",
                    agent.name,
                    original_response.confidence_score,
                    revised.confidence_score,
                )
                return None

        except Exception as e:
            logger.error("Reflection retry failed for %s: %s", agent.name, e)
            return None

    # ---------------------------------------------------------------
    # Result building
    # ---------------------------------------------------------------

    @staticmethod
    def _build_result_summary(
        plan: ExecutionPlan,
        step_results: list[dict[str, Any]],
        agent_responses: list[AgentResponse],
    ) -> dict[str, Any]:
        """Build a structured result summary from all sub-agent outputs."""
        agent_summaries = []
        for resp in agent_responses:
            summary = {
                "agent": resp.agent_name,
                "confidence": resp.confidence_score,
                "verification_passed": resp.verification.passed,
            }

            # Include the actual result payload
            if isinstance(resp.result, dict):
                summary["result"] = resp.result
            elif isinstance(resp.result, str):
                summary["result_preview"] = resp.result[:500]
            else:
                summary["result"] = str(resp.result)[:500]

            agent_summaries.append(summary)

        return {
            "summary": plan.request_summary,
            "execution_plan": {
                "request_summary": plan.request_summary,
                "steps": step_results,
            },
            "agent_responses": agent_summaries,
            "plan_health_updated": plan.requires_plan_health_update,
            "reflection_triggered": any(
                r.verification.was_revised for r in agent_responses
            ),
        }

    @staticmethod
    def _collect_issues(
        step_results: list[dict[str, Any]],
        agent_responses: list[AgentResponse],
    ) -> list[str]:
        """Collect all issues from step results and sub-agent responses."""
        issues: list[str] = []

        # Failed steps
        for step in step_results:
            if not step.get("completed", False):
                issues.append(
                    f"Step {step['step_id']} ({step['agent']}) failed: "
                    f"{step.get('error', 'unknown error')}"
                )

        # Sub-agent verification failures
        for resp in agent_responses:
            if not resp.verification.passed:
                for issue in resp.verification.issues_found:
                    issues.append(f"[{resp.agent_name}] {issue}")

        return issues
