"""
CertIQ -- Critic Verifier Agent
===================================

Standalone asynchronous audit checker that reviews agent responses
for quality, compliance, and safety.  This agent runs OUT OF BAND
and NEVER blocks user-facing responses.

Fix 3 -- Non-blocking execution patterns:
  - Phase 3 (standalone): threading.Thread(target=..., daemon=True).start()
  - Phase 4 (FastAPI): asyncio.to_thread(critic.audit_response, req, resp)
  - daemon=True ensures the thread does not block process exit during testing.

Uses the **lite** model tier (gpt-4o-mini).

Returns ``AuditEntry`` payload in the ``AgentResponse.result`` field.

Audit Checks:
  1. Groundedness -- Is the response grounded in source material?
  2. Tone compliance -- Is the tone professional and supportive?
  3. Safety violations -- Any harmful, biased, or PII content?
  4. Hallucination risk -- Does the response contain unsupported claims?
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from pathlib import Path
from typing import Any, Callable

from agents.base_agent import BaseAgent
from agents.schemas import AgentResponse, AuditEntry

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are the **Critic Verifier** agent of CertIQ.  You perform post-hoc
quality audits on responses from other agents.

## Your Role
You review agent responses and assess them across four dimensions:
1. **Groundedness**: Is the response grounded in provided source material?
2. **Tone Compliance**: Is the tone professional, supportive, and appropriate?
3. **Safety**: Are there any harmful, biased, or PII-containing elements?
4. **Hallucination Risk**: Does the response contain unsupported claims?

## Output Rules
You MUST respond with a single JSON object matching this exact schema:

```json
{
  "agent_name": "critic_verifier",
  "result": {
    "audit_id": "<uuid>",
    "agent_name": "<name of the agent being audited>",
    "original_response_confidence": <float>,
    "bias_detected": <true|false>,
    "bias_details": "<description or empty string>",
    "hallucination_risk": <0.0-1.0>,
    "rai_compliant": <true|false>,
    "rai_issues": ["<issue 1>", "<issue 2>"],
    "overall_quality_score": <0.0-1.0>,
    "recommendations": ["<recommendation 1>"]
  },
  "confidence_score": <0.0-1.0>,
  "verification": {
    "passed": true,
    "checks_performed": [
      "groundedness_check",
      "tone_compliance_check",
      "safety_check",
      "hallucination_check"
    ],
    "issues_found": [],
    "was_revised": false
  },
  "reasoning_trace": [
    "Step 1: Checked groundedness of claims...",
    "Step 2: Assessed tone and language...",
    "Step 3: Scanned for safety violations...",
    "Step 4: Evaluated hallucination risk..."
  ],
  "citations": []
}
```

## Scoring Guide
- **overall_quality_score >= 0.8**: Good quality, no issues.
- **0.6 <= score < 0.8**: Acceptable but with minor issues.
- **0.4 <= score < 0.6**: Poor quality, needs revision.
- **score < 0.4**: Reject -- significant issues found.

## Important Constraints
- Be objective and specific in your assessment.
- Always explain WHY something is flagged.
- Do NOT be overly harsh -- focus on material issues.
"""


