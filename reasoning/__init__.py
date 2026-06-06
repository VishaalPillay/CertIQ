"""
CertIQ -- Reasoning Engine Package
====================================

Pure-function reasoning modules consumed by the agent layer:

  - ``planner``           -- Intent classification + execution plan generation
  - ``reflection``        -- Confidence-gated self-reflection loop
  - ``plan_health``       -- Cross-agent Plan Health metric
  - ``spaced_repetition`` -- SM-2 review interval calculation
  - ``bloom_taxonomy``    -- Bloom's Taxonomy cognitive level calibration
"""

from reasoning.plan_health import PlanHealthEngine
from reasoning.spaced_repetition import SpacedRepetitionEngine
from reasoning.bloom_taxonomy import BloomTaxonomyCalibrator
from reasoning.reflection import SelfReflectionEngine
from reasoning.planner import IntentPlanner

__all__ = [
    "PlanHealthEngine",
    "SpacedRepetitionEngine",
    "BloomTaxonomyCalibrator",
    "SelfReflectionEngine",
    "IntentPlanner",
]
