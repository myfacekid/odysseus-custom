"""Tests for portable knowledge graph."""

import json
from unittest.mock import patch

import pytest

from src.knowledge_graph import (
    KnowledgeEdge,
    KnowledgeNode,
    add_graph_link,
    execute_knowledge_tool,
    get_neighbors,
    list_graph_summary,
    load_edges,
    load_manual_edges,
    node_id,
    rebuild_owner_graph,
    remove_graph_link,
    save_graph,
    search_knowledge,
    suggest_graph_link,
    _is_library_document,
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


def test_get_neighbors_resolves_document_ids_with_colons(tmp_path, monkeypatch):
    monkeypatch.setattr("src.knowledge_graph.KNOWLEDGE_ROOT", tmp_path / "knowledge")
    owner = "tester"
    doc_id = "document:vault:Daily Notes/2026-06-01.md"
    task_id = "task:child"
    parent_id = "task:parent"
    nodes = {
        doc_id: KnowledgeNode(
            id=doc_id,
            type="document",
            title="Daily note",
            snippet="Some content",
            meta={"source": "vault", "path": "Daily Notes/2026-06-01.md"},
        ).to_dict(),
        task_id: KnowledgeNode(
            id=task_id,
            type="task",
            title="Linked task",
            snippet="Do the thing",
        ).to_dict(),
        parent_id: KnowledgeNode(
            id=parent_id,
            type="task",
            title="Parent goal",
            snippet="Big picture",
        ).to_dict(),
    }
    edges = [
        KnowledgeEdge(doc_id, task_id, "link").to_dict(),
        KnowledgeEdge(task_id, parent_id, "parent").to_dict(),
    ]
    save_graph(owner, nodes, edges)

    nb = get_neighbors(owner, doc_id)
    assert nb["node"]["id"] == doc_id
    assert any(row.get("node", {}).get("id") == task_id for row in nb["outgoing"])

    nb2 = get_neighbors(owner, "vault:Daily Notes/2026-06-01.md")
    assert nb2["node"]["id"] == doc_id


def test_manual_link_add_remove_and_rebuild_merge(tmp_path, monkeypatch):
    monkeypatch.setattr("src.knowledge_graph.KNOWLEDGE_ROOT", tmp_path / "knowledge")
    owner = "tester"
    nodes = {
        "task:a": KnowledgeNode(id="task:a", type="task", title="Task A", snippet="a").to_dict(),
        "document:doc-1": KnowledgeNode(
            id="document:doc-1",
            type="document",
            title="Lab notes",
            snippet="methods",
            meta={"source": "editor", "document_id": "doc-1"},
        ).to_dict(),
        "document:vault:notes/x.md": KnowledgeNode(
            id="document:vault:notes/x.md",
            type="document",
            title="Vault note",
            snippet="vault",
            meta={"source": "vault", "path": "notes/x.md"},
        ).to_dict(),
    }
    edges = [KnowledgeEdge("task:a", "task:b", "parent").to_dict()]
    save_graph(owner, nodes, edges)

    result = add_graph_link(owner, "task:a", "document:doc-1", kind="related")
    assert result["ok"] is True
    assert load_manual_edges(owner)
    nb = get_neighbors(owner, "task:a")
    assert any(row["node"]["id"] == "document:doc-1" for row in nb["outgoing"])

    removed = remove_graph_link(owner, "task:a", "document:doc-1", kind="related")
    assert removed["ok"] is True
    nb2 = get_neighbors(owner, "task:a")
    assert not any(row["node"]["id"] == "document:doc-1" for row in nb2["outgoing"])

    add_graph_link(owner, "task:a", "document:doc-1", kind="link")
    assert load_manual_edges(owner)
    merged = load_edges(owner)
    assert any(e["from"] == "task:a" and e["to"] == "document:doc-1" for e in merged)


def test_manual_edge_reason_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr("src.knowledge_graph.KNOWLEDGE_ROOT", tmp_path / "knowledge")
    owner = "tester"
    nodes = {
        "paper:A": {"id": "paper:A", "type": "paper", "title": "A", "snippet": "s", "meta": {}},
        "paper:B": {"id": "paper:B", "type": "paper", "title": "B", "snippet": "s", "meta": {}},
    }
    save_graph(owner, nodes, [])

    result = add_graph_link(
        owner,
        "paper:A",
        "paper:B",
        kind="derives_from",
        reason="B extends methods from A",
        source="agent",
    )
    assert result["ok"] is True
    assert result["kind"] == "derives_from"

    manual = load_manual_edges(owner)
    edge = next(e for e in manual if e["to"] == "paper:B")
    assert edge["kind"] == "derives_from"
    assert edge["reason"] == "B extends methods from A"

    synced = load_edges(owner)
    merged_edge = next(e for e in synced if e["to"] == "paper:B")
    assert merged_edge["reason"] == "B extends methods from A"


def test_document_filter_matches_library_only(tmp_path, monkeypatch):
    monkeypatch.setattr("src.knowledge_graph.KNOWLEDGE_ROOT", tmp_path / "knowledge")
    owner = "tester"
    nodes = {
        "document:editor-1": KnowledgeNode(
            id="document:editor-1",
            type="document",
            title="Editor doc",
            snippet="body",
            meta={"source": "editor", "document_id": "editor-1"},
        ).to_dict(),
        "document:vault:readme.md": KnowledgeNode(
            id="document:vault:readme.md",
            type="document",
            title="Readme",
            snippet="vault",
            meta={"source": "vault", "path": "readme.md"},
        ).to_dict(),
    }
    save_graph(owner, nodes, [])

    assert _is_library_document(nodes["document:editor-1"]) is True
    assert _is_library_document(nodes["document:vault:readme.md"]) is False

    summary = list_graph_summary(owner, type_filter="document", limit=50)
    ids = {n["id"] for n in summary["nodes"]}
    assert "document:editor-1" in ids
    assert "document:vault:readme.md" not in ids


def test_suggest_graph_link_without_writing(tmp_path, monkeypatch):
    monkeypatch.setattr("src.knowledge_graph.KNOWLEDGE_ROOT", tmp_path / "knowledge")
    owner = "tester"
    nodes = {
        "document:a": KnowledgeNode(
            id="document:a",
            type="document",
            title="Methods",
            snippet="protocol",
            meta={"source": "editor", "document_id": "a"},
        ).to_dict(),
        "document:b": KnowledgeNode(
            id="document:b",
            type="document",
            title="Results",
            snippet="data",
            meta={"source": "editor", "document_id": "b"},
        ).to_dict(),
    }
    save_graph(owner, nodes, [])

    suggestion = suggest_graph_link(
        owner,
        "document:a",
        "document:b",
        kind="related",
        reason="Same experiment",
    )
    assert suggestion["ok"] is True
    assert suggestion["action"] == "suggest_link"
    assert not load_manual_edges(owner)

    tool_out = execute_knowledge_tool(
        {
            "action": "suggest_link",
            "from": "document:a",
            "to": "document:b",
            "reason": "Same experiment",
        },
        owner=owner,
    )
    assert tool_out["exit_code"] == 0
    assert tool_out.get("action") == "suggest_link"


def test_paper_nodes_indexed_from_catalog(tmp_path, monkeypatch):
    monkeypatch.setattr("src.knowledge_graph.KNOWLEDGE_ROOT", tmp_path / "knowledge")
    monkeypatch.setattr("src.zotero_catalog.ZOTERO_ROOT", tmp_path / "zotero")
    owner = "tester"
    zdir = tmp_path / "zotero" / "users" / owner
    zdir.mkdir(parents=True)
    (zdir / "catalog.jsonl").write_text(
        json.dumps({
            "zotero_key": "PAPER1",
            "title": "Attention Is All You Need",
            "authors": "Vaswani",
            "year": "2017",
            "abstract": "Transformers.",
            "collection_keys": ["COL1"],
            "collection_paths": ["Reading"],
            "item_type": "journalArticle",
            "doi": "",
            "url": "https://example.test/paper",
        }) + "\n",
        encoding="utf-8",
    )
    (zdir / "collections.json").write_text(
        json.dumps([{"key": "COL1", "path": "Reading", "name": "Reading", "parent": ""}]),
        encoding="utf-8",
    )

    with patch("src.knowledge_graph.OBSIDIAN_INTEGRATION_ENABLED", False):
        stats = rebuild_owner_graph(owner)

    assert stats["ok"] is True
    summary = list_graph_summary(owner, type_filter="paper", limit=50)
    ids = {n["id"] for n in summary["nodes"]}
    assert "paper:PAPER1" in ids

    content = execute_knowledge_tool({"action": "read", "id": "paper:PAPER1"}, owner=owner)
    assert content["exit_code"] == 0
    assert "Attention Is All You Need" in content["output"]
    assert "Transformers." in content["output"]
    assert "PDF extraction skipped" in content["output"]

    with patch(
        "src.zotero_client.fetch_paper_pdf_text",
        return_value=("Full paper body from PDF.", ""),
    ):
        content_pdf = execute_knowledge_tool(
            {"action": "read", "id": "paper:PAPER1", "include_pdf": True},
            owner=owner,
        )
    assert "Full paper body from PDF." in content_pdf["output"]
    assert "PDF text (from your Zotero library)" in content_pdf["output"]


def test_search_expand_hops_includes_edge_kinds(tmp_path, monkeypatch):
    monkeypatch.setattr("src.knowledge_graph.KNOWLEDGE_ROOT", tmp_path / "knowledge")
    owner = "tester"
    a = "document:a"
    b = "document:b"
    save_graph(owner, {
        a: {"id": a, "type": "document", "title": "Methods", "snippet": "m", "meta": {}},
        b: {"id": b, "type": "document", "title": "Results", "snippet": "r", "meta": {}},
    }, [])
    add_graph_link(
        owner,
        a,
        b,
        kind="derives_from",
        reason="Results extend methods",
    )
    from src.knowledge_graph import search_knowledge

    result = search_knowledge(owner, "Methods", expand_hops=1, limit=5)
    links = result.get("expanded_links") or []
    assert any(l.get("kind") == "derives_from" for l in links)
    assert any(l.get("reason") == "Results extend methods" for l in links)
