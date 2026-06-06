"""Project session tool policy (Phase 0e).

Two-boundary model (see docs/projects-roadmap.md):

- **Depth (cwd):** mutate/read computation files only via scoped project tools.
- **Breadth (graph):** research, Zotero, knowledge graph, documents — unchanged.

Project sessions (``sessions.mode == 'project'``) deny depth escape hatches so
the agent cannot bypass ``working_dir`` with generic shell or filesystem tools.
"""
from __future__ import annotations

from typing import FrozenSet, Optional, Set

# Depth tools registered in later phases; allowed only in project sessions.
PROJECT_DEPTH_ALLOWED_TOOLS: FrozenSet[str] = frozenset({
    "read_project_file",
    "write_project_file",
    "run_project_script",
})

# Generic / unscoped tools that must not run inside a project workspace chat.
PROJECT_DEPTH_DENIED_TOOLS: FrozenSet[str] = frozenset({
    "bash",
    "python",
    "read_file",
    "write_file",
})

PROJECT_MCP_FILESYSTEM_PREFIX = "mcp__filesystem__"

# Documented in roadmap; enforced when agent wrappers land (Phase B/C).
PROJECT_BREADTH_TOOL_EXAMPLES: FrozenSet[str] = frozenset({
    "search_knowledge",
    "search_zotero",
    "trigger_research",
    "manage_research",
    "create_document",
    "edit_document",
})


def is_mcp_filesystem_tool(tool_name: Optional[str]) -> bool:
    if not tool_name or not isinstance(tool_name, str):
        return False
    return tool_name.startswith(PROJECT_MCP_FILESYSTEM_PREFIX)


def is_project_depth_denied_tool(tool_name: Optional[str]) -> bool:
    if not tool_name or not isinstance(tool_name, str):
        return False
    return tool_name in PROJECT_DEPTH_DENIED_TOOLS or is_mcp_filesystem_tool(tool_name)


def session_is_project(session_id: Optional[str]) -> bool:
    """Return True when the session is a project-scoped workspace chat."""
    if not session_id:
        return False
    try:
        from core.database import get_session_mode

        return get_session_mode(session_id) == "project"
    except Exception:
        return False


def disabled_tools_for_project_session() -> Set[str]:
    """Tools to hide/disable for project session agent loops."""
    denied = set(PROJECT_DEPTH_DENIED_TOOLS)
    denied.add("mcp__filesystem__read_file")
    denied.add("mcp__filesystem__write_file")
    denied.add("mcp__filesystem__list_directory")
    return denied


def project_tool_block_reason(
    tool_name: Optional[str],
    session_id: Optional[str],
) -> Optional[str]:
    """Return an error message when a tool is blocked in a project session."""
    if not session_is_project(session_id):
        return None
    if not is_project_depth_denied_tool(tool_name):
        return None
    return (
        f"Tool '{tool_name}' is not available in project workspace chats. "
        "Use project-scoped tools (read_project_file, write_project_file, "
        "run_project_script) for files under the project working directory."
    )
