"""Phase E1 — optional project_id on research start + persisted in JSON."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from routes.research_routes import setup_research_routes
from src.project_workspace import create_project


@pytest.fixture
def research_project_env(tmp_path, monkeypatch):
    monkeypatch.setattr("src.project_workspace.PROJECTS_ROOT", tmp_path / "projects")
    monkeypatch.setattr("src.project_graph.PROJECTS_ROOT", tmp_path / "projects")
    research_dir = tmp_path / "deep_research"
    research_dir.mkdir(parents=True)
    monkeypatch.setattr("src.research_handler.RESEARCH_DATA_DIR", research_dir)

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    create_project(
        "alice",
        title="Research link project",
        working_dir=str(workspace),
        project_id="proj-e1",
    )
    return {"research_dir": research_dir}


def _route(router, path: str, method: str):
    for route in router.routes:
        if getattr(route, "path", None) == path and method in getattr(route, "methods", set()):
            return route.endpoint
    raise AssertionError(f"Route not found: {method} {path}")


def test_research_start_route_passes_project_id(research_project_env, monkeypatch):
    captured = {}
    handler = MagicMock()

    def _start_research(**kwargs):
        captured.update(kwargs)
        return {"status": "running"}

    handler.start_research.side_effect = _start_research
    monkeypatch.setattr("routes.research_routes.resolve_endpoint", lambda *a, **k: ("http://ep", "m", {}))
    monkeypatch.setattr("src.auth_helpers.require_privilege", lambda req, priv: "alice")

    router = setup_research_routes(handler)
    start_route = _route(router, "/api/research/start", "POST")
    req = SimpleNamespace(state=SimpleNamespace(), headers={})
    body = SimpleNamespace(
        query="Compare fibril structures",
        max_rounds=0,
        search_provider=None,
        endpoint_id=None,
        model=None,
        max_time=300,
        extraction_timeout=None,
        extraction_concurrency=None,
        include_preprints=True,
        include_zotero=True,
        include_knowledge=True,
        seed_papers=["ABC12345", "DEF67890"],
        mode="compare",
        report_length="standard",
        category=None,
        project_id="proj-e1",
    )
    result = asyncio.run(start_route(body, req))
    assert result["project_id"] == "proj-e1"
    assert captured["project_id"] == "proj-e1"


def test_research_start_route_rejects_foreign_project(research_project_env, monkeypatch):
    handler = MagicMock()
    monkeypatch.setattr("routes.research_routes.resolve_endpoint", lambda *a, **k: ("http://ep", "m", {}))
    monkeypatch.setattr("src.auth_helpers.require_privilege", lambda req, priv: "bob")

    router = setup_research_routes(handler)
    start_route = _route(router, "/api/research/start", "POST")
    req = SimpleNamespace(state=SimpleNamespace(), headers={})
    body = SimpleNamespace(
        query="Gap analysis",
        max_rounds=0,
        search_provider=None,
        endpoint_id=None,
        model=None,
        max_time=300,
        extraction_timeout=None,
        extraction_concurrency=None,
        include_preprints=True,
        include_zotero=True,
        include_knowledge=True,
        seed_papers=["ABC12345"],
        mode="gap_analysis",
        report_length="standard",
        category=None,
        project_id="proj-e1",
    )
    with pytest.raises(HTTPException) as exc:
        asyncio.run(start_route(body, req))
    assert exc.value.status_code == 404


def test_research_save_json_includes_project_id(research_project_env):
    from src.research_handler import ResearchHandler

    handler = ResearchHandler()
    session_id = "rp-testsave01"
    entry = {
        "query": "Test",
        "status": "done",
        "result": "Report body",
        "raw_report": "Report body",
        "started_at": 1.0,
        "owner": "alice",
        "project_id": "proj-e1",
        "research_mode": "compare",
        "report_length": "standard",
        "seed_papers": [],
        "include_preprints": True,
        "include_zotero": True,
        "include_knowledge": True,
        "sources": [],
        "stats": {},
    }
    handler._save_result(session_id, entry)
    path = research_project_env["research_dir"] / f"{session_id}.json"
    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["project_id"] == "proj-e1"


def test_ensure_graph_node_for_link_upserts_research(tmp_path, monkeypatch):
    from src.knowledge_graph import get_node, node_id
    from src.project_graph import ensure_graph_node_for_link

    research_dir = tmp_path / "deep_research"
    research_dir.mkdir()
    monkeypatch.setattr("src.research_handler.RESEARCH_DATA_DIR", research_dir)
    monkeypatch.setattr("src.knowledge_graph.KNOWLEDGE_ROOT", tmp_path / "knowledge")

    sid = "rp-upsert01"
    (research_dir / f"{sid}.json").write_text(
        json.dumps(
            {
                "owner": "alice",
                "query": "Compare A vs B",
                "research_mode": "compare",
                "status": "done",
            }
        ),
        encoding="utf-8",
    )
    rid = node_id("research", sid)
    assert get_node("alice", rid) is None
    ensure_graph_node_for_link("alice", rid)
    node = get_node("alice", rid)
    assert node is not None
    assert node.get("type") == "research"
    assert "Compare" in (node.get("title") or "")
