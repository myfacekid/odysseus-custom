"""Phase A — project graph nodes and linking."""

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import core.database as cdb
from src.knowledge_graph import get_node, load_nodes, node_id
from src.project_graph import (
    delete_project_node,
    index_project_nodes,
    project_node_id,
    upsert_project_node,
)
from src.project_paths import working_dir_warning
from src.project_workspace import create_project, get_project


@pytest.fixture
def graph_env(tmp_path, monkeypatch):
    monkeypatch.setattr("src.project_workspace.PROJECTS_ROOT", tmp_path / "projects")
    monkeypatch.setattr("src.project_graph.PROJECTS_ROOT", tmp_path / "projects")
    monkeypatch.setattr("src.knowledge_graph.KNOWLEDGE_ROOT", tmp_path / "knowledge")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return {"workspace": workspace, "owner": "alice"}


def test_working_dir_warning_home(monkeypatch):
    import os

    fake_home = "/tmp/fake-home-user"
    monkeypatch.setattr(os.path, "expanduser", lambda p: fake_home if p.startswith("~") else p)
    monkeypatch.setattr(os.path, "realpath", lambda p: os.path.abspath(p))
    assert working_dir_warning(fake_home) is not None


def test_create_project_syncs_graph_node(graph_env):
    project = create_project(
        graph_env["owner"],
        title="AlphaFold",
        working_dir=str(graph_env["workspace"]),
        project_id="proj-graph",
    )
    nid = project_node_id("proj-graph")
    node = get_node(graph_env["owner"], nid)
    assert node is not None
    assert node["type"] == "project"
    assert node["title"] == "AlphaFold"
    assert node["meta"]["project_id"] == "proj-graph"


def test_index_project_nodes_on_rebuild(graph_env):
    create_project(
        graph_env["owner"],
        title="Rebuild me",
        working_dir=str(graph_env["workspace"]),
        project_id="proj-rebuild",
    )
    nodes = {}
    index_project_nodes(graph_env["owner"], nodes)
    assert project_node_id("proj-rebuild") in nodes


def test_project_links_api(graph_env, monkeypatch):
    monkeypatch.setattr("routes.project_routes.get_current_user", lambda request: graph_env["owner"])
    from routes import project_routes

    create_project(
        graph_env["owner"],
        title="Linked",
        working_dir=str(graph_env["workspace"]),
        project_id="proj-links",
    )
    upsert_project_node(
        graph_env["owner"],
        get_project(graph_env["owner"], "proj-links"),
    )
    # Seed a paper node for linking.
    from src.knowledge_graph import save_graph

    paper_id = node_id("paper", "ABCD1234")
    nodes = load_nodes(graph_env["owner"])
    nodes[paper_id] = {
        "id": paper_id,
        "type": "paper",
        "title": "Test paper",
        "snippet": "",
        "updated_at": "",
        "meta": {},
    }
    save_graph(graph_env["owner"], nodes, [])

    app = FastAPI()
    app.include_router(project_routes.setup_project_routes())
    client = TestClient(app)

    res = client.post(
        "/api/projects/proj-links/links",
        json={"to_id": paper_id, "kind": "related"},
    )
    assert res.status_code == 200
    assert res.json().get("ok") is True

    res = client.get("/api/projects/proj-links/links")
    assert res.status_code == 200
    body = res.json()
    assert body.get("node", {}).get("id") == project_node_id("proj-links")
    linked_ids = {row["node"]["id"] for row in body.get("outgoing", []) if row.get("node")}
    assert paper_id in linked_ids

    res = client.delete(
        "/api/projects/proj-links/links",
        params={"to_id": paper_id, "kind": "related"},
    )
    assert res.status_code == 200


def test_cross_owner_project_links_404(graph_env, monkeypatch):
    monkeypatch.setattr("routes.project_routes.get_current_user", lambda request: "bob")
    from routes import project_routes

    create_project(
        "alice",
        title="Alice only",
        working_dir=str(graph_env["workspace"]),
        project_id="proj-private",
    )
    app = FastAPI()
    app.include_router(project_routes.setup_project_routes())
    client = TestClient(app)
    res = client.get("/api/projects/proj-private/links")
    assert res.status_code == 404


def test_archive_removes_graph_node(graph_env):
    create_project(
        graph_env["owner"],
        title="Temporary",
        working_dir=str(graph_env["workspace"]),
        project_id="proj-archive",
    )
    nid = project_node_id("proj-archive")
    assert get_node(graph_env["owner"], nid) is not None

    from src.project_workspace import archive_project

    archive_project(graph_env["owner"], "proj-archive")
    assert get_node(graph_env["owner"], nid) is None
    assert get_project(graph_env["owner"], "proj-archive") is None

    path = graph_env["workspace"].parent / "projects" / "alice" / "proj-archive.json"
    assert path.is_file()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data.get("archived") is True


