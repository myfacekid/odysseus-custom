"""L5 — link audit loop for pending learned connections."""

import pytest

from src.knowledge_graph import add_graph_link, save_graph
from src.link_audit import audit_pending_links
from src.pending_graph_edges import enqueue_proposals, load_pending_edges


def _seed_papers(tmp_path, monkeypatch, owner="tester"):
    monkeypatch.setattr("src.knowledge_graph.KNOWLEDGE_ROOT", tmp_path / "knowledge")
    nodes = {
        "paper:A": {"id": "paper:A", "type": "paper", "title": "Paper A", "snippet": "s", "meta": {}},
        "paper:B": {"id": "paper:B", "type": "paper", "title": "Paper B", "snippet": "s", "meta": {}},
    }
    save_graph(owner, nodes, [])
    return owner


def test_audit_flags_missing_node(tmp_path, monkeypatch):
    owner = _seed_papers(tmp_path, monkeypatch)
    enqueue_proposals(owner, [{
        "from": "paper:A",
        "to": "paper:MISSING",
        "kind": "supports",
        "reason": "Should fail audit",
    }], source="agent")

    result = audit_pending_links(owner)
    assert result["ok"] is True
    assert result["audited"] == 1
    assert result["flagged"] == 1

    pending = load_pending_edges(owner)
    assert pending[0]["audit_status"] == "missing_node"
    assert pending[0].get("audit_flagged") is True
    assert any("not in graph" in e.lower() for e in pending[0].get("audit_errors") or [])


def test_audit_flags_stance_conflict(tmp_path, monkeypatch):
    owner = _seed_papers(tmp_path, monkeypatch)
    add_graph_link(owner, "paper:A", "paper:B", kind="supports", reason="Existing support")
    enqueue_proposals(owner, [{
        "from": "paper:A",
        "to": "paper:B",
        "kind": "refutes",
        "reason": "Contradicts existing",
    }], source="compare_papers")

    result = audit_pending_links(owner)
    assert result["flagged"] == 1
    pending = load_pending_edges(owner)
    assert pending[0]["audit_status"] == "conflict"


def test_audit_ok_when_ready(tmp_path, monkeypatch):
    owner = _seed_papers(tmp_path, monkeypatch)
    enqueue_proposals(owner, [{
        "from": "paper:A",
        "to": "paper:B",
        "kind": "relates",
        "reason": "Fine link",
    }], source="agent")

    result = audit_pending_links(owner)
    assert result["flagged"] == 0
    pending = load_pending_edges(owner)
    assert pending[0]["audit_status"] == "ok"
    assert pending[0].get("audited_at")


def test_enqueue_fires_link_proposed_with_count(tmp_path, monkeypatch):
    owner = _seed_papers(tmp_path, monkeypatch)
    fired = []

    def _capture(event, owner=None, *, count=1):
        fired.append((event, owner, count))

    monkeypatch.setattr("src.event_bus.fire_event", _capture)

    enqueue_proposals(owner, [
        {"from": "paper:A", "to": "paper:B", "kind": "relates", "reason": "One"},
        {"from": "paper:B", "to": "paper:A", "kind": "relates", "reason": "Two"},
    ], source="agent")

    assert fired == [("link_proposed", owner, 2)]


@pytest.mark.asyncio
async def test_action_audit_links_noop_without_pending(tmp_path, monkeypatch):
    from src.builtin_actions import TaskNoop, action_audit_links

    monkeypatch.setattr("src.knowledge_graph.KNOWLEDGE_ROOT", tmp_path / "knowledge")
    with pytest.raises(TaskNoop):
        await action_audit_links("nobody")
