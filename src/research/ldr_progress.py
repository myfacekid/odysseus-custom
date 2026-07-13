"""Map Local Deep Research progress events to Odysseus SSE progress payloads."""
from __future__ import annotations

from typing import Any, Callable, Dict, Optional

# Odysseus panel phases (static/js/research/jobs.js)
_PHASE_ALIASES = {
    "planning": "planning",
    "plan": "planning",
    "thinking": "planning",
    "searching": "searching",
    "search": "searching",
    "reading": "reading",
    "fetch": "reading",
    "fetching": "reading",
    "extract": "reading",
    "extracting": "reading",
    "synthesizing": "synthesizing",
    "synthesis": "synthesizing",
    "writing": "synthesizing",
    "report": "synthesizing",
    "done": "done",
    "complete": "done",
    "error": "error",
    "warning": "warning",
}


def normalize_ldr_phase(raw: Optional[str]) -> str:
    key = (raw or "").strip().lower()
    return _PHASE_ALIASES.get(key, key or "searching")


def ldr_event_to_progress(event: Dict[str, Any]) -> Dict[str, Any]:
    """Convert an LDR/strategy progress dict to Odysseus progress_callback shape."""
    if not event:
        return {"phase": "searching"}

    phase = normalize_ldr_phase(
        event.get("phase")
        or event.get("status")
        or event.get("step")
    )
    out: Dict[str, Any] = {"phase": phase}

    message = (event.get("message") or event.get("detail") or event.get("text") or "").strip()
    if message:
        out["message"] = message

    for key in (
        "source", "tool", "query", "round", "round_num", "new_sources", "total_sources",
        "event", "reason",
    ):
        if key in event and event[key] is not None:
            out[key] = event[key]

    if event.get("engine"):
        out["source"] = event["engine"]
    if event.get("tool_name") and "message" not in out:
        out["message"] = str(event["tool_name"])

    return out


def wrap_progress_callback(
    callback: Optional[Callable[[Dict[str, Any]], None]],
) -> Optional[Callable[[Dict[str, Any]], None]]:
    """Return a callback that normalizes LDR events before forwarding."""
    if callback is None:
        return None

    def _wrapped(event: Dict[str, Any]) -> None:
        callback(ldr_event_to_progress(event))

    return _wrapped
