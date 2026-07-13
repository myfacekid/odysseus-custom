"""Tests for learned connection proposals (Brain inbox)."""

from src.knowledge_graph import add_graph_link, load_manual_edges, save_graph
from src.pending_graph_edges import (
    accept_pending_edge,
    accept_proposals,
    enqueue_proposals,
    load_pending_edges,
    reject_proposal,
)


def _seed_papers(tmp_path, monkeypatch, owner="tester"):
    monkeypatch.setattr("src.knowledge_graph.KNOWLEDGE_ROOT", tmp_path / "knowledge")
    nodes = {
        "paper:A": {"id": "paper:A", "type": "paper", "title": "Paper A", "snippet": "s", "meta": {}},
        "paper:B": {"id": "paper:B", "type": "paper", "title": "Paper B", "snippet": "s", "meta": {}},
    }
    save_graph(owner, nodes, [])
    return owner


def test_enqueue_and_accept_pending(tmp_path, monkeypatch):
    owner = _seed_papers(tmp_path, monkeypatch)
    out = enqueue_proposals(owner, [
        {"from": "paper:A", "to": "paper:B", "kind": "supports", "reason": "Same benchmark"},
    ], source="compare_papers")
    assert out["ok"] is True
    assert out["added"] == 1
    pending = load_pending_edges(owner)
    assert len(pending) == 1
    assert pending[0]["source"] == "compare_papers"

    result = accept_pending_edge(owner, pending[0]["id"])
    assert result["ok"] is True
    assert not load_pending_edges(owner)
    manual = load_manual_edges(owner)
    assert any(e["from"] == "paper:A" and e["to"] == "paper:B" for e in manual)


def test_enqueue_skips_duplicate_pending(tmp_path, monkeypatch):
    owner = _seed_papers(tmp_path, monkeypatch)
    prop = {"from": "paper:A", "to": "paper:B", "kind": "relates", "reason": "r1"}
    enqueue_proposals(owner, [prop], source="agent")
    out = enqueue_proposals(owner, [prop], source="agent")
    assert out["added"] == 0
    assert out["skipped"] == 1
    assert len(load_pending_edges(owner)) == 1


def test_reject_records_key_and_removes_pending(tmp_path, monkeypatch):
    owner = _seed_papers(tmp_path, monkeypatch)
    prop = {"from": "paper:A", "to": "paper:B", "kind": "refutes", "reason": "Conflict"}
    enqueue_proposals(owner, [prop], source="agent")
    reject_proposal(owner, prop)
    assert not load_pending_edges(owner)
    out = enqueue_proposals(owner, [prop], source="agent")
    assert out["added"] == 0


def test_accept_summarizes_pending_uses_pipeline_edge(tmp_path, monkeypatch):
    from src import knowledge_graph as kg
    from src.paper_summaries import PAPER_SUMMARY_EDGE_KIND, PAPER_SUMMARY_EDGE_SOURCE

    owner = _seed_papers(tmp_path, monkeypatch)
    doc_id = kg.node_id("document", "doc-1")
    nodes = kg.load_nodes(owner)
    nodes[doc_id] = {"id": doc_id, "type": "document", "title": "Summary", "snippet": "s", "meta": {}}
    kg.save_graph(owner, nodes, [])

    out = enqueue_proposals(owner, [{
        "from": "paper:A",
        "to": doc_id,
        "kind": PAPER_SUMMARY_EDGE_KIND,
        "source": PAPER_SUMMARY_EDGE_SOURCE,
        "generated_at": "2026-06-08T12:00:00+00:00",
        "research_session_id": "sess-1",
        "zotero_key": "A",
    }], source="research")
    assert out["added"] == 1
    pending = load_pending_edges(owner)
    result = accept_pending_edge(owner, pending[0]["id"])
    assert result["ok"] is True
    manual = load_manual_edges(owner)
    edge = next(e for e in manual if e.get("kind") == PAPER_SUMMARY_EDGE_KIND)
    assert edge["from"] == "paper:A"
    assert edge["to"] == doc_id
    assert edge["zotero_key"] == "A"


def test_accept_batch_skips_existing_manual(tmp_path, monkeypatch):
    owner = _seed_papers(tmp_path, monkeypatch)
    add_graph_link(owner, "paper:A", "paper:B", kind="relates", reason="Existing")
    result = accept_proposals(owner, [
        {"from": "paper:A", "to": "paper:B", "kind": "supports", "reason": "New"},
        {"from": "paper:B", "to": "paper:A", "kind": "relates", "reason": "Reverse"},
    ])
    assert result["applied"] >= 1
    manual = load_manual_edges(owner)
    kinds = {(e["from"], e["to"], e["kind"]) for e in manual}
    assert ("paper:B", "paper:A", "relates") in kinds


def test_accept_batch_runs_merge_preview(tmp_path, monkeypatch):
    owner = _seed_papers(tmp_path, monkeypatch)
    enqueue_proposals(owner, [
        {"from": "paper:A", "to": "paper:B", "kind": "supports", "reason": "One"},
        {"from": "paper:B", "to": "paper:A", "kind": "relates", "reason": "Two"},
    ], source="agent")
    pending = load_pending_edges(owner)
    result = accept_proposals(owner, pending)
    assert result["ok"] is True
    assert result["applied"] >= 2
    assert not load_pending_edges(owner)
    manual = load_manual_edges(owner)
    assert len(manual) >= 2
