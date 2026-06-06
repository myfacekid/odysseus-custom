"""Scoped file operations under a project working directory (Phase 0)."""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List

from src.project_paths import ProjectPathError, is_path_under_root
from src.project_workspace import (
    ProjectAccessError,
    ProjectNotFoundError,
    assert_project_owner,
    resolve_owned_project_path,
)

MAX_FILE_BYTES = 2_000_000


class ProjectFileError(ValueError):
    """Raised when a project file operation is invalid."""


def _normalize_rel_path(rel_path: str) -> str:
    text = (rel_path or "").strip().replace("\\", "/")
    return text or "."


def _working_dir_root(owner: str, project_id: str) -> str:
    project = assert_project_owner(owner, project_id)
    return project.get("working_dir") or ""


def list_directory(owner: str, project_id: str, rel_path: str = ".") -> List[dict]:
    """List immediate children under *rel_path* within the project cwd."""
    directory = resolve_owned_project_path(
        owner,
        project_id,
        _normalize_rel_path(rel_path),
        must_exist=True,
    )
    if not directory.is_dir():
        raise ProjectFileError("path is not a directory")

    root = _working_dir_root(owner, project_id)
    entries: List[dict] = []
    for item in sorted(directory.iterdir(), key=lambda p: p.name.lower()):
        try:
            resolved = item.resolve()
        except OSError:
            continue
        if not is_path_under_root(str(resolved), root):
            continue
        try:
            rel = resolved.relative_to(Path(root))
        except ValueError:
            continue
        stat = resolved.stat()
        entries.append({
            "name": item.name,
            "path": rel.as_posix(),
            "type": "dir" if resolved.is_dir() else "file",
            "size": stat.st_size if resolved.is_file() else None,
            "modified_at": int(stat.st_mtime),
        })
    return entries


def read_text_file(owner: str, project_id: str, rel_path: str) -> dict:
    """Read a UTF-8 text file under the project cwd."""
    path = resolve_owned_project_path(
        owner,
        project_id,
        _normalize_rel_path(rel_path),
        must_exist=True,
    )
    if not path.is_file():
        raise ProjectFileError("path is not a file")
    size = path.stat().st_size
    if size > MAX_FILE_BYTES:
        raise ProjectFileError(f"file exceeds {MAX_FILE_BYTES} byte limit")
    content = path.read_text(encoding="utf-8")
    root = _working_dir_root(owner, project_id)
    rel = path.relative_to(Path(root)).as_posix()
    return {
        "path": rel,
        "content": content,
        "size": size,
    }


def write_text_file(
    owner: str,
    project_id: str,
    rel_path: str,
    content: str,
    *,
    create_dirs: bool = True,
) -> dict:
    """Write UTF-8 text to a path under the project cwd."""
    if content is None:
        raise ProjectFileError("content is required")
    if len(content.encode("utf-8")) > MAX_FILE_BYTES:
        raise ProjectFileError(f"content exceeds {MAX_FILE_BYTES} byte limit")

    path = resolve_owned_project_path(
        owner,
        project_id,
        _normalize_rel_path(rel_path),
        must_exist=False,
    )
    root = Path(_working_dir_root(owner, project_id))
    if path.resolve() == root.resolve():
        raise ProjectFileError("cannot write project root directory")

    if create_dirs:
        path.parent.mkdir(parents=True, exist_ok=True)
    elif not path.parent.is_dir():
        raise ProjectFileError("parent directory does not exist")

    path.write_text(content, encoding="utf-8")
    stat = path.stat()
    rel = path.relative_to(root).as_posix()
    return {
        "path": rel,
        "size": stat.st_size,
        "modified_at": int(stat.st_mtime),
    }


def mkdir(owner: str, project_id: str, rel_path: str) -> dict:
    """Create a directory under the project cwd."""
    path = resolve_owned_project_path(
        owner,
        project_id,
        _normalize_rel_path(rel_path),
        must_exist=False,
    )
    root = Path(_working_dir_root(owner, project_id))
    if path.resolve() == root.resolve():
        raise ProjectFileError("project root already exists")
    path.mkdir(parents=True, exist_ok=True)
    rel = path.relative_to(root).as_posix()
    return {"path": rel, "type": "dir"}


def delete_path(owner: str, project_id: str, rel_path: str) -> dict:
    """Delete a file or empty directory under the project cwd."""
    path = resolve_owned_project_path(
        owner,
        project_id,
        _normalize_rel_path(rel_path),
        must_exist=True,
    )
    root = Path(_working_dir_root(owner, project_id))
    if path.resolve() == root.resolve():
        raise ProjectFileError("cannot delete project root directory")

    rel = path.relative_to(root).as_posix()
    if path.is_dir():
        path.rmdir()
        kind = "dir"
    elif path.is_file():
        path.unlink()
        kind = "file"
    else:
        raise ProjectFileError("path is not a file or directory")
    return {"path": rel, "deleted": kind}


def map_project_exception(exc: Exception) -> tuple[int, str]:
    """Map domain errors to HTTP status + detail."""
    if isinstance(exc, ProjectNotFoundError):
        return 404, "Project not found"
    if isinstance(exc, ProjectAccessError):
        return 404, "Project not found"
    if isinstance(exc, (ProjectPathError, ProjectFileError, ValueError)):
        return 400, str(exc)
    return 500, "Project operation failed"
