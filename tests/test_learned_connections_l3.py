"""L3 tests — shared proposals, project filter, owner isolation."""

import json

import pytest

from src.graph_merge import preview_merge_proposals
from src.graph_proposals import coerce_graph_proposal, coerce_pending_proposal
from src.pending_graph_edges import (
    enqueue_proposals,
    filter_pending_for_project,
    load_pending_edges,
)
from src.project_graph import project_node_id


def test_coerce_graph_proposal_shared_fields():
    row = coerce_graph_proposal({
        "from": "paper:A",
        "to": "paper:B",
        "kind": "supports",
        "reason": "Same benchmark",
        "evidence": "Both report accuracy gains",
        "section_ref": "methods",
        "project_id": "proj-1",
    })
    assert row["from"] == "paper:A"
    assert row["evidence"] == "Both report accuracy gains"
    assert row["section_ref"] == "methods"
    assert row["project_id"] == "proj-1"


def test_coerce_pending_adds_status():
    row = coerce_pending_proposal({"from": "paper:A", "to": "paper:B", "kind": "relates"})
    assert row["id"]
    assert row["status"] == "pending"
    assert row["created_at"]


def test_filter_pending_for_project(tmp_path, monkeypatch):
    from src import knowledge_graph as kg

    owner = "tester"
    monkeypatch.setattr(kg, "KNOWLEDGE_ROOT", tmp_path / "knowledge")
    proj_id = "proj-alpha"
    pid = project_node_id(proj_id)
    paper = kg.node_id("paper", "P1")
    other = kg.node_id("paper", "P2")
    kg.save_graph(owner, {
        pid: {"id": pid, "type": "project", "title": "Alpha", "snippet": "s", "meta": {"project_id": proj_id}},
        paper: {"id": paper, "type": "paper", "title": "P1", "snippet": "s", "meta": {}},
        other: {"id": other, "type": "paper", "title": "P2", "snippet": "s", "meta": {}},
    }, [
        {"from": pid, "to": paper, "kind": "relates", "source": "manual"},
    ])

    enqueue_proposals(owner, [
        {"from": pid, "to": paper, "kind": "supports", "reason": "in neighborhood"},
        {"from": other, "to": paper, "kind": "relates", "reason": "unrelated"},
        {"from": "paper:X", "to": "paper:Y", "kind": "relates", "reason": "tagged", "project_id": proj_id},
    ], source="research")

    pending = load_pending_edges(owner)
    filtered = filter_pending_for_project(owner, proj_id, pending)
    reasons = {p.get("reason") for p in filtered}
    assert "in neighborhood" in reasons
    assert "tagged" in reasons
    assert "unrelated" not in reasons


def test_pending_api_owner_isolation(tmp_path, monkeypatch):
    """Pending rows are scoped per owner on the knowledge API."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from routes import knowledge_routes

    monkeypatch.setattr("src.knowledge_graph.KNOWLEDGE_ROOT", tmp_path / "knowledge")
    owner_a = "alice"
    owner_b = "bob"
    enqueue_proposals(owner_a, [
        {"from": "paper:A", "to": "paper:B", "kind": "relates", "reason": "secret"},
    ], source="agent")

    app = FastAPI()
    app.include_router(knowledge_routes.setup_knowledge_routes())
    current = {"user": owner_a}
    monkeypatch.setattr("routes.knowledge_routes.get_current_user", lambda request: current["user"])
    client = TestClient(app)

    res_a = client.get("/api/knowledge/pending")
    assert res_a.status_code == 200
    assert len(res_a.json().get("rows") or []) == 1

    current["user"] = owner_b
    res_b = client.get("/api/knowledge/pending")
    assert res_b.status_code == 200
    assert len(res_b.json().get("rows") or []) == 0


def test_merge_preview_does_not_cross_owners(tmp_path, monkeypatch):
    from src import knowledge_graph as kg

    monkeypatch.setattr(kg, "KNOWLEDGE_ROOT", tmp_path / "knowledge")
    owner_a = "user-a"
    owner_b = "user-b"
    for owner, key in ((owner_a, "A"), (owner_b, "B")):
        pid = kg.node_id("paper", key)
        kg.save_graph(owner, {
            pid: {"id": pid, "type": "paper", "title": key, "snippet": "s", "meta": {}},
        }, [])

    preview = preview_merge_proposals(owner_b, [
        {"from": "paper:A", "to": "paper:B", "kind": "relates", "reason": "cross"},
    ])
    row = preview["rows"][0]
    assert row["status"] == "missing_node"
