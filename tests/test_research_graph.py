"""Phase 5b — research graph linking and source breakdown."""

import json
from pathlib import Path

import pytest

from src.research_graph import (
    collect_research_link_targets,
    compute_source_breakdown,
    propose_research_graph_links,
    research_node_dict,
    sync_research_graph_links,
)


def test_compute_source_breakdown():
    data = {
        "evidence_registry": {
            "sources": [
                {"source_type": "zotero", "is_seed": True, "citation_num": 1},
                {"source_type": "web", "citation_num": 2},
                {"source_type": "knowledge", "citation_num": 3},
            ]
        }
    }
    br = compute_source_breakdown(data)
    assert br["total"] == 3
    assert br["seeds"] == 1
    assert br["zotero"] == 1
    assert br["web"] == 1
    assert br["graph"] == 1


def test_collect_research_link_targets_prefers_seeds():
    data = {
        "seed_paper_details": [{"zotero_key": "SEED0001"}],
        "seed_papers": ["SEED0002"],
        "evidence_registry": {
            "sources": [
                {"citation_num": 1, "source_id": "src:zotero:SEED0001", "is_seed": True},
                {"citation_num": 2, "source_id": "src:zotero:CITED001"},
            ]
        },
    }
    targets = collect_research_link_targets(data, cap=5)
    assert "paper:SEED0001" in targets
    assert "paper:SEED0002" in targets
    assert "paper:CITED001" in targets


def test_research_node_dict():
    node = research_node_dict("sess-1", {
        "query": "AlphaFold mechanisms",
        "research_mode": "compare",
        "seed_papers": ["A", "B"],
        "source_breakdown": {"total": 4, "web": 2, "zotero": 2, "graph": 0, "seeds": 2},
        "stats": {"Rounds": 3},
    })
    assert node["id"] == "research:sess-1"
    assert node["type"] == "research"
    assert node["meta"]["research_mode"] == "compare"
    assert node["meta"]["seed_count"] == 2


def test_propose_research_graph_links_enqueues_not_manual(tmp_path, monkeypatch):
    from src import knowledge_graph as kg
    from src.pending_graph_edges import load_pending_edges

    owner = "tester"
    owner_dir = tmp_path / "knowledge" / "users" / owner
    owner_dir.mkdir(parents=True)
    monkeypatch.setattr(kg, "KNOWLEDGE_ROOT", tmp_path / "knowledge")

    paper_a = kg.node_id("paper", "AFOLD001")
    paper_b = kg.node_id("paper", "ESMF001")
    kg.save_graph(owner, {
        paper_a: {"id": paper_a, "type": "paper", "title": "AlphaFold", "snippet": "s", "meta": {}},
        paper_b: {"id": paper_b, "type": "paper", "title": "ESMFold", "snippet": "s", "meta": {}},
    }, [])

    fixture = json.loads(
        (Path(__file__).parent / "fixtures" / "research" / "compare_alphafold_esm.json").read_text(
            encoding="utf-8"
        )
    )
    fixture["owner"] = owner
    result = propose_research_graph_links(owner, "fixture-compare-alphafold-esm", fixture)
    assert result["ok"] is True
    assert result["proposal_count"] >= 1

    manual = kg.load_manual_edges(owner)
    assert not any(e.get("from", "").startswith("research:") for e in manual)

    pending = load_pending_edges(owner)
    assert any(p.get("from", "").startswith("research:") for p in pending)
    assert any(p.get("kind") != "relates" or p.get("reason") for p in pending)

    nodes = kg.load_nodes(owner)
    assert "research:fixture-compare-alphafold-esm" in nodes


def test_sync_research_graph_links_alias(tmp_path, monkeypatch):
    from src import knowledge_graph as kg

    owner = "tester"
    monkeypatch.setattr(kg, "KNOWLEDGE_ROOT", tmp_path / "knowledge")
    paper_a = kg.node_id("paper", "AFOLD001")
    kg.save_graph(owner, {
        paper_a: {"id": paper_a, "type": "paper", "title": "AlphaFold", "snippet": "s", "meta": {}},
    }, [])
    fixture = {"query": "q", "research_mode": "literature_review", "seed_papers": ["AFOLD001"]}
    out = sync_research_graph_links(owner, "sess-alias", fixture)
    assert out["ok"] is True
    assert "proposal_count" in out
