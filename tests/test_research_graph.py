"""Phase 5b — research graph linking and source breakdown."""

import json
from pathlib import Path

import pytest

from src.research_graph import (
    collect_research_link_targets,
    compute_source_breakdown,
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


def test_sync_research_graph_links(tmp_path, monkeypatch):
    from src import knowledge_graph as kg

    owner = "tester"
    owner_dir = tmp_path / "knowledge" / "users" / owner
    owner_dir.mkdir(parents=True)
    monkeypatch.setattr(kg, "KNOWLEDGE_ROOT", tmp_path / "knowledge")

    # Seed paper node already in graph
    paper_id = kg.node_id("paper", "PAPER123")
    kg.save_graph(owner, {
        paper_id: {
            "id": paper_id,
            "type": "paper",
            "title": "Attention",
            "snippet": "test",
            "meta": {"zotero_key": "PAPER123"},
        }
    }, [])

    data = {
        "query": "Compare models",
        "research_mode": "compare",
        "seed_paper_details": [{"zotero_key": "PAPER123", "title": "Attention"}],
        "evidence_registry": {"sources": []},
        "owner": owner,
    }
    result = sync_research_graph_links(owner, "rp-test-1", data)
    assert result["ok"] is True
    assert "research:rp-test-1" == result["research_id"]
    assert paper_id in result["linked"]

    manual = kg.load_manual_edges(owner)
    assert any(
        e.get("from") == "research:rp-test-1" and e.get("to") == paper_id
        for e in manual
    )

    node = kg.get_node(owner, "research:rp-test-1")
    assert node and node.get("type") == "research"
