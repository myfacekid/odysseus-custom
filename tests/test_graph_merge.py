"""Tests for batch graph edge merge (Edge Taxonomy T2)."""

from src.graph_merge import apply_merge_proposals, preview_merge_proposals
from src.knowledge_graph import add_graph_link, load_manual_edges, save_graph


def _seed_papers(tmp_path, monkeypatch, owner="tester"):
    monkeypatch.setattr("src.knowledge_graph.KNOWLEDGE_ROOT", tmp_path / "knowledge")
    nodes = {
        "paper:A": {"id": "paper:A", "type": "paper", "title": "Paper A", "snippet": "s", "meta": {}},
        "paper:B": {"id": "paper:B", "type": "paper", "title": "Paper B", "snippet": "s", "meta": {}},
        "paper:C": {"id": "paper:C", "type": "paper", "title": "Paper C", "snippet": "s", "meta": {}},
    }
    save_graph(owner, nodes, [])
    return owner


def test_preview_flags_supports_refutes_conflict(tmp_path, monkeypatch):
    owner = _seed_papers(tmp_path, monkeypatch)
    add_graph_link(owner, "paper:A", "paper:B", kind="supports", reason="Existing support")

    preview = preview_merge_proposals(owner, [
        {"from": "paper:A", "to": "paper:B", "kind": "refutes", "reason": "New contradiction"},
    ])
    assert preview["ok"] is True
    row = preview["rows"][0]
    assert row["status"] == "conflict"
    assert any("Opposing stance" in e for e in row.get("errors") or [])


def test_preview_duplicate_can_update_reason(tmp_path, monkeypatch):
    owner = _seed_papers(tmp_path, monkeypatch)
    add_graph_link(owner, "paper:A", "paper:B", kind="relates", reason="Old reason")

    preview = preview_merge_proposals(owner, [
        {"from": "paper:A", "to": "paper:B", "kind": "relates", "reason": "Sharper reason"},
    ])
    row = preview["rows"][0]
    assert row["status"] == "duplicate"
    assert row["can_update_reason"] is True


def test_apply_partial_accept_adds_only_selected(tmp_path, monkeypatch):
    owner = _seed_papers(tmp_path, monkeypatch)
    proposals = [
        {"from": "paper:A", "to": "paper:B", "kind": "relates", "reason": "Link AB"},
        {"from": "paper:B", "to": "paper:C", "kind": "supports", "reason": "Link BC"},
    ]
    preview = preview_merge_proposals(owner, proposals)
    rows = preview["rows"]
    accepted = [
        {**rows[0], "selected": True},
        {**rows[1], "selected": False, "skip": True, "action": "skip"},
    ]
    result = apply_merge_proposals(owner, accepted)
    assert result["ok"] is True
    assert result["applied"] == 1
    assert result["skipped"] == 1

    manual = load_manual_edges(owner)
    pairs = {(e["from"], e["to"], e["kind"]) for e in manual}
    assert ("paper:A", "paper:B", "relates") in pairs
    assert ("paper:B", "paper:C", "supports") not in pairs


def test_apply_updates_reason_on_duplicate(tmp_path, monkeypatch):
    owner = _seed_papers(tmp_path, monkeypatch)
    add_graph_link(owner, "paper:A", "paper:B", kind="derives_from", reason="Initial")

    preview = preview_merge_proposals(owner, [
        {"from": "paper:A", "to": "paper:B", "kind": "derives_from", "reason": "Updated lineage"},
    ])
    row = preview["rows"][0]
    result = apply_merge_proposals(owner, [{**row, "action": "update_reason", "selected": True}])
    assert result["ok"] is True
    assert result["updated"] == 1

    manual = load_manual_edges(owner)
    match = [e for e in manual if e["from"] == "paper:A" and e["to"] == "paper:B"]
    assert len(match) == 1
    assert match[0]["reason"] == "Updated lineage"


def test_apply_skips_conflict(tmp_path, monkeypatch):
    owner = _seed_papers(tmp_path, monkeypatch)
    add_graph_link(owner, "paper:A", "paper:B", kind="supports", reason="Existing")

    preview = preview_merge_proposals(owner, [
        {"from": "paper:A", "to": "paper:B", "kind": "refutes", "reason": "Conflict"},
    ])
    row = preview["rows"][0]
    result = apply_merge_proposals(owner, [{**row, "selected": True}])
    assert result["skipped"] == 1
    assert result["applied"] == 0


def test_preview_rejects_over_twenty_proposals(tmp_path, monkeypatch):
    owner = _seed_papers(tmp_path, monkeypatch)
    proposals = [
        {"from": "paper:A", "to": "paper:B", "kind": "relates", "reason": f"r{i}"}
        for i in range(21)
    ]
    preview = preview_merge_proposals(owner, proposals)
    assert preview["ok"] is False
    assert "20" in (preview.get("error") or "")


def test_execute_knowledge_merge_subgraph_preview(tmp_path, monkeypatch):
    owner = _seed_papers(tmp_path, monkeypatch)
    from src.knowledge_graph import execute_knowledge_tool

    out = execute_knowledge_tool(
        {
            "action": "merge_subgraph",
            "phase": "preview",
            "proposals": [{"from": "paper:A", "to": "paper:C", "kind": "relates", "reason": "Related"}],
        },
        owner=owner,
    )
    assert out["exit_code"] == 0
    assert out.get("action") == "merge_subgraph"
    assert "Merge preview" in out.get("output", "")
