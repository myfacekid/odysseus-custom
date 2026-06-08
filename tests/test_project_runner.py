"""Phase 0c — scoped project Python runner."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routes import project_routes
from src.project_files import write_text_file
from src.project_paths import ProjectPathError
from src.project_runner import (
    ProjectRunError,
    build_run_env,
    project_run_allow_network,
    run_python_script,
)
from src.project_workspace import create_project


@pytest.fixture
def project_env(tmp_path, monkeypatch):
    monkeypatch.setattr("src.project_workspace.PROJECTS_ROOT", tmp_path / "projects")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    create_project(
        "alice",
        title="Runner",
        working_dir=str(workspace),
        project_id="proj-run",
    )
    return {"workspace": workspace, "project_id": "proj-run"}


def test_run_python_script_success(project_env):
    write_text_file(
        "alice",
        project_env["project_id"],
        "hello.py",
        "print('hello project')\n",
    )
    result = run_python_script("alice", project_env["project_id"], "hello.py")
    assert result["ok"] is True
    assert result["exit_code"] == 0
    assert "hello project" in result["stdout"]


def test_run_python_script_with_args(project_env):
    write_text_file(
        "alice",
        project_env["project_id"],
        "args.py",
        "import sys\nprint(sys.argv[1])\n",
    )
    result = run_python_script(
        "alice",
        project_env["project_id"],
        "args.py",
        args=["world"],
    )
    assert result["ok"] is True
    assert "world" in result["stdout"]


def test_run_rejects_non_python(project_env):
    write_text_file("alice", project_env["project_id"], "notes.txt", "nope")
    with pytest.raises(ProjectRunError, match="only .py"):
        run_python_script("alice", project_env["project_id"], "notes.txt")


def test_run_rejects_path_traversal(project_env):
    write_text_file("alice", project_env["project_id"], "local.py", "pass\n")
    with pytest.raises(ProjectPathError):
        run_python_script("alice", project_env["project_id"], "../outside.py")


def test_run_timeout(project_env):
    write_text_file(
        "alice",
        project_env["project_id"],
        "slow.py",
        "import time\ntime.sleep(2)\n",
    )
    result = run_python_script(
        "alice",
        project_env["project_id"],
        "slow.py",
        timeout=1,
    )
    assert result["timed_out"] is True
    assert result["ok"] is False


def test_run_uses_project_cwd(project_env):
    write_text_file(
        "alice",
        project_env["project_id"],
        "cwd.py",
        "from pathlib import Path\n"
        "Path('out.txt').write_text('cwd-ok\\n')\n"
        "print('done')\n",
    )
    result = run_python_script("alice", project_env["project_id"], "cwd.py")
    assert result["ok"] is True
    assert (project_env["workspace"] / "out.txt").read_text(encoding="utf-8") == "cwd-ok\n"


def test_run_truncates_large_stdout(project_env):
    from src.project_runner import MAX_OUTPUT_CHARS

    write_text_file(
        "alice",
        project_env["project_id"],
        "big.py",
        f"print('{'x' * (MAX_OUTPUT_CHARS + 5000)}')\n",
    )
    result = run_python_script("alice", project_env["project_id"], "big.py")
    assert result["ok"] is True
    assert len(result["stdout"]) <= MAX_OUTPUT_CHARS + 80
    assert "truncated" in result["stdout"]


def test_api_run_endpoint(project_env, monkeypatch):
    monkeypatch.setattr(project_routes, "get_current_user", lambda request: "alice")
    write_text_file(
        "alice",
        project_env["project_id"],
        "api_run.py",
        "print('via api')\n",
    )
    app = FastAPI()
    app.include_router(project_routes.setup_project_routes())
    client = TestClient(app)

    res = client.post(
        f"/api/projects/{project_env['project_id']}/run",
        json={"path": "api_run.py"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert "via api" in body["stdout"]


def test_api_run_rejects_traversal(project_env, monkeypatch):
    monkeypatch.setattr(project_routes, "get_current_user", lambda request: "alice")
    app = FastAPI()
    app.include_router(project_routes.setup_project_routes())
    client = TestClient(app)

    res = client.post(
        f"/api/projects/{project_env['project_id']}/run",
        json={"path": "../../etc/passwd"},
    )
    assert res.status_code == 400


def test_api_run_rejects_cross_owner(project_env, monkeypatch):
    monkeypatch.setattr(project_routes, "get_current_user", lambda request: "bob")
    write_text_file(
        "alice",
        project_env["project_id"],
        "secret.py",
        "print('secret')\n",
    )
    app = FastAPI()
    app.include_router(project_routes.setup_project_routes())
    client = TestClient(app)

    res = client.post(
        f"/api/projects/{project_env['project_id']}/run",
        json={"path": "secret.py"},
    )
    assert res.status_code == 404


def test_build_run_env_strips_proxy_when_network_off(monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.example:8080")
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    env = build_run_env(allow_network=False)
    assert "HTTP_PROXY" not in env
    assert env.get("ODYSSEUS_PROJECT_RUN_NETWORK") == "0"
    assert env.get("PATH") == "/usr/bin:/bin"


def test_build_run_env_inherits_proxy_when_network_on(monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.example:8080")
    env = build_run_env(allow_network=True)
    assert env.get("HTTP_PROXY") == "http://proxy.example:8080"
    assert env.get("ODYSSEUS_PROJECT_RUN_NETWORK") == "1"


def test_run_result_includes_network_policy(project_env, monkeypatch):
    write_text_file(
        "alice",
        project_env["project_id"],
        "net_flag.py",
        "import os\nprint(os.environ.get('ODYSSEUS_PROJECT_RUN_NETWORK', '?'))\n",
    )
    result = run_python_script(
        "alice",
        project_env["project_id"],
        "net_flag.py",
        allow_network=False,
    )
    assert result["network_allowed"] is False
    assert "0" in result["stdout"]

    result_on = run_python_script(
        "alice",
        project_env["project_id"],
        "net_flag.py",
        allow_network=True,
    )
    assert result_on["network_allowed"] is True
    assert "1" in result_on["stdout"]


def test_project_run_allow_network_default_false(monkeypatch):
    monkeypatch.delenv("HTTP_PROXY", raising=False)
    assert project_run_allow_network() is False
