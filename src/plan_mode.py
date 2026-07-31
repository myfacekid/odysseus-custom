"""Plan mode helpers — write denylist and structured plan parsing."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

# Tools that mutate state or take irreversible actions. Plan mode explores
# with read/search tools only; Start switches to agent for execution.
PLAN_WRITE_DENYLIST = frozenset({
    "bash",
    "python",
    "write_file",
    "write_project_file",
    "run_project_script",
    "promote_project_file",
    "create_document",
    "update_document",
    "edit_document",
    "suggest_document",
    "generate_image",
    "edit_image",
    "builtin_browser",
    "app_api",
    "api_call",
    "manage_notes",
    "manage_calendar",
    "manage_tasks",
    "manage_memory",
    "manage_skills",
    "manage_session",
    "manage_endpoints",
    "manage_mcp",
    "manage_webhooks",
    "manage_tokens",
    "manage_documents",
    "manage_settings",
    "manage_research",
    "trigger_research",
    "create_session",
    "send_to_session",
    "pipeline",
    "chat_with_model",
    "ask_teacher",
    "ui_control",
    "download_model",
    "serve_model",
    "stop_served_model",
    "cancel_download",
    "serve_preset",
    "adopt_served_model",
})

# Allow optional space after ```, CRLF, and closing fence without a prior newline
# (models sometimes emit ```plan\n{...}```).
_PLAN_FENCE_RE = re.compile(
    r"```\s*(?:plan|json)\s*\r?\n(.*?)(?:\r?\n)?```",
    re.DOTALL | re.IGNORECASE,
)
_HEADING_RE = re.compile(r"^#{1,3}\s+(.+)$", re.MULTILINE)
_NUMBERED_RE = re.compile(r"^\s*(?:\d+[\.\)]\s+|[-*]\s+)(.+)$", re.MULTILINE)


def strip_plan_fence(text: str) -> str:
    """Remove a trailing ```plan``` / ```json``` fence from assistant text."""
    if not text:
        return text or ""
    return _PLAN_FENCE_RE.sub("", text).rstrip()


def _normalize_steps(raw: Any) -> List[Dict[str, str]]:
    steps: List[Dict[str, str]] = []
    if not isinstance(raw, list):
        return steps
    for item in raw:
        if isinstance(item, str) and item.strip():
            steps.append({"title": item.strip(), "detail": ""})
        elif isinstance(item, dict):
            title = str(item.get("title") or item.get("step") or item.get("name") or "").strip()
            detail = str(item.get("detail") or item.get("description") or item.get("body") or "").strip()
            if title or detail:
                steps.append({"title": title or detail[:80], "detail": detail if title else ""})
    return steps


def _normalize_risks(raw: Any) -> List[str]:
    if isinstance(raw, str) and raw.strip():
        return [raw.strip()]
    if not isinstance(raw, list):
        return []
    out = []
    for item in raw:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
        elif isinstance(item, dict):
            t = str(item.get("title") or item.get("risk") or item.get("text") or "").strip()
            if t:
                out.append(t)
    return out


def _plan_from_dict(data: dict, *, status: str = "ready") -> Optional[Dict[str, Any]]:
    if not isinstance(data, dict):
        return None
    title = str(data.get("title") or data.get("name") or "").strip()
    overview = str(data.get("overview") or data.get("summary") or data.get("description") or "").strip()
    steps = _normalize_steps(data.get("steps") or data.get("todos") or data.get("plan"))
    risks = _normalize_risks(data.get("risks") or data.get("assumptions") or [])
    if not title and not overview and not steps:
        return None
    if not title:
        title = "Plan"
    return {
        "title": title,
        "overview": overview,
        "steps": steps,
        "risks": risks,
        "status": status,
    }


def parse_plan_from_text(text: str, *, status: str = "ready") -> Optional[Dict[str, Any]]:
    """Parse a structured plan from model output.

    Prefers a fenced ```plan``` / ```json``` block; falls back to markdown
    headings + numbered/bulleted steps.
    """
    if not text or not isinstance(text, str):
        return None

    for match in _PLAN_FENCE_RE.finditer(text):
        raw = match.group(1).strip()
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
        plan = _plan_from_dict(data, status=status)
        if plan:
            return plan

    # Markdown fallback
    headings = [m.group(1).strip() for m in _HEADING_RE.finditer(text) if m.group(1).strip()]
    steps_raw = [m.group(1).strip() for m in _NUMBERED_RE.finditer(text) if m.group(1).strip()]
    title = headings[0] if headings else "Plan"
    overview = ""
    # First non-heading, non-list paragraph as overview
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#") or _NUMBERED_RE.match(s) or s.startswith("```"):
            continue
        overview = s
        break
    steps = [{"title": s, "detail": ""} for s in steps_raw[:20]]
    if not steps and not overview and title == "Plan":
        # Last resort: use truncated reply as overview
        cleaned = strip_plan_fence(text).strip()
        if len(cleaned) < 40:
            return None
        overview = cleaned[:280] + ("…" if len(cleaned) > 280 else "")
    return {
        "title": title[:120],
        "overview": overview[:500],
        "steps": steps,
        "risks": [],
        "status": status,
    }


def format_plan_for_execution(plan: Dict[str, Any]) -> str:
    """Render an approved plan as context for the agent execute turn."""
    title = str(plan.get("title") or "Plan").strip()
    overview = str(plan.get("overview") or "").strip()
    lines = [
        f"# Approved plan: {title}",
        "",
        "Execute this plan now. Follow the steps in order. Use tools as needed.",
        "",
    ]
    if overview:
        lines.extend([overview, ""])
    steps = plan.get("steps") or []
    if steps:
        lines.append("## Steps")
        for i, step in enumerate(steps, 1):
            if isinstance(step, dict):
                t = str(step.get("title") or "").strip()
                d = str(step.get("detail") or "").strip()
                lines.append(f"{i}. {t}" + (f" — {d}" if d else ""))
            else:
                lines.append(f"{i}. {step}")
        lines.append("")
    risks = plan.get("risks") or []
    if risks:
        lines.append("## Risks / assumptions")
        for r in risks:
            lines.append(f"- {r}")
        lines.append("")
    return "\n".join(lines).strip()
