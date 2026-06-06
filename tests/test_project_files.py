"""Phase 0 — scoped project file CRUD."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routes import project_routes
from src.project_files import (
    ProjectFileError,
    delete_path,
    list_directory,
    read_text_file,
    write_text_file,
)
from src.project_paths import ProjectPathError
from src.project_workspace import create_project


@pytest.fixture
def project_env(tmp_path, monkeypatch):
    monkeypatch.setattr("src.project_workspace.PROJECTS_ROOT", tmp_path / "projects")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    create_project(
        "alice",
        title="Analysis",
        working_dir=str(workspace),
        project_id="proj-files",
    )
    return {"workspace": workspace, "project_id": "proj-files"}


def test_write_read_list_delete_round_trip(project_env):
    pid = project_env["project_id"]
    write_text_file("alice", pid, "src/run.py", "print('hello')\n")
    payload = read_text_file("alice", pid, "src/run.py")
    assert payload["content"] == "print('hello')\n"

    entries = list_directory("alice", pid, ".")
    names = {e["name"] for e in entries}
    assert "src" in names

    nested = list_directory("alice", pid, "src")
    assert nested[0]["path"] == "src/run.py"

    deleted = delete_path("alice", pid, "src/run.py")
    assert deleted["deleted"] == "file"


def test_write_rejects_traversal(project_env):
    with pytest.raises(ProjectPathError):
        write_text_file("alice", project_env["project_id"], "../escape.py", "bad")


def test_read_rejects_missing_file(project_env):
    with pytest.raises(ProjectPathError, match="not found"):
        read_text_file("alice", project_env["project_id"], "missing.py")


def test_api_file_round_trip(project_env, monkeypatch):
    monkeypatch.setattr(project_routes, "get_current_user", lambda request: "alice")
    app = FastAPI()
    app.include_router(project_routes.setup_project_routes())
    client = TestClient(app)
    pid = project_env["project_id"]

    res = client.put(
        f"/api/projects/{pid}/file",
        json={"path": "analysis.py", "content": "x = 1\n"},
    )
    assert res.status_code == 200
    assert res.json()["path"] == "analysis.py"

    res = client.get(f"/api/projects/{pid}/file", params={"path": "analysis.py"})
    assert res.status_code == 200
    assert res.json()["content"] == "x = 1\n"

    res = client.get(f"/api/projects/{pid}/files", params={"path": "."})
    assert res.status_code == 200
    assert any(e["name"] == "analysis.py" for e in res.json()["entries"])


def test_api_rejects_cross_owner(project_env, monkeypatch):
    monkeypatch.setattr(project_routes, "get_current_user", lambda request: "alice")
    app = FastAPI()
    app.include_router(project_routes.setup_project_routes())
    client = TestClient(app)

    res = client.get("/api/projects/proj-files/file", params={"path": "../etc/passwd"})
    assert res.status_code == 400


def test_api_project_create_and_get(project_env, monkeypatch):
    monkeypatch.setattr(project_routes, "get_current_user", lambda request: "alice")
    app = FastAPI()
    app.include_router(project_routes.setup_project_routes())
    client = TestClient(app)

    res = client.get("/api/projects/proj-files")
    assert res.status_code == 200
    assert res.json()["project"]["title"] == "Analysis"

    res = client.get("/api/projects")
    assert res.status_code == 200
    assert res.json()["count"] >= 1


def test_api_unauthenticated(monkeypatch):
    monkeypatch.setattr(project_routes, "get_current_user", lambda request: None)
    app = FastAPI()
    app.include_router(project_routes.setup_project_routes())
    client = TestClient(app)
    res = client.get("/api/projects")
    assert res.status_code == 401
