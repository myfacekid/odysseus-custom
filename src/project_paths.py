"""Path containment for project working directories (Phase 0).

Depth boundary: all project file operations resolve under the registered
working_dir via realpath containment checks.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Tuple

WORKING_DIR_OK = "ok"
WORKING_DIR_MISSING = "missing"
WORKING_DIR_PERMISSION_DENIED = "permission_denied"
WORKING_DIR_INVALID = "invalid"

WORKING_DIR_STATUSES = frozenset({
    WORKING_DIR_OK,
    WORKING_DIR_MISSING,
    WORKING_DIR_PERMISSION_DENIED,
    WORKING_DIR_INVALID,
})


class ProjectPathError(ValueError):
    """Raised when a project-relative path cannot be resolved safely."""


def is_path_under_root(resolved: str, root: str) -> bool:
    """Return True when *resolved* is equal to or nested under *root*."""
    root_real = os.path.realpath(root)
    path_real = os.path.realpath(resolved)
    if path_real == root_real:
        return True
    try:
        common = os.path.commonpath([path_real, root_real])
    except ValueError:
        return False
    return common == root_real


def validate_working_dir(raw_path: str) -> Tuple[str, str]:
    """Validate and canonicalize a user-selected working directory.

    Returns ``(canonical_realpath, status)`` where status is one of
    ``WORKING_DIR_*`` constants.
    """
    text = (raw_path or "").strip()
    if not text:
        return "", WORKING_DIR_INVALID

    expanded = os.path.expanduser(text)
    try:
        candidate = os.path.abspath(expanded)
    except OSError:
        return expanded, WORKING_DIR_INVALID

    if not os.path.exists(candidate):
        return candidate, WORKING_DIR_MISSING

    try:
        resolved = os.path.realpath(candidate)
    except OSError:
        return candidate, WORKING_DIR_PERMISSION_DENIED

    if not os.path.isdir(resolved):
        return resolved, WORKING_DIR_INVALID

    if not os.access(resolved, os.R_OK | os.X_OK):
        return resolved, WORKING_DIR_PERMISSION_DENIED

    return resolved, WORKING_DIR_OK


def resolve_path_under_root(
    root: str,
    rel_path: str,
    *,
    must_exist: bool = False,
) -> Path:
    """Resolve *rel_path* under *root* and reject escapes via ``..`` or symlinks."""
    if not root or not str(root).strip():
        raise ProjectPathError("project working directory is not configured")

    root_status = validate_working_dir(root)
    if root_status[1] != WORKING_DIR_OK:
        raise ProjectPathError(f"project working directory is {root_status[1]}")

    root_real = root_status[0]
    raw = (rel_path or "").strip()
    if not raw:
        raise ProjectPathError("path is required")

    expanded = os.path.expanduser(raw)
    if os.path.isabs(expanded):
        candidate = expanded
    else:
        candidate = os.path.join(root_real, expanded)

    try:
        resolved = os.path.realpath(candidate)
    except OSError as exc:
        raise ProjectPathError(f"cannot resolve path: {exc}") from exc

    if not is_path_under_root(resolved, root_real):
        raise ProjectPathError("path is outside project working directory")

    if must_exist and not os.path.exists(resolved):
        raise ProjectPathError("path not found")

    return Path(resolved)


def resolve_project_path(
    working_dir: str,
    rel_path: str,
    *,
    must_exist: bool = False,
) -> Path:
    """Resolve *rel_path* within a project's working directory."""
    return resolve_path_under_root(working_dir, rel_path, must_exist=must_exist)
