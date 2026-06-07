# integrations/work_iq.py
from datetime import datetime
from functools import lru_cache
from typing import Any

from data.loader import get_employee_calendar

def get_iso_week(date_str: str) -> int:
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return dt.isocalendar()[1]
    except Exception:
        return 0

def get_duration_minutes(start_str: str, end_str: str) -> int:
    try:
        fmt = "%H:%M"
        t_start = datetime.strptime(start_str, fmt)
        t_end = datetime.strptime(end_str, fmt)
        delta = t_end - t_start
        return int(delta.total_seconds() / 60)
    except Exception:
        return 0

class WorkIQ:
    """
    Work context intelligence layer.
    Reads calendar_data.json entries for an employee and computes:
      - Meeting density (how overloaded their calendar is)
      - Focus windows (when they can actually study)
      - Availability factor (the Plan Health denominator multiplier)
      - Optimal study slots (specific time blocks to recommend)
    """

    def compute_availability_factor(self, employee_id: str, days: int = 10) -> float:
        """
        AF = clamp(1.0 - MDF + FWDF, 0.1, 1.5)
        MDF  = avg(meeting_hours) / 8.0       over last `days` calendar entries
        FWDF = avg(focus_hours) / 8.0         over last `days` calendar entries
        Returns float clamped to [0.1, 1.5].
        """
        entries = get_employee_calendar(employee_id)
        if not entries:
            return 1.0
        
        subset = entries[-days:]
        meeting_hours = [e.get("meeting_hours_total", 0.0) for e in subset]
        focus_hours = [e.get("deep_work_hours", 0.0) for e in subset]
        
        avg_m = sum(meeting_hours) / len(subset)
        avg_f = sum(focus_hours) / len(subset)
        
        mdf = avg_m / 8.0
        fwdf = avg_f / 8.0
        
        af = 1.0 - mdf + fwdf
        return max(0.1, min(1.5, af))

    def get_focus_windows(self, employee_id: str) -> list[dict[str, Any]]:
        """
        Returns list of available study slots across the calendar window.
        Each slot: {"date": str, "start": str, "duration_minutes": int, "quality": str}
        """
        entries = get_employee_calendar(employee_id)
        slots = []
        for entry in entries:
            date_str = entry.get("date", "")
            for slot in entry.get("available_study_slots", []):
                start = slot.get("start", "")
                end = slot.get("end", "")
                quality = slot.get("quality", "medium")
                duration = get_duration_minutes(start, end)
                slots.append({
                    "date": date_str,
                    "start": start,
                    "duration_minutes": duration,
                    "quality": quality
                })
        return slots

    def get_meeting_density(self, employee_id: str) -> dict[str, Any]:
        """
        Returns: {
          "avg_meeting_hours_per_day": float,
          "peak_meeting_days": list[str],      # days with >4h meetings
          "fragmentation_score_avg": float,
          "recommendation": str                # e.g. "Avoid Monday and Wednesday for study"
        }
        """
        entries = get_employee_calendar(employee_id)
        if not entries:
            return {
                "avg_meeting_hours_per_day": 0.0,
                "peak_meeting_days": [],
                "fragmentation_score_avg": 0.0,
                "recommendation": "No calendar data available"
            }
        
        meeting_hours = [e.get("meeting_hours_total", 0.0) for e in entries]
        frag_scores = [e.get("fragmentation_score", 0.0) for e in entries]
        
        avg_meetings = sum(meeting_hours) / len(entries)
        avg_frag = sum(frag_scores) / len(entries)
        
        peak_days = []
        high_meeting_days = []
        for e in entries:
            if e.get("meeting_hours_total", 0.0) > 4.0:
                peak_days.append(e.get("date", ""))
                high_meeting_days.append(e.get("day_of_week", ""))
                
        # Generate recommendations based on peak days of week
        if high_meeting_days:
            # count frequencies of days
            day_counts = {}
            for d in high_meeting_days:
                day_counts[d] = day_counts.get(d, 0) + 1
            # Sort by frequency
            sorted_days = sorted(day_counts.items(), key=lambda x: x[1], reverse=True)
            worst_days = [day for day, count in sorted_days[:2]]
            rec = f"Avoid {', '.join(worst_days)} for deep study due to high meeting load."
        else:
            rec = "Calendar is relatively clear. Any day is suitable for study."
            
        return {
            "avg_meeting_hours_per_day": round(avg_meetings, 2),
            "peak_meeting_days": peak_days,
            "fragmentation_score_avg": round(avg_frag, 2),
            "recommendation": rec
        }

    def get_weekly_summary(self, employee_id: str, week_offset: int = 0) -> dict[str, Any]:
        """
        week_offset=0 = current week, week_offset=-1 = last week.
        Returns aggregated signals for one calendar week.
        """
        entries = get_employee_calendar(employee_id)
        if not entries:
            return {
                "meeting_hours_total": 0.0,
                "deep_work_hours_total": 0.0,
                "focus_windows_count": 0,
                "days_tracked": 0
            }
            
        # Group by ISO week
        weeks_map = {}
        for e in entries:
            date_str = e.get("date", "")
            week_num = get_iso_week(date_str)
            if week_num not in weeks_map:
                weeks_map[week_num] = []
            weeks_map[week_num].append(e)
            
        sorted_weeks = sorted(weeks_map.keys())
        target_idx = len(sorted_weeks) - 1 + week_offset
        if target_idx < 0 or target_idx >= len(sorted_weeks):
            return {
                "meeting_hours_total": 0.0,
                "deep_work_hours_total": 0.0,
                "focus_windows_count": 0,
                "days_tracked": 0
            }
            
        target_week_num = sorted_weeks[target_idx]
        week_entries = weeks_map[target_week_num]
        
        meeting_sum = sum(e.get("meeting_hours_total", 0.0) for e in week_entries)
        focus_sum = sum(e.get("deep_work_hours", 0.0) for e in week_entries)
        slots_count = sum(len(e.get("available_study_slots", [])) for e in week_entries)
        
        return {
            "week_number": target_week_num,
            "meeting_hours_total": round(meeting_sum, 2),
            "deep_work_hours_total": round(focus_sum, 2),
            "focus_windows_count": slots_count,
            "days_tracked": len(week_entries)
        }

@lru_cache(maxsize=1)
def get_work_iq() -> WorkIQ:
    return WorkIQ()
