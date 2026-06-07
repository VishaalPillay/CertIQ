# reasoning/trace_hook.py
from typing import Any, Callable

_trace_callback: Callable[[dict[str, Any]], None] | None = None

def register_trace_callback(callback: Callable[[dict[str, Any]], None]) -> None:
    """Register a callback for agent execution traces."""
    global _trace_callback
    _trace_callback = callback

def trigger_trace_step(step_info: dict[str, Any]) -> None:
    """Trigger the registered callback with trace step information."""
    if _trace_callback:
        try:
            _trace_callback(step_info)
        except Exception:
            pass
