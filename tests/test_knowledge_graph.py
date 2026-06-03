"""Tests for portable knowledge graph."""

import json
from unittest.mock import patch

import pytest

from src.knowledge_graph import (
    KnowledgeEdge,
    KnowledgeNode,
    execute_knowledge_tool,
    node_id,
    rebuild_owner_graph,
    save_graph,
    search_knowledge,
    _owner_dir,
)


def test_node_id_format():
    assert node_id("task", "abc-123") == "task:abc-123"
    assert node_id("document", "doc:abc-123") == "document:abc-123"


def test_save_and_search_graph(tmp_path, monkeypatch):
    monkeypatch.setattr("src.knowledge_graph.KNOWLEDGE_ROOT", tmp_path / "knowledge")
    owner = "tester"
    nodes = {
        "task:a": KnowledgeNode(
            id="task:a",
            type="task",
            title="Finish lab notes",
            snippet="due epistasis project",
            meta={"horizon": "focus"},
        ).to_dict(),
        "task:b": KnowledgeNode(
            id="task:b",
            type="task",
            title="Q2 research aims",
            snippet="build horizon goal",
            meta={"horizon": "build"},
        ).to_dict(),
    }
    edges = [
        KnowledgeEdge("task:a", "task:b", "parent").to_dict(),
    ]
    save_graph(owner, nodes, edges)

    owner_dir = _owner_dir(owner)
    assert (owner_dir / "nodes.jsonl").is_file()
    assert (owner_dir / "edges.jsonl").is_file()
    manifest = json.loads((owner_dir / "manifest.json").read_text())
    assert manifest["node_count"] == 2
    assert manifest["edge_count"] == 1

    result = search_knowledge(owner, "epistasis", expand_hops=1)
    assert result["hits"]
    assert result["hits"][0]["id"] == "task:a"


def test_execute_knowledge_search():
    with patch("src.knowledge_graph.search_knowledge") as mock_search:
        mock_search.return_value = {
            "hits": [{"id": "task:x", "type": "task", "title": "Demo", "snippet": "s", "meta": {}}],
            "neighbors": [],
            "total_nodes": 1,
        }
        out = execute_knowledge_tool({"action": "search", "query": "demo"}, owner="u")
        assert out["exit_code"] == 0
        assert "Demo" in out["output"]


def test_rebuild_from_one_thing_db(tmp_path, monkeypatch):
    monkeypatch.setattr("src.knowledge_graph.KNOWLEDGE_ROOT", tmp_path / "knowledge")

    class FakeTask:
        def __init__(self, tid, text, horizon, parent_ids=None):
            self.id = tid
            self.text = text
            self.horizon = horizon
            self.priority = "steady"
            self.done = False
            self.due_date = None
            self.parent_ids = parent_ids or []

    fake_tasks = [
        FakeTask("child", "Child task", "focus", ["parent"]),
        FakeTask("parent", "Parent goal", "build"),
    ]

    with patch("src.one_thing.list_tasks", return_value=fake_tasks):
        with patch("core.database.SessionLocal") as mock_session:
            mock_session.return_value.__enter__ = lambda s: s
            mock_session.return_value.__exit__ = lambda *a: None
            with patch("core.database.Document"):
                with patch("core.database.Memory"):
                    with patch("services.memory.skills.SkillsManager") as sm:
                        sm.return_value.load.return_value = []
                        stats = rebuild_owner_graph("tester")

    assert stats["ok"] is True
    assert stats["nodes"] >= 2
    assert stats["edges"] >= 1

    nb = execute_knowledge_tool({"action": "neighbors", "id": "task:child"}, owner="tester")
    assert nb["exit_code"] == 0
    assert "Parent goal" in nb["output"]
