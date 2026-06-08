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
    rename_path,
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
    names = {e["name"] for e in entries["entries"]}
    assert "src" in names

    nested = list_directory("alice", pid, "src")
    assert nested["entries"][0]["path"] == "src/run.py"

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


def test_rename_path(project_env):
    pid = project_env["project_id"]
    write_text_file("alice", pid, "old/name.py", "x = 1\n")
    result = rename_path("alice", pid, "old/name.py", "new/name.py")
    assert result["from"] == "old/name.py"
    assert result["to"] == "new/name.py"
    payload = read_text_file("alice", pid, "new/name.py")
    assert payload["content"] == "x = 1\n"
    with pytest.raises(ProjectPathError, match="not found"):
        read_text_file("alice", pid, "old/name.py")


def test_rename_rejects_existing_destination(project_env):
    pid = project_env["project_id"]
    write_text_file("alice", pid, "a.py", "a\n")
    write_text_file("alice", pid, "b.py", "b\n")
    with pytest.raises(ProjectFileError, match="already exists"):
        rename_path("alice", pid, "a.py", "b.py")


def test_delete_non_empty_dir_requires_recursive(project_env):
    pid = project_env["project_id"]
    write_text_file("alice", pid, "pkg/module.py", "pass\n")
    with pytest.raises(ProjectFileError, match="not empty"):
        delete_path("alice", pid, "pkg")
    delete_path("alice", pid, "pkg", recursive=True)
    root_listing = list_directory("alice", pid, ".")
    assert "pkg" not in {e["name"] for e in root_listing["entries"]}


def test_api_rename_and_recursive_delete(project_env, monkeypatch):
    monkeypatch.setattr(project_routes, "get_current_user", lambda request: "alice")
    app = FastAPI()
    app.include_router(project_routes.setup_project_routes())
    client = TestClient(app)
    pid = project_env["project_id"]

    client.put(f"/api/projects/{pid}/file", json={"path": "draft.py", "content": "v1\n"})
    res = client.post(
        f"/api/projects/{pid}/rename",
        json={"src": "draft.py", "dest": "analysis.py"},
    )
    assert res.status_code == 200
    assert res.json()["to"] == "analysis.py"

    client.put(f"/api/projects/{pid}/file", json={"path": "tree/inner.py", "content": "x\n"})
    res = client.delete(
        f"/api/projects/{pid}/file",
        params={"path": "tree", "recursive": True},
    )
    assert res.status_code == 200
    assert res.json()["recursive"] is True

    listing = client.get(f"/api/projects/{pid}/files", params={"path": "."})
    names = {e["name"] for e in listing.json()["entries"]}
    assert "tree" not in names
    assert "analysis.py" in names