class CriticVerifierAgent(BaseAgent):
    """
    Async audit checker for agent responses.
    Uses the ``lite`` model tier (gpt-4o-mini).
    Does NOT block the user-facing response chain.
    """

    def __init__(self) -> None:
        super().__init__(
            name="critic_verifier",
            system_prompt=SYSTEM_PROMPT,
            model_tier="lite",
        )
        # Store audit results for observability panel retrieval
        self._audit_log: list[AuditEntry] = []

    # ---------------------------------------------------------------
    # Synchronous audit (used internally)
    # ---------------------------------------------------------------

    def audit_response(
        self,
        original_request: str,
        agent_response: AgentResponse,
    ) -> AuditEntry:
        """
        Audit an agent response for quality, compliance, and safety.

        This method is synchronous and is called either directly (for
        testing) or via a daemon thread (for non-blocking execution).

        Args:
            original_request: The original user request.
            agent_response: The agent's response to audit.

        Returns:
            An ``AuditEntry`` with the audit results.
        """
        context = {
            "original_request": original_request,
            "agent_being_audited": agent_response.agent_name,
            "response_confidence": agent_response.confidence_score,
            "response_result": str(agent_response.result)[:2000],  # Truncate for context window
            "verification_passed": agent_response.verification.passed,
            "citations_count": len(agent_response.citations),
            "reasoning_trace_length": len(agent_response.reasoning_trace),
        }

        user_message = (
            f"Audit the following response from the '{agent_response.agent_name}' "
            f"agent. The original request was: '{original_request[:200]}'. "
            f"Check for groundedness, tone, safety, and hallucination risk."
        )

        audit_response = self.run(user_message=user_message, context=context)

        # Parse audit result into AuditEntry
        audit_entry = self._parse_audit_entry(audit_response, agent_response)

        # Store in in-memory audit log (fast access during session)
        self._audit_log.append(audit_entry)

        # Persist to JSONL file (survives process restarts for Phase 5
        # Observability Panel)
        self._persist_audit_entry(audit_entry)

        logger.info(
            "Critic audit complete for '%s' | quality=%.2f | hallucination_risk=%.2f",
            agent_response.agent_name,
            audit_entry.overall_quality_score,
            audit_entry.hallucination_risk,
        )

        return audit_entry

    # ---------------------------------------------------------------
    # Non-blocking audit (Fix 3 -- daemon thread pattern)
    # ---------------------------------------------------------------

    def audit_async(
        self,
        original_request: str,
        agent_response: AgentResponse,
        callback: Callable[[AuditEntry], None] | None = None,
    ) -> threading.Thread:
        """
        Launch an audit in a daemon thread (non-blocking).

        Phase 3: Uses threading.Thread(daemon=True).
        Phase 4: Will be replaced with asyncio.to_thread().

        Args:
            original_request: The original user request.
            agent_response: The agent's response to audit.
            callback: Optional callback invoked with the AuditEntry
                when the audit completes.

        Returns:
            The started daemon Thread (for testing/joining if needed).
        """
        def _run_audit():
            try:
                entry = self.audit_response(original_request, agent_response)
                if callback:
                    callback(entry)
            except Exception as e:
                logger.error("Async audit failed: %s", e)

        thread = threading.Thread(target=_run_audit, daemon=True)
        thread.start()

        logger.info(
            "Launched async audit for '%s' response (daemon thread)",
            agent_response.agent_name,
        )

        return thread

    # ---------------------------------------------------------------
    # Audit log access (for observability panel)
    # ---------------------------------------------------------------

    def get_audit_log(self) -> list[AuditEntry]:
        """Return all audit entries (for the observability panel)."""
        return list(self._audit_log)

    def clear_audit_log(self) -> None:
        """Clear the in-memory audit log."""
        self._audit_log.clear()

    # ---------------------------------------------------------------
    # Internal helpers
    # ---------------------------------------------------------------

    @staticmethod
    def _persist_audit_entry(entry: AuditEntry) -> None:
        """
        Append an audit entry to ``logs/audit_log.jsonl``.

        The in-memory ``_audit_log`` stays for fast access during the
        current session.  This JSONL file survives process restarts
        and gives the Phase 5 Observability Panel a reliable data source.
        """
        try:
            log_path = Path("logs/audit_log.jsonl")
            log_path.parent.mkdir(exist_ok=True)
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry.model_dump(), default=str) + "\n")
        except Exception as e:
            logger.warning("Failed to persist audit entry: %s", e)

    @staticmethod
    def _parse_audit_entry(
        audit_response: AgentResponse,
        original_response: AgentResponse,
    ) -> AuditEntry:
        """
        Parse the Critic's LLM response into an AuditEntry.
        Falls back to defaults if the response is not structured.
        """
        result = audit_response.result

        # If result is a dict (structured response), extract fields
        if isinstance(result, dict):
            return AuditEntry(
                audit_id=result.get("audit_id", str(uuid.uuid4())),
                agent_name=result.get("agent_name", original_response.agent_name),
                original_response_confidence=original_response.confidence_score,
                bias_detected=result.get("bias_detected", False),
                bias_details=result.get("bias_details", ""),
                hallucination_risk=min(max(result.get("hallucination_risk", 0.0), 0.0), 1.0),
                rai_compliant=result.get("rai_compliant", True),
                rai_issues=result.get("rai_issues", []),
                overall_quality_score=min(max(result.get("overall_quality_score", 0.5), 0.0), 1.0),
                recommendations=result.get("recommendations", []),
            )

        # Fallback: create a basic audit entry
        return AuditEntry(
            audit_id=str(uuid.uuid4()),
            agent_name=original_response.agent_name,
            original_response_confidence=original_response.confidence_score,
            overall_quality_score=0.5,
            recommendations=["Audit response was unstructured -- manual review recommended."],
        )
