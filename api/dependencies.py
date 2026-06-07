# api/dependencies.py
from functools import lru_cache
from typing import Any
from agents.orchestrator import OrchestratorAgent
from integrations.foundry_iq import FoundryIQ
from integrations.work_iq import WorkIQ
from integrations.fabric_iq import FabricIQ
from integrations.microsoft_learn_mcp import MicrosoftLearnMCP

# ── Agent Singleton ──────────────────────────────────────────────
@lru_cache(maxsize=1)
def get_orchestrator() -> OrchestratorAgent:
    return OrchestratorAgent()

# ── Integration Singletons ───────────────────────────────────────
@lru_cache(maxsize=1)
def get_foundry_iq() -> FoundryIQ:
    return FoundryIQ()

@lru_cache(maxsize=1)
def get_work_iq() -> WorkIQ:
    return WorkIQ()

@lru_cache(maxsize=1)
def get_fabric_iq() -> FabricIQ:
    return FabricIQ()

@lru_cache(maxsize=1)
def get_mcp() -> MicrosoftLearnMCP:
    return MicrosoftLearnMCP()

# ── In-Memory State Stores ───────────────────────────────────────
# dict[employee_id: str, dict[str, Any]]
assessment_sessions: dict[str, Any] = {}

def get_assessment_sessions() -> dict[str, Any]:
    return assessment_sessions

# HITL approvals: pending/approved/deferred readiness decisions
# dict[employee_id: str, dict[str, Any]]
hitl_store: dict[str, Any] = {}

def get_hitl_store() -> dict[str, Any]:
    return hitl_store

# Reasoning trace store: last 50 traces for Observability Panel
trace_store: list[dict[str, Any]] = []
MAX_TRACES = 50

def get_trace_store() -> list[dict[str, Any]]:
    return trace_store

def append_trace(trace: dict[str, Any]):
    """Append a trace and evict oldest if over MAX_TRACES."""
    trace_store.append(trace)
    if len(trace_store) > MAX_TRACES:
        trace_store.pop(0)
