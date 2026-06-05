"""
CertIQ — Universal Agent Response Schemas
==========================================

Every agent in the CertIQ system MUST return an AgentResponse.
This is the contract that ensures:
  - Confidence scores are surfaced in the UI
  - Inline verification results are tracked
  - Reasoning traces are available for observability
  - Citations ground AI outputs in source material

No exceptions. No agent returns raw text.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class BloomLevel(str, Enum):
    """Bloom's Taxonomy cognitive levels for question calibration."""
    REMEMBER = "remember"
    UNDERSTAND = "understand"
    APPLY = "apply"
    ANALYZE = "analyze"
    EVALUATE = "evaluate"
    CREATE = "create"


class PlanHealthStatus(str, Enum):
    """Plan Health status classifications."""
    EXCELLING = "excelling"      # > 0.9
    ON_TRACK = "on_track"        # 0.7 - 0.9
    STRUGGLING = "struggling"    # 0.5 - 0.7
    AT_RISK = "at_risk"          # < 0.5
    UNKNOWN = "unknown"          # No data


class RiskProfile(str, Enum):
    """Employee risk profile for demo contrast."""
    AT_RISK = "at_risk"
    STRUGGLING = "struggling"
    ON_TRACK = "on_track"
    EXCELLING = "excelling"
    NEW_STARTER = "new_starter"


class AgentName(str, Enum):
    """All agent names in the system."""
    ORCHESTRATOR = "orchestrator"
    LEARNING_PATH_CURATOR = "learning_path_curator"
    STUDY_PLAN_GENERATOR = "study_plan_generator"
    ENGAGEMENT = "engagement"
    ASSESSMENT = "assessment"
    MANAGER_INSIGHTS = "manager_insights"
    CRITIC_VERIFIER = "critic_verifier"


# ---------------------------------------------------------------------------
# Citation — Source reference for grounded content
# ---------------------------------------------------------------------------

class Citation(BaseModel):
    """A reference to source material that grounds an AI output."""
    source: str = Field(description="Document name or URL")
    section: str = Field(description="Specific section within the document")
    relevance: float = Field(
        ge=0.0, le=1.0,
        description="How relevant this citation is to the output (0.0-1.0)",
    )
    quote: str = Field(default="", description="Direct quote from the source, if applicable")


# ---------------------------------------------------------------------------
# VerificationResult — Inline Critic output
# ---------------------------------------------------------------------------

class VerificationResult(BaseModel):
    """
    Result of inline self-verification performed by each agent
    before returning its response. This is NOT from the standalone
    Critic agent — it's embedded in each agent's system prompt.
    """
    passed: bool = Field(description="Did all verification checks pass?")
    checks_performed: list[str] = Field(
        default_factory=list,
        description="List of verification checks that were run",
    )
    issues_found: list[str] = Field(
        default_factory=list,
        description="Issues found during verification (empty if all passed)",
    )
    was_revised: bool = Field(
        default=False,
        description="Was the output revised after self-check?",
    )
    original_confidence: float | None = Field(
        default=None,
        description="Confidence before revision (only set if was_revised=True)",
    )


# ---------------------------------------------------------------------------
# AgentResponse — THE universal response schema
# ---------------------------------------------------------------------------

class AgentResponse(BaseModel):
    """
    Universal response schema for ALL CertIQ agents.

    Every agent returns this exact schema. The UI reads confidence_score
    to display badges, verification to show inline critic results,
    and reasoning_trace for the observability panel.
    """
    agent_name: str = Field(description="Which agent produced this response")
    result: Any = Field(description="The actual output payload (varies by agent)")
    confidence_score: float = Field(
        ge=0.0, le=1.0,
        description="Agent's self-assessed confidence (displayed in UI)",
    )
    verification: VerificationResult = Field(
        description="Inline critic verification result",
    )
    reasoning_trace: list[str] = Field(
        default_factory=list,
        description="Chain-of-thought reasoning steps for observability",
    )
    citations: list[Citation] = Field(
        default_factory=list,
        description="Source references grounding this output",
    )
    plan_health_impact: float | None = Field(
        default=None,
        description="How this response affects the learner's Plan Health score",
    )
    model_used: str = Field(
        default="",
        description="Which model produced this response (e.g., openai/gpt-4o)",
    )
    latency_ms: float = Field(
        default=0.0,
        description="Time taken for the LLM call in milliseconds",
    )
    timestamp: datetime = Field(
        default_factory=datetime.utcnow,
        description="When this response was generated",
    )


# ---------------------------------------------------------------------------
# Specialist Response Payloads
# ---------------------------------------------------------------------------

class CertificationModule(BaseModel):
    """A single module within a certification."""
    module_id: str
    title: str
    estimated_hours: float
    skills: list[str] = Field(default_factory=list)
    bloom_level: BloomLevel = BloomLevel.REMEMBER


class CertificationRoadmap(BaseModel):
    """Output from the Learning Path Curator."""
    target_certification: str
    certification_code: str
    prerequisites: list[str] = Field(default_factory=list)
    recommended_order: list[str] = Field(default_factory=list)
    modules: list[CertificationModule] = Field(default_factory=list)
    total_estimated_hours: float = 0.0
    rationale: str = ""


class StudyBlock(BaseModel):
    """A single study block in a weekly schedule."""
    day: str
    start_time: str
    end_time: str
    topic: str
    module_id: str
    activity_type: str = Field(
        description="'new_material', 'review', 'practice_quiz', 'deep_dive'",
    )
    duration_minutes: int = 60


