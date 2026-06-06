"""Scoped Python execution under a project working directory (Phase 0c)."""
from __future__ import annotations

import re
import subprocess
import sys
import time
from typing import List, Optional

from src.project_files import ProjectFileError, map_project_exception
from src.project_workspace import assert_project_owner, resolve_owned_project_path

DEFAULT_RUN_TIMEOUT = 60
MAX_RUN_TIMEOUT = 300
MAX_OUTPUT_CHARS = 100_000
_MAX_ARGS = 16
_ARG_RE = re.compile(r"^[A-Za-z0-9_.=/:-]+$")


class ProjectRunError(ValueError):
    """Raised when a project script cannot be executed."""


def _normalize_rel_path(rel_path: str) -> str:
    text = (rel_path or "").strip().replace("\\", "/")
    return text or ""


def _validate_args(args: Optional[List[str]]) -> List[str]:
    validated: List[str] = []
    for arg in args or []:
        text = str(arg)
        if not text or len(text) > 256 or not _ARG_RE.match(text):
            raise ProjectRunError("invalid script argument")
        validated.append(text)
    if len(validated) > _MAX_ARGS:
        raise ProjectRunError("too many script arguments")
    return validated


def _truncate(text: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... (truncated, {len(text)} chars total)"


def run_python_script(
    owner: str,
    project_id: str,
    rel_path: str,
    *,
    args: Optional[List[str]] = None,
    timeout: Optional[int] = None,
) -> dict:
    """Execute a Python file under the project cwd without a shell."""
    rel = _normalize_rel_path(rel_path)
    if not rel:
        raise ProjectRunError("path is required")
    if not rel.lower().endswith(".py"):
        raise ProjectRunError("only .py scripts can be run")

    script_path = resolve_owned_project_path(
        owner,
        project_id,
        rel,
        must_exist=True,
    )
    if not script_path.is_file():
        raise ProjectFileError("path is not a file")

    project = assert_project_owner(owner, project_id)
    working_dir = project.get("working_dir") or ""
    validated_args = _validate_args(args)
    run_timeout = DEFAULT_RUN_TIMEOUT if timeout is None else int(timeout)
    if run_timeout < 1 or run_timeout > MAX_RUN_TIMEOUT:
        raise ProjectRunError(f"timeout must be between 1 and {MAX_RUN_TIMEOUT} seconds")

    argv = [sys.executable or "python3", str(script_path), *validated_args]
    started = time.time()
    try:
        completed = subprocess.run(
            argv,
            cwd=working_dir,
            capture_output=True,
            text=True,
            timeout=run_timeout,
            shell=False,
        )
    except subprocess.TimeoutExpired as exc:
        elapsed_ms = int((time.time() - started) * 1000)
        return {
            "ok": False,
            "path": rel,
            "exit_code": None,
            "timed_out": True,
            "duration_ms": elapsed_ms,
            "stdout": _truncate(exc.stdout or ""),
            "stderr": _truncate(exc.stderr or "") or "Execution timed out",
        }
    except OSError as exc:
        raise ProjectRunError(f"failed to start python: {exc}") from exc

    elapsed_ms = int((time.time() - started) * 1000)
    return {
        "ok": completed.returncode == 0,
        "path": rel,
        "exit_code": completed.returncode,
        "timed_out": False,
        "duration_ms": elapsed_ms,
        "stdout": _truncate(completed.stdout or ""),
        "stderr": _truncate(completed.stderr or ""),
    }


def map_run_exception(exc: Exception) -> tuple[int, str]:
    if isinstance(exc, ProjectRunError):
        return 400, str(exc)
    return map_project_exception(exc)
