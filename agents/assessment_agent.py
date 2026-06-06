"""
CertIQ -- Assessment Agent
=============================

Generates grounded, cited practice questions from the Azure AI Search
knowledge base (``certiq-knowledge`` index).  Each question is:

  - Grounded in actual knowledge base content (not hallucinated)
  - Calibrated to the learner's Bloom's Taxonomy level
  - Accompanied by citations to source material
  - Verified by an inline critic before returning

Critical 1 Fix: This agent includes a ``search_knowledge_base()`` method
that queries the Azure AI Search index using semantic + keyword search.
Retrieved chunks are injected verbatim into the system prompt as
GROUNDED CONTEXT so every question is answerable from cited material.

Returns ``AssessmentQuestion`` or ``AssessmentSession`` payload in
the ``AgentResponse.result`` field.

Inline Critic Checklist:
  1. Is the question fully answerable from the cited text chunks?
  2. Does the question match the designated Bloom cognitive level?
  3. Are options distinct and is the explanation detailed?
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient

from agents.base_agent import BaseAgent
from agents.config import settings
from agents.schemas import AgentResponse, BloomLevel
from data.loader import get_certification_by_code, get_employee, get_employee_history
from reasoning.bloom_taxonomy import BloomTaxonomyCalibrator

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are the **Assessment Agent** of CertIQ, an enterprise certification
intelligence platform.

## Your Role
You generate practice questions for certification exam preparation.  Every
question you produce MUST be grounded in the GROUNDED CONTEXT provided below.
You are FORBIDDEN from generating questions about topics not covered in the
grounded context.

## Output Rules
You MUST respond with a single JSON object matching this exact schema:

```json
{
  "agent_name": "assessment",
  "result": {
    "session_id": "<uuid>",
    "learner_id": "<employee_id>",
    "certification_code": "<e.g. AZ-204>",
    "questions": [
      {
        "question_id": "<uuid>",
        "question_text": "<the question>",
        "question_type": "multiple_choice",
        "options": ["A. ...", "B. ...", "C. ...", "D. ..."],
        "correct_answer": "B",
        "explanation": "<detailed explanation citing source material>",
        "bloom_level": "<remember|understand|apply|analyze|evaluate|create>",
        "topic": "<topic name>",
        "module_id": "<module_id>",
        "citations": [
          {
            "source": "<source_file>",
            "section": "<section_heading>",
            "relevance": <0.0-1.0>,
            "quote": "<verbatim quote from the grounded context>"
          }
        ],
        "difficulty": <0.0-1.0>
      }
    ],
    "current_bloom_level": "<the target bloom level>",
    "score": null,
    "completed": false
  },
  "confidence_score": <0.0-1.0>,
  "verification": {
    "passed": <true|false>,
    "checks_performed": [
      "question_grounded_in_context",
      "bloom_level_matches_target",
      "options_are_distinct",
      "explanation_cites_source"
    ],
    "issues_found": [],
    "was_revised": false
  },
  "reasoning_trace": [
    "Step 1: Searched knowledge base for relevant chunks...",
    "Step 2: Calibrated Bloom's level based on learner scores...",
    "Step 3: Generated question from grounded context...",
    "Step 4: Verified question is answerable from cited text..."
  ],
  "citations": []
}
```

## Self-Verification Checklist (CRITICAL -- run BEFORE returning)
1. **Grounding Check**: Is EVERY question fully answerable from the
   GROUNDED CONTEXT text provided?  If you cannot point to a specific
   passage that answers the question, the question is HALLUCINATED
   and you MUST discard it.
2. **Bloom's Level Match**: Does the question's cognitive demand match
   the designated Bloom's level?  (e.g., REMEMBER = recall facts,
   APPLY = solve a problem, ANALYZE = compare/debug)
3. **Option Distinctness**: Are all 4 options meaningfully different?
   No two options should be semantically identical.
4. **Explanation Quality**: Does the explanation reference specific
   content from the grounded context with a verbatim quote?

If ANY check fails, set ``verification.passed`` to ``false``.

## Important Constraints
- Generate exactly the number of questions requested (default: 3).
- Use action verbs appropriate for the Bloom's level.
- Include at least one citation per question.
- For scenario-based questions, provide realistic Azure scenarios.
"""


