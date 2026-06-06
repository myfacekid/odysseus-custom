"""Project-scoped chat session helpers (Phase 0d)."""
from __future__ import annotations

import uuid
from typing import Optional

from src.project_workspace import ProjectAccessError, ProjectNotFoundError, assert_project_owner


class ProjectSessionError(ValueError):
    """Raised when a project session operation is invalid."""


def create_project_session(
    session_manager,
    owner: str,
    project_id: str,
    *,
    name: str = "",
    endpoint_url: str = "",
    model: str = "",
    rag: bool = False,
) -> dict:
    """Create a chat session linked to a project workspace."""
    assert_project_owner(owner, project_id)
    if session_manager is None:
        raise ProjectSessionError("session manager unavailable")

    session_id = str(uuid.uuid4())
    session = session_manager.create_session(
        session_id=session_id,
        name=(name or "Project chat").strip()[:200],
        endpoint_url=endpoint_url or "",
        model=model or "",
        rag=rag,
        owner=owner,
        project_id=project_id,
        mode="project",
    )
    return {
        "id": session.id,
        "name": session.name,
        "model": session.model,
        "endpoint_url": session.endpoint_url,
        "mode": "project",
        "project_id": project_id,
        "message_count": session.message_count or 0,
    }


def list_project_sessions(session_manager, owner: str, project_id: str) -> list:
    """List non-archived sessions for a project."""
    assert_project_owner(owner, project_id)
    if session_manager is None:
        raise ProjectSessionError("session manager unavailable")
    return session_manager.list_sessions_for_project(owner, project_id)


def map_session_exception(exc: Exception) -> tuple[int, str]:
    if isinstance(exc, ProjectNotFoundError):
        return 404, "Project not found"
    if isinstance(exc, ProjectAccessError):
        return 404, "Project not found"
    if isinstance(exc, ProjectSessionError):
        return 400, str(exc)
    return 500, "Project session operation failed"
