"""
CertIQ -- Centralised Data Loader
===================================

Cached, read-only access to all synthetic JSON data files.
Every agent imports from here -- no agent ever reads JSON directly.

Design decisions:
  - ``lru_cache`` means each file is parsed from disk exactly once per
    process lifetime.  Safe because synthetic data never changes at runtime.
  - Helper look-ups (``get_employee``, ``get_employee_calendar``, etc.)
    keep agent code clean and prevent key-name typos.
  - ``get_managers()`` returns the four employees with ``is_manager: true``
    for O(1) Manager Insights Agent filtering.
"""

from __future__ import annotations

import functools
import json
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Data directory -- relative to *this* file
# ---------------------------------------------------------------------------

DATA_DIR = Path(__file__).parent / "synthetic"

# ---------------------------------------------------------------------------
# Cached loaders -- each file is read exactly once
# ---------------------------------------------------------------------------


@functools.lru_cache(maxsize=None)
def load_employees() -> list[dict[str, Any]]:
    """Load all 20 employee profiles."""
    return json.loads((DATA_DIR / "employees.json").read_text(encoding="utf-8"))


@functools.lru_cache(maxsize=None)
def load_certifications() -> list[dict[str, Any]]:
    """Load all 10 certification definitions."""
    return json.loads((DATA_DIR / "certifications.json").read_text(encoding="utf-8"))


@functools.lru_cache(maxsize=None)
def load_calendar() -> list[dict[str, Any]]:
    """Load calendar data (200 employee-day entries)."""
    return json.loads((DATA_DIR / "calendar_data.json").read_text(encoding="utf-8"))


@functools.lru_cache(maxsize=None)
def load_study_history() -> list[dict[str, Any]]:
    """Load study history for all 20 employees."""
    return json.loads((DATA_DIR / "study_history.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Convenience look-ups
# ---------------------------------------------------------------------------


def get_employee(employee_id: str) -> dict[str, Any] | None:
    """Get a single employee by ``id`` field.  Returns ``None`` if not found."""
    return next((e for e in load_employees() if e["id"] == employee_id), None)


def get_employee_calendar(employee_id: str) -> list[dict[str, Any]]:
    """Get all calendar entries for a given employee (list of day-records)."""
    return [entry for entry in load_calendar() if entry["employee_id"] == employee_id]


def get_employee_history(employee_id: str) -> dict[str, Any] | None:
    """Get the study history record for a given employee.  Returns ``None`` if not found."""
    return next(
        (h for h in load_study_history() if h["employee_id"] == employee_id),
        None,
    )


def get_certification(cert_id: str) -> dict[str, Any] | None:
    """Get a certification definition by its ``id`` field (e.g. ``cert_az204``)."""
    return next((c for c in load_certifications() if c["id"] == cert_id), None)


def get_certification_by_code(code: str) -> dict[str, Any] | None:
    """Get a certification by its short code (e.g. ``AZ-204``)."""
    return next(
        (c for c in load_certifications() if c.get("code", "").upper() == code.upper()),
        None,
    )


def get_team_employees(team: str) -> list[dict[str, Any]]:
    """Get all employees belonging to a specific team."""
    return [e for e in load_employees() if e["team"] == team]


def get_managers() -> list[dict[str, Any]]:
    """Get all employees with ``is_manager: true`` (exactly 4)."""
    return [e for e in load_employees() if e.get("is_manager")]


def get_direct_reports(manager_id: str) -> list[dict[str, Any]]:
    """Get all employees who report to a given manager."""
    return [e for e in load_employees() if e.get("manager_id") == manager_id]
