"""Phase 5d — golden research JSON fixtures for CI (no live Zotero)."""

import json
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from src.research_evidence import EvidenceRegistry
from src.research_export import export_bibtex, export_markdown, select_export_sources
from src.research_graph import (
    collect_research_link_targets,
    compute_source_breakdown,
    research_node_dict,
)
from src.visual_report import generate_visual_report

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "research"


def _load_fixture(name: str) -> dict:
    path = FIXTURES_DIR / name
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "filename",
    ["compare_alphafold_esm.json", "literature_review_gap.json", "ldr_compare_foldseek.json"],
)
def test_fixture_source_breakdown(filename):
    data = _load_fixture(filename)
    br = compute_source_breakdown(data)
    registry = data.get("evidence_registry") or {}
    assert br["total"] == len(registry.get("sources") or [])
    assert br["seeds"] >= 1


def test_compare_fixture_graph_links_and_node():
    data = _load_fixture("compare_alphafold_esm.json")
    targets = collect_research_link_targets(data, cap=10)
    assert "paper:AFOLD001" in targets
    assert "paper:ESMF001" in targets

    node = research_node_dict(data["session_id"], data)
    assert node["id"] == "research:fixture-compare-alphafold-esm"
    assert node["meta"]["research_mode"] == "compare"
    assert node["meta"]["seed_count"] == 2


def test_phase5_session_json_fields():
    """Phase 5 acceptance: persisted JSON includes seeds, mode, source breakdown."""
    data = _load_fixture("compare_alphafold_esm.json")
    assert data.get("research_mode") == "compare"
    assert len(data.get("seed_papers") or []) >= 2
    assert len(data.get("seed_paper_details") or []) >= 2
    br = data.get("source_breakdown") or compute_source_breakdown(data)
    assert br.get("total", 0) >= 1
    assert br.get("seeds", 0) >= 1


def test_phase5_graph_edge_targets_include_seeds():
    """Phase 5 acceptance: research session links to seed paper nodes."""
    data = _load_fixture("compare_alphafold_esm.json")
    from src.research_typed_edges import build_research_graph_edges

    edges = build_research_graph_edges(data["session_id"], data)
    assert edges
    seed_edges = [e for e in edges if e.get("from", "").startswith("research:")]
    assert seed_edges
    targets = {e.get("to") for e in seed_edges}
    assert "paper:AFOLD001" in targets
    assert "paper:ESMF001" in targets


def test_compare_fixture_export_and_visual_report():
    data = _load_fixture("compare_alphafold_esm.json")
    reg = EvidenceRegistry.from_dict(data["evidence_registry"])
    cited = select_export_sources(reg, data["raw_report"], scope="cited")
    assert [s.citation_num for s in cited] == [1, 2, 3]

    bib = export_bibtex(data, scope="cited")
    assert "AFOLD001" in bib or "AlphaFold" in bib
    assert "10.1038/s41586-021-03819-2" in bib

    md = export_markdown(data)
    assert "# Compare AlphaFold and ESMFold" in md or "AlphaFold [1]" in md

    html = generate_visual_report(
        data["query"],
        data["raw_report"],
        sources=[],
        stats=data.get("stats") or {},
        session_id=data["session_id"],
        evidence_registry=data["evidence_registry"],
    )
    soup = BeautifulSoup(html, "html.parser")
    assert soup.select_one("#source-1")
    assert soup.select_one("#source-2")
    assert soup.select_one('a.cite-link[data-cite="1"]')
    assert soup.select_one(".sourcing-disclosure")


def test_gap_fixture_thin_seed_tier_disclosure():
    data = _load_fixture("literature_review_gap.json")
    html = generate_visual_report(
        data["query"],
        data["raw_report"],
        sources=[],
        stats=data.get("stats") or {},
        session_id=data["session_id"],
        evidence_registry=data["evidence_registry"],
    )
    assert "abstract only" in html.lower() or "limited" in html.lower()
