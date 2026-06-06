"""Minimal project record storage for Phase 0 spikes."""
from __future__ import annotations

import json
import logging
import re
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.constants import DATA_DIR
from src.project_paths import (
    WORKING_DIR_OK,
    ProjectPathError,
    resolve_project_path,
    validate_working_dir,
)

logger = logging.getLogger(__name__)

PROJECTS_ROOT = Path(DATA_DIR) / "projects"
_PROJECT_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,128}$")


class ProjectNotFoundError(LookupError):
    """Raised when a project record does not exist for the owner."""


class ProjectAccessError(PermissionError):
    """Raised when a project belongs to another owner."""


def _safe_owner(owner: str) -> str:
    safe = re.sub(r"[^\w.-]", "_", (owner or "default").strip()) or "default"
    return safe


def _project_file(owner: str, project_id: str) -> Path:
    if not _PROJECT_ID_RE.fullmatch(project_id or ""):
        raise ValueError("invalid project id")
    return PROJECTS_ROOT / _safe_owner(owner) / f"{project_id}.json"


def _now_ts() -> int:
    return int(time.time())


def _normalize_working_dir(raw_path: str) -> Dict[str, str]:
    canonical, status = validate_working_dir(raw_path)
    return {
        "working_dir": canonical or (raw_path or "").strip(),
        "working_dir_status": status,
    }


def get_project(owner: str, project_id: str) -> Optional[dict]:
    """Load a project record for *owner*, or None if missing."""
    path = _project_file(owner, project_id)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Failed to read project %s: %s", path, exc)
        return None
    if not isinstance(data, dict):
        return None
    if (data.get("owner") or "") != (owner or ""):
        return None
    return data


def list_projects(owner: str) -> List[dict]:
    """Return project records for *owner*, newest first."""
    owner_dir = PROJECTS_ROOT / _safe_owner(owner)
    if not owner_dir.is_dir():
        return []
    rows: List[dict] = []
    for path in sorted(owner_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(data, dict) and (data.get("owner") or "") == (owner or ""):
            rows.append(refresh_working_dir_status(data))
    return rows


def create_project(
    owner: str,
    *,
    title: str,
    working_dir: str,
    project_id: Optional[str] = None,
    description: str = "",
) -> dict:
    """Create and persist a project record."""
    pid = (project_id or uuid.uuid4().hex[:12]).strip()
    if not _PROJECT_ID_RE.fullmatch(pid):
        raise ValueError("invalid project id")

    wd = _normalize_working_dir(working_dir)
    now = _now_ts()
    record: Dict[str, Any] = {
        "id": pid,
        "owner": owner or "",
        "title": (title or "Untitled project").strip()[:200],
        "description": (description or "").strip()[:2000],
        "created_at": now,
        "updated_at": now,
        **wd,
    }
    save_project(owner, pid, record)
    return record


def save_project(owner: str, project_id: str, data: dict) -> None:
    """Persist a project record to disk."""
    path = _project_file(owner, project_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(data or {})
    payload["id"] = project_id
    payload["owner"] = owner or ""
    payload["updated_at"] = _now_ts()
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def refresh_working_dir_status(project: dict) -> dict:
    """Re-check working_dir on disk and update status fields."""
    data = dict(project or {})
    wd = _normalize_working_dir(data.get("working_dir") or "")
    data.update(wd)
    return data


def assert_project_owner(owner: str, project_id: str) -> dict:
    """Load a project and enforce ownership."""
    project = get_project(owner, project_id)
    if project is not None:
        return refresh_working_dir_status(project)
    if PROJECTS_ROOT.is_dir():
        for path in PROJECTS_ROOT.glob(f"*/{project_id}.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if isinstance(data, dict) and (data.get("id") or path.stem) == project_id:
                raise ProjectAccessError("project not accessible")
    raise ProjectNotFoundError(project_id)


def resolve_owned_project_path(
    owner: str,
    project_id: str,
    rel_path: str,
    *,
    must_exist: bool = False,
) -> Path:
    """Resolve *rel_path* under the project's working directory for *owner*."""
    project = assert_project_owner(owner, project_id)
    status = project.get("working_dir_status") or WORKING_DIR_OK
    if status != WORKING_DIR_OK:
        raise ProjectPathError(f"project working directory is {status}")
    working_dir = project.get("working_dir") or ""
    try:
        return resolve_project_path(working_dir, rel_path, must_exist=must_exist)
    except ProjectPathError:
        raise
    except Exception as exc:
        raise ProjectPathError(str(exc)) from exc