class WeeklyStudyPlan(BaseModel):
    """Output from the Study Plan Generator."""
    week_number: int
    focus_modules: list[str]
    study_blocks: list[StudyBlock] = Field(default_factory=list)
    review_sessions: list[StudyBlock] = Field(
        default_factory=list,
        description="Spaced repetition review blocks",
    )
    total_study_hours: float = 0.0
    plan_health_projection: float = 0.0


class StudyPlan(BaseModel):
    """Complete multi-week study plan."""
    learner_id: str
    certification_code: str
    weeks: list[WeeklyStudyPlan] = Field(default_factory=list)
    total_weeks: int = 0
    target_completion_date: str = ""
    spaced_repetition_schedule: dict[str, list[str]] = Field(
        default_factory=dict,
        description="topic -> list of review dates",
    )


class EngagementNudge(BaseModel):
    """Output from the Engagement Agent."""
    learner_id: str
    nudge_type: str = Field(
        description="'reminder', 'encouragement', 'schedule_adjustment', 'escalation'",
    )
    message: str
    suggested_study_time: str | None = None
    plan_health_current: float = 0.0
    escalation_triggered: bool = False
    escalation_reason: str = ""


class AssessmentQuestion(BaseModel):
    """A single practice question from the Assessment Agent."""
    question_id: str
    question_text: str
    question_type: str = Field(description="'multiple_choice' or 'scenario'")
    options: list[str] = Field(default_factory=list)
    correct_answer: str = ""
    explanation: str = ""
    bloom_level: BloomLevel = BloomLevel.REMEMBER
    topic: str = ""
    module_id: str = ""
    citations: list[Citation] = Field(default_factory=list)
    difficulty: float = Field(ge=0.0, le=1.0, default=0.5)


class AssessmentSession(BaseModel):
    """An assessment session with multiple questions."""
    session_id: str
    learner_id: str
    certification_code: str
    questions: list[AssessmentQuestion] = Field(default_factory=list)
    current_bloom_level: BloomLevel = BloomLevel.REMEMBER
    score: float | None = None
    completed: bool = False


class TeamMemberReadiness(BaseModel):
    """Readiness data for a single team member."""
    employee_id: str
    employee_name: str
    target_certification: str
    plan_health: float = 0.0
    plan_health_status: PlanHealthStatus = PlanHealthStatus.UNKNOWN
    completion_percentage: float = 0.0
    predicted_pass_probability: float = 0.0
    predicted_completion_date: str = ""
    risk_factors: list[str] = Field(default_factory=list)
    weeks_at_risk: int = 0


class TeamInsights(BaseModel):
    """Output from the Manager Insights Agent."""
    team_id: str
    team_name: str
    total_members: int = 0
    members_at_risk: int = 0
    members_on_track: int = 0
    members_excelling: int = 0
    overall_readiness: float = 0.0
    member_readiness: list[TeamMemberReadiness] = Field(default_factory=list)
    risk_alerts: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)


class ReadinessApproval(BaseModel):
    """HITL approval gate data."""
    learner_id: str
    learner_name: str
    certification_code: str
    readiness_score: float
    confidence_score: float
    study_hours_completed: float
    study_hours_recommended: float
    plan_health: float
    status: str = Field(
        default="pending",
        description="'pending', 'approved', 'deferred'",
    )
    approved_by: str | None = None
    approval_date: str | None = None
    defer_reason: str | None = None


# ---------------------------------------------------------------------------
# Plan Health
# ---------------------------------------------------------------------------

class PlanHealth(BaseModel):
    """Cross-agent Plan Health metric."""
    learner_id: str = ""
    score: float = Field(ge=0.0, le=1.5, description="Plan Health score (capped at 1.5)")
    status: PlanHealthStatus = PlanHealthStatus.UNKNOWN
    completed_study_hours: float = 0.0
    recommended_hours: float = 0.0
    availability_factor: float = 1.0
    streak_weeks_below_threshold: int = 0
    escalation_triggered: bool = False
    trend: list[float] = Field(
        default_factory=list,
        description="Historical Plan Health scores (last 8 weeks)",
    )


# ---------------------------------------------------------------------------
# Orchestrator-specific schemas
# ---------------------------------------------------------------------------

class PlanStep(BaseModel):
    """A single step in the Orchestrator's execution plan."""
    step_id: int
    description: str
    agent: AgentName
    input_data: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[int] = Field(default_factory=list)
    completed: bool = False


class ExecutionPlan(BaseModel):
    """The Orchestrator's decomposed plan for a user request."""
    request_summary: str
    steps: list[PlanStep] = Field(default_factory=list)
    requires_plan_health_update: bool = False


# ---------------------------------------------------------------------------
# Critic/Verifier audit schema
# ---------------------------------------------------------------------------

class AuditEntry(BaseModel):
    """Async Critic/Verifier audit log entry for observability."""
    audit_id: str
    agent_name: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    original_response_confidence: float
    bias_detected: bool = False
    bias_details: str = ""
    hallucination_risk: float = Field(ge=0.0, le=1.0, default=0.0)
    rai_compliant: bool = True
    rai_issues: list[str] = Field(default_factory=list)
    overall_quality_score: float = Field(ge=0.0, le=1.0, default=0.0)
    recommendations: list[str] = Field(default_factory=list)
