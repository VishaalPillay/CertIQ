"""
CertIQ -- Self-Reflection Engine
===================================

Provides the confidence-gated self-reflection loop used by the
Orchestrator.  When an agent's response has a confidence score
below the threshold (0.65), the Orchestrator:

  1. Calls ``should_reflect()`` to confirm reflection is needed.
  2. Calls ``generate_reflection_prompt()`` to build a feedback
     prompt that tells the agent specifically what was lacking.
  3. Re-invokes the agent with the augmented prompt.
  4. Records the before/after confidence for the observability panel.

Design decision:
  The reflection engine is *not* an agent -- it is a pure-function
  module that generates prompt text.  The Orchestrator (an agent)
  performs the actual re-invocation.
"""

from __future__ import annotations

from agents.schemas import AgentResponse


class SelfReflectionEngine:
    """Pure-function engine for confidence-gated self-reflection."""

    # Default threshold -- should match agents.config.settings.confidence_threshold
    DEFAULT_THRESHOLD: float = 0.65
    MAX_REFLECTION_ROUNDS: int = 2

    # ---------------------------------------------------------------
    # Decision gate
    # ---------------------------------------------------------------

    @staticmethod
    def should_reflect(
        response: AgentResponse,
        threshold: float = 0.65,
    ) -> bool:
        """
        Check whether a response warrants self-reflection.

        Returns True if:
          - ``confidence_score`` is below the threshold, OR
          - ``verification.passed`` is False.
        """
        if response.confidence_score < threshold:
            return True
        if not response.verification.passed:
            return True
        return False

    # ---------------------------------------------------------------
    # Reflection prompt generation
    # ---------------------------------------------------------------

    @staticmethod
    def generate_reflection_prompt(
        original_response: AgentResponse,
        issues: list[str] | None = None,
    ) -> str:
        """
        Generate a reflection feedback prompt for the agent retry.

        The prompt tells the agent specifically what was lacking in its
        first attempt (missing citations, weak reasoning, ungrounded
        results, etc.) so it can produce a better second attempt.

        Args:
            original_response: The first-attempt ``AgentResponse``.
            issues: Optional list of specific issues to address.
                If not provided, issues are inferred from the response.

        Returns:
            A formatted prompt string to prepend to the retry request.
        """
        # Infer issues from the response if none provided
        if issues is None:
            issues = SelfReflectionEngine._infer_issues(original_response)

        confidence = original_response.confidence_score
        agent = original_response.agent_name

        lines = [
            "## SELF-REFLECTION FEEDBACK",
            "",
            f"Your previous response (agent: {agent}) had a confidence "
            f"score of {confidence:.2f}, which is below the required "
            f"threshold of 0.65.",
            "",
        ]

        # Add verification failures
        if not original_response.verification.passed:
            lines.append("### Verification Failures")
            for issue in original_response.verification.issues_found:
                lines.append(f"  - {issue}")
            lines.append("")

        # Add specific issues
        if issues:
            lines.append("### Issues to Address in This Retry")
            for i, issue in enumerate(issues, 1):
                lines.append(f"  {i}. {issue}")
            lines.append("")

        # Add guidance
        lines.extend([
            "### Requirements for This Retry",
            "  1. Address ALL issues listed above.",
            "  2. Provide stronger reasoning traces.",
            "  3. Include citations from source material where applicable.",
            "  4. Your confidence score MUST reflect genuine improvement.",
            "  5. If you cannot improve, explain why in the reasoning_trace.",
            "",
            "Respond with the COMPLETE improved response in the same JSON format.",
        ])

        return "\n".join(lines)

    # ---------------------------------------------------------------
    # Issue inference
    # ---------------------------------------------------------------

    @staticmethod
    def _infer_issues(response: AgentResponse) -> list[str]:
        """Infer issues from a low-confidence response."""
        issues: list[str] = []

        # Missing citations
        if not response.citations:
            issues.append(
                "No citations provided. Ground your response in source "
                "material from the knowledge base."
            )

        # Thin reasoning trace
        if len(response.reasoning_trace) < 2:
            issues.append(
                "Reasoning trace is too thin. Provide at least 3-4 "
                "explicit chain-of-thought steps."
            )

        # Failed verification
        if not response.verification.passed:
            issues.append(
                "Self-verification failed. Review the verification "
                "checklist and ensure all checks pass."
            )

        # Low confidence without clear reason
        if response.confidence_score < 0.4:
            issues.append(
                "Confidence is critically low (< 0.40). This suggests "
                "the response may be hallucinated or off-topic. "
                "Re-read the context and try again."
            )

        # Fallback
        if not issues:
            issues.append(
                "The response quality was below threshold. Improve "
                "specificity, depth, and accuracy."
            )

        return issues

    # ---------------------------------------------------------------
    # Utility: track reflection history
    # ---------------------------------------------------------------

    @staticmethod
    def build_reflection_trace(
        original: AgentResponse,
        revised: AgentResponse,
    ) -> list[str]:
        """
        Build a reasoning trace entry documenting the reflection loop.

        Returns a list of trace strings to append to the final response's
        ``reasoning_trace``.
        """
        return [
            f"[REFLECTION] Original confidence: {original.confidence_score:.2f}",
            f"[REFLECTION] Issues found: {len(SelfReflectionEngine._infer_issues(original))}",
            f"[REFLECTION] Revised confidence: {revised.confidence_score:.2f}",
            f"[REFLECTION] Improvement: {revised.confidence_score - original.confidence_score:+.2f}",
        ]
