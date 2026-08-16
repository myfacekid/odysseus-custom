"""Agent permission modes, approval waits, and change-tape helpers.

Ask mode pauses mutating tools until the user allows/denies via
``POST /api/chat/tool-approval/{session_id}``. Auto mode runs immediately.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any, Dict, List, Optional, Set

from src.plan_mode import PLAN_WRITE_DENYLIST

logger = logging.getLogger(__name__)

PREF_PERMISSION_MODE = "agent_permission_mode"
PREF_ALLOWED_TOOLS = "agent_allowed_tools"

MODE_ASK = "ask"
MODE_AUTO = "auto"
DEFAULT_MODE = MODE_ASK

APPROVAL_REQUIRED_TOOLS = frozenset(PLAN_WRITE_DENYLIST)
_MCP_PREFIX = "mcp__"

APPROVAL_TIMEOUT_S = 300.0
APPROVAL_KEEPALIVE_S = 12.0

Decision = str  # approve | deny | always_session | always


def normalize_mode(raw: Any) -> str:
    mode = str(raw or DEFAULT_MODE).strip().lower()
    return MODE_AUTO if mode == MODE_AUTO else MODE_ASK


def load_permission_prefs(owner: Optional[str]) -> Dict[str, Any]:
    """Load permission mode + permanent tool allowlist for owner."""
    try:
        from routes.prefs_routes import _load_for_user

        prefs = _load_for_user(owner) or {}
    except Exception as exc:
        logger.warning("tool_permissions: prefs load failed: %s", exc)
        prefs = {}
    allowed = prefs.get(PREF_ALLOWED_TOOLS) or []
    if not isinstance(allowed, list):
        allowed = []
    return {
        "mode": normalize_mode(prefs.get(PREF_PERMISSION_MODE)),
        "allowed_tools": {str(t).strip() for t in allowed if str(t).strip()},
    }


def save_allowed_tool(owner: Optional[str], tool_name: str) -> None:
    """Persist tool_name on the permanent allowlist."""
    tool_name = (tool_name or "").strip()
    if not tool_name:
        return
    try:
        from routes.prefs_routes import _load_for_user, _save_for_user

        prefs = _load_for_user(owner) or {}
        allowed = prefs.get(PREF_ALLOWED_TOOLS) or []
        if not isinstance(allowed, list):
            allowed = []
        if tool_name not in allowed:
            allowed.append(tool_name)
            prefs[PREF_ALLOWED_TOOLS] = allowed
            _save_for_user(owner, prefs)
    except Exception as exc:
        logger.warning("tool_permissions: save allowlist failed: %s", exc)


def tool_needs_approval(tool_name: Optional[str]) -> bool:
    if not tool_name or not isinstance(tool_name, str):
        return False
    if tool_name in APPROVAL_REQUIRED_TOOLS:
        return True
    return tool_name.startswith(_MCP_PREFIX)


def is_allowed(
    tool_name: str,
    *,
    permanent: Optional[Set[str]] = None,
    session: Optional[Set[str]] = None,
) -> bool:
    if tool_name in (permanent or ()):
        return True
    if tool_name in (session or ()):
        return True
    return False


def should_request_approval(
    tool_name: str,
    *,
    mode: str,
    permanent: Optional[Set[str]] = None,
    session: Optional[Set[str]] = None,
) -> bool:
    if normalize_mode(mode) != MODE_ASK:
        return False
    if not tool_needs_approval(tool_name):
        return False
    return not is_allowed(tool_name, permanent=permanent, session=session)


class ApprovalRegistry:
    """In-process pending tool approvals keyed by approval_id."""

    def __init__(self) -> None:
        self._pending: Dict[str, Dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def create(
        self,
        *,
        tool: str,
        command: str,
        session_id: Optional[str],
        owner: Optional[str],
    ) -> str:
        approval_id = uuid.uuid4().hex
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        async with self._lock:
            self._pending[approval_id] = {
                "future": fut,
                "tool": tool,
                "command": command,
                "session_id": session_id,
                "owner": owner,
                "created_at": time.time(),
            }
        return approval_id

    async def resolve(self, approval_id: str, decision: Decision) -> bool:
        decision = (decision or "").strip().lower()
        if decision not in ("approve", "deny", "always_session", "always"):
            return False
        async with self._lock:
            entry = self._pending.pop(approval_id, None)
        if not entry:
            return False
        fut: asyncio.Future = entry["future"]
        if not fut.done():
            fut.set_result(decision)
        return True

    def peek(self, approval_id: str) -> Optional[Dict[str, Any]]:
        entry = self._pending.get(approval_id)
        if not entry:
            return None
        return {
            "tool": entry["tool"],
            "command": entry["command"],
            "session_id": entry["session_id"],
            "owner": entry["owner"],
            "created_at": entry["created_at"],
        }

    def get_future(self, approval_id: str) -> Optional[asyncio.Future]:
        entry = self._pending.get(approval_id)
        return entry["future"] if entry else None

    async def wait(self, approval_id: str, timeout: float = APPROVAL_TIMEOUT_S) -> Decision:
        async with self._lock:
            entry = self._pending.get(approval_id)
        if not entry:
            return "deny"
        fut: asyncio.Future = entry["future"]
        try:
            return await asyncio.wait_for(asyncio.shield(fut), timeout=timeout)
        except asyncio.TimeoutError:
            async with self._lock:
                self._pending.pop(approval_id, None)
            if not fut.done():
                fut.set_result("deny")
            return "deny"
        except asyncio.CancelledError:
            async with self._lock:
                self._pending.pop(approval_id, None)
            if not fut.done():
                fut.cancel()
            raise

    async def cancel_session(self, session_id: Optional[str]) -> None:
        if not session_id:
            return
        async with self._lock:
            to_cancel = [
                aid
                for aid, e in self._pending.items()
                if e.get("session_id") == session_id
            ]
            entries = [(aid, self._pending.pop(aid)) for aid in to_cancel]
        for _aid, entry in entries:
            fut = entry["future"]
            if not fut.done():
                fut.set_result("deny")


_registry: Optional[ApprovalRegistry] = None


def get_approval_registry() -> ApprovalRegistry:
    global _registry
    if _registry is None:
        _registry = ApprovalRegistry()
    return _registry


_session_allow: Dict[str, Set[str]] = {}


def session_allowlist(session_id: Optional[str]) -> Set[str]:
    if not session_id:
        return set()
    return _session_allow.setdefault(session_id, set())


def allow_tool_for_session(session_id: Optional[str], tool_name: str) -> None:
    if not session_id or not tool_name:
        return
    session_allowlist(session_id).add(tool_name)


def build_change_entry(
    tool: str,
    command: str,
    result: Dict[str, Any],
    output_text: str = "",
) -> Optional[Dict[str, Any]]:
    """Build a change-tape row for a successful mutating tool, else None."""
    if not tool_needs_approval(tool):
        return None
    if result.get("success") is False:
        return None
    exit_code = result.get("exit_code")
    if exit_code not in (None, 0):
        return None
    err = result.get("error")
    if err and not result.get("doc_id") and not result.get("action"):
        return None

    summary = _summarize_change(tool, command, result, output_text)
    entry: Dict[str, Any] = {
        "tool": tool,
        "summary": summary,
        "command": (command or "")[:200],
        "ok": True,
    }
    if result.get("doc_id"):
        entry["doc_id"] = result["doc_id"]
        entry["title"] = result.get("title") or ""
    path = result.get("path")
    if path:
        entry["path"] = path
    return entry


def _summarize_change(
    tool: str,
    command: str,
    result: Dict[str, Any],
    output_text: str,
) -> str:
    title = result.get("title") or ""
    path = result.get("path") or ""
    action = result.get("action") or ""

    if tool in ("create_document", "update_document", "edit_document", "suggest_document"):
        label = {
            "create": "Created",
            "edit": "Edited",
            "update": "Updated",
            "suggest": "Suggested edits on",
        }.get(action, "Updated")
        return f'{label} document "{title or result.get("doc_id", "")}"'.strip()
    if tool in ("write_file", "write_project_file"):
        return f"Wrote {path or (command or '').splitlines()[0][:80]}"
    if tool == "run_project_script":
        return f"Ran project script {path or command[:80]}"
    if tool == "bash":
        first = (command or "").strip().splitlines()[0][:100]
        return f"Shell: {first}" if first else "Ran shell command"
    if tool == "python":
        return "Ran Python"
    if tool.startswith("manage_"):
        return f"{tool.replace('_', ' ').title()}: {action or (command or '')[:80]}"
    if tool in (
        "download_model",
        "serve_model",
        "serve_preset",
        "stop_served_model",
        "cancel_download",
        "adopt_served_model",
    ):
        return f"Cookbook: {tool.replace('_', ' ')}"
    if tool == "ui_control":
        return f"UI: {result.get('toggle_name') or result.get('mode') or command[:80] or 'control'}"
    if tool in ("send_email", "reply_to_email"):
        return "Sent email"
    if output_text:
        return output_text[:120]
    first = (command or "").strip().splitlines()[0][:100]
    return f"{tool}: {first}" if first else tool


def denied_tool_result(tool: str, reason: str = "User denied tool permission") -> Dict[str, Any]:
    return {
        "error": reason,
        "exit_code": 1,
        "output": f"[permission denied] {tool}: {reason}",
    }


def format_steer_message(text: str) -> str:
    body = (text or "").strip()
    return (
        "[User steering — apply before continuing]\n"
        f"{body}\n\n"
        "Continue from the current state. Do not redo successful tool work unless "
        "the user asked to reverse it. Prefer adjusting the plan and next tools."
    )
