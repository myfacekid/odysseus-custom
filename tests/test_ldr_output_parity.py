"""LDR Phase L3 — session JSON parity, export, visual report, graph hooks."""

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
from src.research.ldr_collector_mapper import ingest_ldr_links, ingest_rejection_reason
from src.visual_report import generate_visual_report

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "research"

# Keys persisted by ResearchHandler._save_result for LDR sessions.
SESSION_JSON_REQUIRED_KEYS = frozenset({
    "session_id",
    "query",
    "status",
    "result",
    "raw_report",
    "sources",
    "raw_findings",
    "evidence_registry",
    "stats",
    "category",
    "include_preprints",
    "include_zotero",
    "include_knowledge",
    "seed_papers",
    "seed_paper_details",
    "source_breakdown",
    "research_mode",
    "report_length",
    "project_id",
    "research_engine",
    "started_at",
    "completed_at",
    "owner",
})


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


def test_ldr_fixture_has_required_session_fields():
    data = _load_fixture("ldr_compare_foldseek.json")
    assert data["research_engine"] == "ldr"
    assert data["stats"]["Engine"] == "LDR LangGraph"
    assert data["include_preprints"] is False


def test_ldr_fixture_source_breakdown_and_graph():
    data = _load_fixture("ldr_compare_foldseek.json")
    br = compute_source_breakdown(data)
    assert br["total"] == 3
    assert br["seeds"] == 2
    targets = collect_research_link_targets(data, cap=10)
    assert "paper:FOLD001" in targets
    assert "paper:ESM3001" in targets
    node = research_node_dict(data["session_id"], data)
    assert node["meta"]["research_mode"] == "compare"
    assert node["meta"]["seed_count"] == 2


def test_ldr_fixture_export_and_visual_report():
    data = _load_fixture("ldr_compare_foldseek.json")
    reg = EvidenceRegistry.from_dict(data["evidence_registry"])
    cited = select_export_sources(reg, data["raw_report"], scope="cited")
    assert [s.citation_num for s in cited] == [1, 2, 3]

    bib = export_bibtex(data, scope="cited")
    assert "Foldseek" in bib or "FOLD001" in bib
    assert "10.1038/s41592-023-02049-6" in bib

    md = export_markdown(data)
    assert "Foldseek" in md or "[1]" in md

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
    assert soup.select_one("#source-3")
    assert soup.select_one('a.cite-link[data-cite="1"]')
    assert "LDR" in html or "Foldseek" in html


def test_ingest_rejection_reason_codes():
    finding = {
        "title": "Arxiv preprint",
        "url": "https://arxiv.org/abs/2301.00001",
        "content": "x",
    }
    assert ingest_rejection_reason(finding, include_preprints=False) == "preprint_excluded"
    assert ingest_rejection_reason(finding, include_preprints=True) is None

    go_finding = {
        "title": "FuseGO",
        "url": "https://doi.org/10.1/go",
        "content": "gene ontology function prediction",
    }
    assert ingest_rejection_reason(go_finding, include_preprints=True, avoid_topics=["gene ontology"]) == "avoid_topic"


def test_ingest_ldr_links_on_reject_callback():
    registry = EvidenceRegistry()
    rejected = []

    ingest_ldr_links(
        registry,
        [
            {"title": "Good", "link": "https://doi.org/10.1/ok", "snippet": "ok"},
            {"title": "Preprint", "link": "https://arxiv.org/abs/1", "snippet": "p"},
        ],
        include_preprints=False,
        on_reject=lambda f, r: rejected.append((f.get("title"), r)),
    )
    assert len(registry) == 1
    assert ("Preprint", "preprint_excluded") in rejected


@pytest.mark.asyncio
async def test_handler_save_result_includes_research_engine(tmp_path, monkeypatch):
    """LDR path persists the expected session JSON shape."""
    monkeypatch.setattr("src.research_handler.RESEARCH_DATA_DIR", tmp_path)
    from src.research_handler import ResearchHandler
    from src.research.ldr_session import LdrResearchSession

    handler = ResearchHandler()
    session = LdrResearchSession(llm_model="test-model", include_preprints=False)
    session.evidence_registry.register(
        {
            "title": "Paper",
            "url": "https://doi.org/10.1/x",
            "content": "body",
        }
    )
    session.findings.append({"title": "Paper", "url": "https://doi.org/10.1/x"})
    session.evolving_report = "## Summary\n\nText [1]."
    session.round_count = 1

    entry = {
        "query": "test query",
        "status": "done",
        "result": "formatted",
        "raw_report": session.evolving_report,
        "researcher": session,
        "stats": session.get_stats(),
        "category": "academic",
        "include_preprints": False,
        "include_zotero": True,
        "include_knowledge": False,
        "seed_papers": [],
        "research_mode": "literature_review",
        "report_length": "standard",
        "research_engine": "ldr",
        "owner": "user-a",
        "started_at": 1.0,
    }
    handler._save_result("sess-ldr-1", entry)

    saved = json.loads((tmp_path / "sess-ldr-1.json").read_text(encoding="utf-8"))
    missing = SESSION_JSON_REQUIRED_KEYS - set(saved.keys())
    assert not missing, f"missing keys: {missing}"
    assert saved["research_engine"] == "ldr"
    assert saved["evidence_registry"]["sources"]
    assert saved["source_breakdown"]["total"] >= 1


@pytest.mark.parametrize("filename", ["compare_alphafold_esm.json", "ldr_compare_foldseek.json"])
def test_research_fixtures_share_breakdown_shape(filename):
    data = _load_fixture(filename)
    br = compute_source_breakdown(data)
    for key in ("web", "zotero", "graph", "seeds", "total"):
        assert key in br
