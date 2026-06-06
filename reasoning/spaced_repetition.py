"""
CertIQ -- Spaced Repetition Engine (SM-2)
===========================================

Implements the SuperMemo-2 algorithm for calculating optimal review
intervals based on quiz performance.

Algorithm
---------
Given a performance rating ``q`` (0-5, mapped from quiz scores):

  - **Easiness Factor (EF)**::

        EF' = EF + (0.1 - (5 - q) * (0.08 + (5 - q) * 0.02))
        # Clamped at minimum 1.3

  - **Repetitions (n) and Interval (I)**:
    - If q < 3:  Reset n = 0, I = 1 day.
    - If q >= 3:
      - n == 0: I = 1 day
      - n == 1: I = 6 days
      - n >  1: I = round(I_prev * EF)
      - Increment n += 1

Quiz Score Mapping
------------------
=================  ====
Quiz Score Range    q
=================  ====
0.00 - 0.30         0
0.31 - 0.44         1
0.45 - 0.54         2
0.55 - 0.64         3
0.65 - 0.79         4
0.80 - 1.00         5
=================  ====
"""

from __future__ import annotations

from typing import Any


class SpacedRepetitionEngine:
    """Pure-function SM-2 spaced repetition calculator."""

    # Default initial values
    DEFAULT_EASINESS_FACTOR: float = 2.5
    DEFAULT_INTERVAL: int = 1
    MIN_EASINESS_FACTOR: float = 1.3
    MAX_INTERVAL_DAYS: int = 365  # Safety cap

    # ---------------------------------------------------------------
    # Quiz score -> SM-2 quality rating (0-5)
    # ---------------------------------------------------------------

    @staticmethod
    def quiz_score_to_quality(quiz_score: float) -> int:
        """
        Map a quiz score (0.0-1.0) to an SM-2 quality rating (0-5).

        The mapping is calibrated so that scores below 0.55 trigger
        a reset (q < 3), which is the SM-2 "failure" threshold.
        """
        if quiz_score <= 0.30:
            return 0
        elif quiz_score <= 0.44:
            return 1
        elif quiz_score <= 0.54:
            return 2
        elif quiz_score <= 0.64:
            return 3
        elif quiz_score <= 0.79:
            return 4
        else:
            return 5

    # ---------------------------------------------------------------
    # Core SM-2 calculation
    # ---------------------------------------------------------------

    @staticmethod
    def calculate_next_review(
        quiz_score: float,
        repetitions: int = 0,
        previous_interval: int = 1,
        easiness_factor: float = 2.5,
    ) -> dict[str, Any]:
        """
        Calculate the next review interval using the SM-2 algorithm.

        Args:
            quiz_score: The learner's quiz score (0.0-1.0).
            repetitions: Number of consecutive successful reviews (n).
            previous_interval: Previous interval in days (I_prev).
            easiness_factor: Current easiness factor (EF, default 2.5).

        Returns:
            Dict with keys:
              - ``interval_days`` (int): Next review interval in days.
              - ``repetitions`` (int): Updated repetition count.
              - ``easiness_factor`` (float): Updated EF.
              - ``quality`` (int): SM-2 quality rating (0-5).
              - ``was_reset`` (bool): Whether the learner was reset (q < 3).
        """
        q = SpacedRepetitionEngine.quiz_score_to_quality(quiz_score)

        # Update easiness factor
        ef = easiness_factor + (0.1 - (5 - q) * (0.08 + (5 - q) * 0.02))
        ef = max(SpacedRepetitionEngine.MIN_EASINESS_FACTOR, ef)

        was_reset = False

        if q < 3:
            # Failed -- reset repetitions and interval
            new_repetitions = 0
            interval = 1
            was_reset = True
        else:
            # Successful recall
            if repetitions == 0:
                interval = 1
            elif repetitions == 1:
                interval = 6
            else:
                interval = round(previous_interval * ef)

            new_repetitions = repetitions + 1

        # Safety cap on interval
        interval = min(interval, SpacedRepetitionEngine.MAX_INTERVAL_DAYS)

        return {
            "interval_days": interval,
            "repetitions": new_repetitions,
            "easiness_factor": round(ef, 4),
            "quality": q,
            "was_reset": was_reset,
        }

    # ---------------------------------------------------------------
    # Batch scheduling for multiple topics
    # ---------------------------------------------------------------

    @staticmethod
    def schedule_reviews(
        topic_scores: list[dict],
        base_date: str = "",
    ) -> list[dict[str, Any]]:
        """
        Generate review schedules for multiple topics based on their
        latest quiz scores.

        Args:
            topic_scores: List of dicts with keys:
              - ``module_id``: Topic identifier.
              - ``quiz_score``: Latest quiz score (0.0-1.0).
              - ``repetitions``: Current repetition count (default 0).
              - ``previous_interval``: Previous interval days (default 1).
              - ``easiness_factor``: Current EF (default 2.5).
            base_date: ISO date string for the reference date (informational).

        Returns:
            List of dicts with the same keys as ``calculate_next_review``
            plus ``module_id`` and ``base_date``.
        """
        schedules = []
        for topic in topic_scores:
            result = SpacedRepetitionEngine.calculate_next_review(
                quiz_score=topic.get("quiz_score", 0.5),
                repetitions=topic.get("repetitions", 0),
                previous_interval=topic.get("previous_interval", 1),
                easiness_factor=topic.get("easiness_factor", 2.5),
            )
            result["module_id"] = topic.get("module_id", "")
            result["base_date"] = base_date
            schedules.append(result)

        return schedules
