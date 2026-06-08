"""Scoped Python execution under a project working directory (Phase 0c / C)."""
from __future__ import annotations

import os
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

# Proxy / TLS env vars stripped when network is disabled (Phase C).
_NETWORK_ENV_KEYS = frozenset({
    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "FTP_PROXY", "SOCKS_PROXY",
    "http_proxy", "https_proxy", "all_proxy", "ftp_proxy", "socks_proxy",
    "NO_PROXY", "no_proxy",
    "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE",
    "SSL_CERT_FILE", "SSL_CERT_DIR",
})

# Minimal subprocess env when network is off — avoids inheriting secrets/proxy config.
_MINIMAL_ENV_KEYS = frozenset({
    "PATH", "HOME", "USER", "LOGNAME", "USERNAME",
    "LANG", "LC_ALL", "LC_CTYPE",
    "SYSTEMROOT", "SystemRoot", "ComSpec", "PATHEXT", "WINDIR",
    "TMP", "TEMP", "TMPDIR",
    "PYTHONHOME",  # needed on some Windows installs
})


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


def project_run_allow_network() -> bool:
    """Return True when project script runs may inherit network-related env."""
    try:
        from src.settings import get_setting

        return bool(get_setting("project_run_allow_network", False))
    except Exception:
        return False


def build_run_env(*, allow_network: Optional[bool] = None) -> dict:
    """Build subprocess env for project script execution.

    When network is disabled (default), only a minimal env is passed and proxy
    variables are omitted. Scripts can read ``ODYSSEUS_PROJECT_RUN_NETWORK``
    (``"0"`` or ``"1"``). This does not kernel-block sockets — it reduces
    accidental outbound access via inherited proxy config.
    """
    if allow_network is None:
        allow_network = project_run_allow_network()

    if allow_network:
        env = dict(os.environ)
        env["ODYSSEUS_PROJECT_RUN_NETWORK"] = "1"
        env.setdefault("TERM", "xterm-256color")
        return env

    env = {}
    for key in _MINIMAL_ENV_KEYS:
        val = os.environ.get(key)
        if val is not None:
            env[key] = val
    env.setdefault("LANG", "C.UTF-8")
    env.setdefault("LC_ALL", "C.UTF-8")
    env["TERM"] = "xterm-256color"
    env["ODYSSEUS_PROJECT_RUN_NETWORK"] = "0"
    return env


def _run_result_meta(*, allow_network: bool) -> dict:
    return {"network_allowed": allow_network}


def run_python_script(
    owner: str,
    project_id: str,
    rel_path: str,
    *,
    args: Optional[List[str]] = None,
    timeout: Optional[int] = None,
    allow_network: Optional[bool] = None,
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

    if allow_network is None:
        allow_network = project_run_allow_network()
    run_env = build_run_env(allow_network=allow_network)

    argv = [sys.executable or "python3", "-I", str(script_path), *validated_args]
    started = time.time()
    try:
        completed = subprocess.run(
            argv,
            cwd=working_dir,
            capture_output=True,
            text=True,
            timeout=run_timeout,
            shell=False,
            env=run_env,
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
            **_run_result_meta(allow_network=allow_network),
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
        **_run_result_meta(allow_network=allow_network),
    }


def map_run_exception(exc: Exception) -> tuple[int, str]:
    if isinstance(exc, ProjectRunError):
        return 400, str(exc)
    return map_project_exception(exc)