def test_validate_dir_api_missing(graph_env, monkeypatch):
    monkeypatch.setattr("routes.project_routes.get_current_user", lambda request: graph_env["owner"])
    from routes import project_routes

    app = FastAPI()
    app.include_router(project_routes.setup_project_routes())
    client = TestClient(app)
    res = client.post(
        "/api/projects/validate-dir",
        json={"working_dir": str(graph_env["workspace"].parent / "does-not-exist")},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["working_dir_status"] == "missing"


def test_cross_owner_get_project_404(graph_env, monkeypatch):
    monkeypatch.setattr("routes.project_routes.get_current_user", lambda request: "bob")
    from routes import project_routes

    create_project(
        "alice",
        title="Private",
        working_dir=str(graph_env["workspace"]),
        project_id="proj-get-private",
    )
    app = FastAPI()
    app.include_router(project_routes.setup_project_routes())
    client = TestClient(app)
    assert client.get("/api/projects/proj-get-private").status_code == 404


def test_revalidate_persists_missing_status(graph_env):
    from src.project_workspace import assert_project_owner, ensure_project_status_current

    create_project(
        graph_env["owner"],
        title="Drift",
        working_dir=str(graph_env["workspace"]),
        project_id="proj-drift",
    )
    graph_env["workspace"].rmdir()
    updated = ensure_project_status_current(
        graph_env["owner"],
        assert_project_owner(graph_env["owner"], "proj-drift"),
    )
    assert updated["working_dir_status"] == "missing"
    reloaded = get_project(graph_env["owner"], "proj-drift")
    assert reloaded["working_dir_status"] == "missing"


def test_add_graph_link_refreshes_project_snippet(graph_env):
    from src.knowledge_graph import add_graph_link, get_node, save_graph

    create_project(
        graph_env["owner"],
        title="Snippet",
        working_dir=str(graph_env["workspace"]),
        project_id="proj-snippet",
    )
    paper_id = node_id("paper", "WXYZ9999")
    nodes = load_nodes(graph_env["owner"])
    nodes[paper_id] = {
        "id": paper_id,
        "type": "paper",
        "title": "Paper",
        "snippet": "",
        "updated_at": "",
        "meta": {},
    }
    save_graph(graph_env["owner"], nodes, [])

    pid = project_node_id("proj-snippet")
    before = get_node(graph_env["owner"], pid)
    assert "1 link" not in (before.get("snippet") or "").lower()

    add_graph_link(graph_env["owner"], pid, paper_id, kind="related")
    after = get_node(graph_env["owner"], pid)
    assert "1 link" in (after.get("snippet") or "").lower()


def test_list_projects_when_auth_disabled(graph_env, monkeypatch):
    create_project(
        "",
        title="Visible",
        working_dir=str(graph_env["workspace"]),
        project_id="proj-visible",
    )
    monkeypatch.setattr("routes.project_routes.get_current_user", lambda request: None)
    monkeypatch.setattr("routes.project_routes._auth_disabled", lambda: True)
    from routes import project_routes

    app = FastAPI()
    app.include_router(project_routes.setup_project_routes())
    client = TestClient(app)
    res = client.get("/api/projects")
    assert res.status_code == 200
    ids = [p["id"] for p in res.json().get("projects", [])]
    assert "proj-visible" in ids


def test_browse_dir_api_disabled_by_default(graph_env, monkeypatch):
    monkeypatch.setattr("routes.project_routes.get_current_user", lambda request: graph_env["owner"])
    monkeypatch.setattr("routes.project_routes.SERVER_DIR_BROWSE_ENABLED", False)
    from routes import project_routes

    app = FastAPI()
    app.include_router(project_routes.setup_project_routes())
    client = TestClient(app)
    res = client.get("/api/projects/browse-dir", params={"path": str(graph_env["workspace"])})
    assert res.status_code == 403


def test_browse_dir_api(graph_env, monkeypatch):
    monkeypatch.setattr("routes.project_routes.get_current_user", lambda request: graph_env["owner"])
    monkeypatch.setattr("routes.project_routes.SERVER_DIR_BROWSE_ENABLED", True)
    fake_home = str(graph_env["workspace"].parent)
    monkeypatch.setattr(
        "routes.project_routes.os.path.expanduser",
        lambda p: fake_home if str(p).startswith("~") else p,
    )
    from routes import project_routes

    nested = graph_env["workspace"] / "nested"
    nested.mkdir()
    app = FastAPI()
    app.include_router(project_routes.setup_project_routes())
    client = TestClient(app)
    res = client.get("/api/projects/browse-dir", params={"path": str(graph_env["workspace"])})
    assert res.status_code == 200
    body = res.json()
    assert body["path"] == str(graph_env["workspace"].resolve())
    names = [entry["name"] for entry in body["entries"]]
    assert "nested" in names

    deeper = client.get(
        "/api/projects/browse-dir",
        params={"path": str(nested.resolve())},
    )
    assert deeper.status_code == 200
    assert deeper.json()["path"] == str(nested.resolve())


def test_resolve_dir_api(graph_env, monkeypatch):
    monkeypatch.setattr("routes.project_routes.get_current_user", lambda request: graph_env["owner"])
    fake_home = str(graph_env["workspace"].parent)
    monkeypatch.setattr(
        "routes.project_routes.os.path.expanduser",
        lambda p: fake_home if str(p).startswith("~") else p,
    )
    target = graph_env["workspace"] / "picked"
    target.mkdir()
    from routes import project_routes

    app = FastAPI()
    app.include_router(project_routes.setup_project_routes())
    client = TestClient(app)
    res = client.post("/api/projects/resolve-dir", json={"folder_name": "picked"})
    assert res.status_code == 200
    body = res.json()
    assert body["matches"] == 1
    assert body["path"] == str(target.resolve())
