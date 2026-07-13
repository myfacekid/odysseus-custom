"""Tests for learned graph connection prefs (L1)."""

from src.learned_link_prefs import (
    auto_approve_links_enabled,
    load_learned_link_prefs,
    producer_enqueue_allowed,
    should_emit_batch_link_proposals,
)
from src.pending_graph_edges import enqueue_proposals, load_pending_edges


def test_load_learned_link_prefs_defaults():
    prefs = load_learned_link_prefs("missing-user")
    assert prefs["auto_learn_links"] is True
    assert prefs["auto_approve_links"] is False
    assert prefs["link_min_confidence"] == 0.85


def test_auto_approve_is_inert_in_v1():
    assert auto_approve_links_enabled("anyone") is False


def test_enqueue_gated_when_auto_learn_off(tmp_path, monkeypatch):
    monkeypatch.setattr("src.knowledge_graph.KNOWLEDGE_ROOT", tmp_path / "knowledge")
    owner = "tester"
    prefs_file = tmp_path / "user_prefs.json"
    prefs_file.write_text('{"_users": {"tester": {"auto_learn_links": false}}}', encoding="utf-8")
    monkeypatch.setattr("routes.prefs_routes.PREFS_FILE", str(prefs_file))

    out = enqueue_proposals(owner, [
        {"from": "paper:A", "to": "paper:B", "kind": "relates", "reason": "test"},
    ], source="compare_papers")
    assert out.get("gated") is True
    assert out["added"] == 0
    assert not load_pending_edges(owner)
    assert producer_enqueue_allowed(owner) is False
    assert should_emit_batch_link_proposals(owner) is False


def test_user_initiated_enqueue_bypasses_gate(tmp_path, monkeypatch):
    monkeypatch.setattr("src.knowledge_graph.KNOWLEDGE_ROOT", tmp_path / "knowledge")
    owner = "tester"
    prefs_file = tmp_path / "user_prefs.json"
    prefs_file.write_text('{"_users": {"tester": {"auto_learn_links": false}}}', encoding="utf-8")
    monkeypatch.setattr("routes.prefs_routes.PREFS_FILE", str(prefs_file))

    out = enqueue_proposals(owner, [
        {"from": "paper:A", "to": "paper:B", "kind": "supports", "reason": "manual save"},
    ], source="agent", user_initiated=True)
    assert out["added"] == 1
    assert len(load_pending_edges(owner)) == 1
