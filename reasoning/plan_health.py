"""
CertIQ -- Plan Health Engine
==============================

Cross-agent metric that quantifies a learner's certification readiness
based on three data sources:

  1. **Study History** (completed study hours)
  2. **Certification Curriculum** (recommended study hours)
  3. **Calendar Signals / Work IQ** (availability factor)

Formula
-------
::

    Plan Health = completed_study_hours / (recommended_hours x availability_factor)

Thresholds
----------
==========  =============
Score        Status
==========  =============
>= 0.90     EXCELLING
0.70 - 0.89 ON_TRACK
0.50 - 0.69 STRUGGLING
< 0.50      AT_RISK
==========  =============

Availability Factor
-------------------
::

    MeetingDensityFactor   = avg(meeting_hours_per_day) / 8.0
    FocusWindowDensityFactor = avg(focus_hours_per_day) / 8.0
    AF = 1.0 - MDF + FWDF
    Clamped to [0.1, 1.5]

Intuition:
  - High meetings (MDF -> 1.0) reduce availability: AF goes down.
  - High focus time (FWDF -> 1.0) increases availability: AF goes up.
  - Perfectly balanced day (4h meetings, 4h focus): AF = 1.0 (neutral).
"""

from __future__ import annotations

from agents.schemas import PlanHealth, PlanHealthStatus


class PlanHealthEngine:
    """Pure-function engine for computing Plan Health scores."""

    # ---------------------------------------------------------------
    # Availability Factor computation
    # ---------------------------------------------------------------

    @staticmethod
    def compute_availability_factor(calendar_entries: list[dict]) -> float:
        """
        Compute the Availability Factor from calendar day-entries.

        Each entry is expected to contain:
          - ``meeting_hours_total``  (float)
          - ``deep_work_hours``      (float) -- used as focus hours

        Returns:
            Availability Factor clamped to [0.1, 1.5].
        """
        if not calendar_entries:
            return 1.0  # neutral when no calendar data available

        total_meeting_hours = 0.0
        total_focus_hours = 0.0

        for entry in calendar_entries:
            total_meeting_hours += float(entry.get("meeting_hours_total", 0))
            total_focus_hours += float(entry.get("deep_work_hours", 0))

        num_days = len(calendar_entries)
        avg_meeting = total_meeting_hours / num_days
        avg_focus = total_focus_hours / num_days

        meeting_density_factor = avg_meeting / 8.0   # 8h = full working day
        focus_window_density_factor = avg_focus / 8.0

        af = 1.0 - meeting_density_factor + focus_window_density_factor

        # Clamp to [0.1, 1.5]
        return max(0.1, min(1.5, af))

    # ---------------------------------------------------------------
    # Status classification
    # ---------------------------------------------------------------

    @staticmethod
    def classify_status(score: float) -> PlanHealthStatus:
        """Classify a Plan Health score into a status tier."""
        if score >= 0.90:
            return PlanHealthStatus.EXCELLING
        elif score >= 0.70:
            return PlanHealthStatus.ON_TRACK
        elif score >= 0.50:
            return PlanHealthStatus.STRUGGLING
        else:
            return PlanHealthStatus.AT_RISK

    # ---------------------------------------------------------------
    # Core calculation
    # ---------------------------------------------------------------

    @staticmethod
    def calculate(
        completed_hours: float,
        recommended_hours: float,
        availability_factor: float = 1.0,
    ) -> PlanHealth:
        """
        Compute the Plan Health score.

        Args:
            completed_hours: Total study hours completed in the target period.
            recommended_hours: Hours recommended by the certification curriculum.
            availability_factor: Calendar-derived factor (default 1.0 = neutral).

        Returns:
            A ``PlanHealth`` schema instance with score, status, and inputs.
        """
        # Guard against division by zero
        denominator = recommended_hours * availability_factor
        if denominator <= 0:
            return PlanHealth(
                score=0.0,
                status=PlanHealthStatus.UNKNOWN,
                completed_study_hours=completed_hours,
                recommended_hours=recommended_hours,
                availability_factor=availability_factor,
            )

        raw_score = completed_hours / denominator

        # Cap at 1.5 (matches PlanHealth schema constraint)
        score = min(raw_score, 1.5)

        status = PlanHealthEngine.classify_status(score)

        return PlanHealth(
            score=round(score, 4),
            status=status,
            completed_study_hours=completed_hours,
            recommended_hours=recommended_hours,
            availability_factor=round(availability_factor, 4),
        )

    # ---------------------------------------------------------------
    # Weekly Plan Health from raw data
    # ---------------------------------------------------------------

    @staticmethod
    def calculate_from_data(
        study_sessions: list[dict],
        calendar_entries: list[dict],
        recommended_weekly_hours: float = 5.0,
    ) -> PlanHealth:
        """
        Convenience method that computes Plan Health directly from
        study session records and calendar entries for a given period.

        Args:
            study_sessions: List of session dicts with ``duration_minutes``.
            calendar_entries: List of calendar day-dicts for the period.
            recommended_weekly_hours: Target study hours (default 5.0 for AZ-204).

        Returns:
            A ``PlanHealth`` instance.
        """
        completed_hours = sum(
            s.get("duration_minutes", 0) / 60.0 for s in study_sessions
        )

        af = PlanHealthEngine.compute_availability_factor(calendar_entries)

        return PlanHealthEngine.calculate(
            completed_hours=completed_hours,
            recommended_hours=recommended_weekly_hours,
            availability_factor=af,
        )
