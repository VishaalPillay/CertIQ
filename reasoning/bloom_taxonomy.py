"""
CertIQ -- Bloom's Taxonomy Calibrator
=======================================

Maps learner performance to one of six cognitive levels defined
by Bloom's revised taxonomy.  Used by the Assessment Agent to
generate questions at the appropriate difficulty.

Levels (ascending complexity)
-----------------------------
1. REMEMBER  -- Recall facts, list definitions
2. UNDERSTAND -- Explain concepts, describe processes
3. APPLY     -- Use knowledge in a new situation (deploy, implement)
4. ANALYZE   -- Break information into parts (debug, compare)
5. EVALUATE  -- Make judgements (argue trade-offs, justify decisions)
6. CREATE    -- Produce new work (design architectures, build solutions)

Calibration Rules
-----------------
===============================  ===========
Condition                         Level
===============================  ===========
avg_score < 0.60 or new starter   REMEMBER / UNDERSTAND
0.60 <= avg_score < 0.75          APPLY
0.75 <= avg_score < 0.85          ANALYZE
avg_score >= 0.85                 EVALUATE / CREATE
===============================  ===========

The ``topic_difficulty`` parameter (0.0-1.0) acts as a tie-breaker
within each tier, pushing toward the higher level when difficulty
is above 0.5.
"""

from __future__ import annotations

from agents.schemas import BloomLevel


# Ordered from lowest to highest cognitive complexity
BLOOM_ORDERED: list[BloomLevel] = [
    BloomLevel.REMEMBER,
    BloomLevel.UNDERSTAND,
    BloomLevel.APPLY,
    BloomLevel.ANALYZE,
    BloomLevel.EVALUATE,
    BloomLevel.CREATE,
]


class BloomTaxonomyCalibrator:
    """
    Pure-function calibrator that maps learner performance metrics
    to the appropriate Bloom's Taxonomy cognitive level.
    """

    @staticmethod
    def calibrate_level(
        avg_score: float,
        topic_difficulty: float = 0.5,
    ) -> BloomLevel:
        """
        Determine the target Bloom's level for question generation.

        Args:
            avg_score: Learner's average quiz score on the topic (0.0-1.0).
            topic_difficulty: Inherent difficulty of the topic (0.0-1.0).
                A higher value pushes the level down (harder topic ->
                easier questions) within the same tier.

        Returns:
            The calibrated ``BloomLevel``.
        """
        # Adjust score slightly based on topic difficulty:
        # Hard topics (difficulty > 0.5) pull the effective score down,
        # easy topics push it up.  Effect is small (max +/- 0.05).
        adjustment = (0.5 - topic_difficulty) * 0.1
        effective_score = avg_score + adjustment

        if effective_score < 0.60:
            # Low performance tier: REMEMBER or UNDERSTAND
            if topic_difficulty > 0.5:
                return BloomLevel.REMEMBER
            return BloomLevel.UNDERSTAND
        elif effective_score < 0.75:
            return BloomLevel.APPLY
        elif effective_score < 0.85:
            return BloomLevel.ANALYZE
        else:
            # High performance tier: EVALUATE or CREATE
            if topic_difficulty > 0.5:
                return BloomLevel.EVALUATE
            return BloomLevel.CREATE

    @staticmethod
    def get_question_verbs(level: BloomLevel) -> list[str]:
        """
        Return action verbs appropriate for each Bloom's level.
        Useful for prompt engineering in the Assessment Agent.
        """
        verbs: dict[BloomLevel, list[str]] = {
            BloomLevel.REMEMBER: [
                "define", "list", "identify", "name", "recall", "state",
            ],
            BloomLevel.UNDERSTAND: [
                "explain", "describe", "summarise", "interpret", "classify",
            ],
            BloomLevel.APPLY: [
                "implement", "deploy", "configure", "solve", "use", "execute",
            ],
            BloomLevel.ANALYZE: [
                "compare", "contrast", "debug", "differentiate", "examine",
            ],
            BloomLevel.EVALUATE: [
                "justify", "assess", "argue", "critique", "prioritise",
            ],
            BloomLevel.CREATE: [
                "design", "architect", "construct", "propose", "develop",
            ],
        }
        return verbs.get(level, ["describe"])

    @staticmethod
    def get_level_index(level: BloomLevel) -> int:
        """Return the ordinal index (0-5) of a Bloom's level."""
        return BLOOM_ORDERED.index(level)

    @staticmethod
    def next_level(level: BloomLevel) -> BloomLevel:
        """Return the next higher Bloom's level (capped at CREATE)."""
        idx = BLOOM_ORDERED.index(level)
        return BLOOM_ORDERED[min(idx + 1, len(BLOOM_ORDERED) - 1)]

    @staticmethod
    def previous_level(level: BloomLevel) -> BloomLevel:
        """Return the previous lower Bloom's level (capped at REMEMBER)."""
        idx = BLOOM_ORDERED.index(level)
        return BLOOM_ORDERED[max(idx - 1, 0)]