class AssessmentAgent(BaseAgent):
    """
    Generates grounded practice questions from the Azure AI Search
    knowledge base.  Uses the ``primary`` model tier (gpt-4o).
    """

    def __init__(self) -> None:
        super().__init__(
            name="assessment",
            system_prompt=SYSTEM_PROMPT,
            model_tier="primary",
        )

        # Azure AI Search client for knowledge base queries
        # (Critical 1 fix -- search_knowledge_base method)
        self.search_client = SearchClient(
            endpoint=settings.azure_search_endpoint,
            index_name=settings.azure_search_index_name,
            credential=AzureKeyCredential(settings.azure_search_admin_key),
        )

    # ---------------------------------------------------------------
    # Knowledge base search (Critical 1)
    # ---------------------------------------------------------------

    def search_knowledge_base(
        self,
        query: str,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """
        Query the ``certiq-knowledge`` index using hybrid search
        (BM25 keyword + Azure semantic ranking).

        Retrieved chunks are injected verbatim into the system prompt
        as GROUNDED CONTEXT.  The agent is instructed to ONLY generate
        questions answerable from this context.

        Args:
            query: The search query (e.g., topic name or question).
            top_k: Number of chunks to retrieve (default 5).

        Returns:
            List of dicts with keys: ``content``, ``source``,
            ``section``, ``id``.
        """
        try:
            results = self.search_client.search(
                search_text=query,
                query_type="semantic",
                semantic_configuration_name="certiq-semantic",
                top=top_k,
                select=["content", "source_file", "section_heading", "chunk_id"],
            )

            chunks = []
            for result in results:
                chunks.append({
                    "content": result.get("content", ""),
                    "source": result.get("source_file", ""),
                    "section": result.get("section_heading", ""),
                    "id": result.get("chunk_id", ""),
                })

            logger.info(
                "Assessment Agent retrieved %d chunks for query: '%s'",
                len(chunks), query[:80],
            )
            return chunks

        except Exception as e:
            logger.error("Knowledge base search failed: %s", e)
            return []

    # ---------------------------------------------------------------
    # Public interface
    # ---------------------------------------------------------------

    def generate_questions(
        self,
        employee_id: str,
        topic: str = "",
        cert_code: str = "AZ-204",
        num_questions: int = 3,
    ) -> AgentResponse:
        """
        Generate grounded practice questions for an employee.

        Args:
            employee_id: The employee's ID.
            topic: Specific topic to focus on (optional).
            cert_code: Target certification code.
            num_questions: Number of questions to generate.

        Returns:
            ``AgentResponse`` with ``AssessmentSession`` in ``result``.
        """
        # Determine Bloom's level from study history
        bloom_level = self._calibrate_bloom_level(employee_id, topic)

        # Search knowledge base for grounded content
        search_query = topic if topic else f"{cert_code} certification exam"
        grounded_chunks = self.search_knowledge_base(search_query, top_k=5)

        # Build context
        context = self._build_context(
            employee_id=employee_id,
            cert_code=cert_code,
            bloom_level=bloom_level,
            grounded_chunks=grounded_chunks,
            num_questions=num_questions,
        )

        # Build user message
        bloom_verbs = BloomTaxonomyCalibrator.get_question_verbs(bloom_level)
        user_message = (
            f"Generate {num_questions} practice questions for employee "
            f"{employee_id} on '{topic or cert_code}'. "
            f"Target Bloom's level: {bloom_level.value}. "
            f"Use these action verbs: {', '.join(bloom_verbs[:3])}. "
            f"Every question MUST be answerable from the GROUNDED CONTEXT."
        )

        return self.run(user_message=user_message, context=context)

    # ---------------------------------------------------------------
    # Bloom's level calibration
    # ---------------------------------------------------------------

    def _calibrate_bloom_level(
        self,
        employee_id: str,
        topic: str = "",
    ) -> BloomLevel:
        """
        Determine the target Bloom's level for an employee based on
        their quiz history on the given topic.
        """
        history = get_employee_history(employee_id)
        if not history or not history.get("sessions"):
            # New starter or no history -> basic level
            return BloomLevel.REMEMBER

        sessions = history["sessions"]

        # Filter sessions by topic if specified
        if topic:
            topic_lower = topic.lower()
            relevant = [
                s for s in sessions
                if topic_lower in s.get("topic", "").lower()
            ]
        else:
            relevant = sessions

        if not relevant:
            return BloomLevel.UNDERSTAND

        # Compute average quiz score
        avg_score = sum(s.get("quiz_score", 0) for s in relevant) / len(relevant)

        return BloomTaxonomyCalibrator.calibrate_level(avg_score, topic_difficulty=0.5)

    # ---------------------------------------------------------------
    # Context builder
    # ---------------------------------------------------------------

    def _build_context(
        self,
        employee_id: str,
        cert_code: str,
        bloom_level: BloomLevel,
        grounded_chunks: list[dict[str, Any]],
        num_questions: int,
    ) -> dict[str, Any]:
        """Build the context dict with grounded knowledge base content."""
        context: dict[str, Any] = {}

        # Employee info
        employee = get_employee(employee_id)
        if employee:
            context["employee"] = {
                "id": employee["id"],
                "name": employee["name"],
                "risk_profile": employee.get("risk_profile", "unknown"),
                "current_certifications": employee.get("current_certifications", []),
            }

        # Assessment parameters
        context["assessment_params"] = {
            "certification_code": cert_code,
            "target_bloom_level": bloom_level.value,
            "num_questions": num_questions,
            "session_id": str(uuid.uuid4()),
        }

        # GROUNDED CONTEXT -- this is the critical block
        # These chunks are injected verbatim so the agent can only
        # generate questions from this material.
        if grounded_chunks:
            context["GROUNDED_CONTEXT"] = []
            for i, chunk in enumerate(grounded_chunks):
                context["GROUNDED_CONTEXT"].append({
                    "chunk_index": i + 1,
                    "source_file": chunk.get("source", ""),
                    "section_heading": chunk.get("section", ""),
                    "content": chunk.get("content", ""),
                })

        return context
