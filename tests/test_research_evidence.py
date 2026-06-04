"""Phase 0 — evidence registry, synthesis selection, citation validation."""

from src.research_evidence import (
    EvidenceRegistry,
    extract_citation_nums,
    source_id_for_finding,
    split_references_section,
)
from src.deep_research import DeepResearcher


def _web_finding(url: str, title: str, **extra):
    return {"url": url, "title": title, "summary": f"Summary of {title}", **extra}


def _zotero_finding(key: str, title: str, **extra):
    return {
        "url": f"https://doi.org/10.1234/{key.lower()}",
        "title": title,
        "summary": f"Zotero summary {title}",
        "zotero_key": key,
        "source_type": "zotero",
        **extra,
    }


def test_source_id_is_stable_for_same_url():
    f1 = _web_finding("https://Example.com/paper/", "Paper A")
    f2 = _web_finding("https://example.com/paper", "Paper A")
    assert source_id_for_finding(f1) == source_id_for_finding(f2)


def test_source_id_uses_zotero_key():
    f = _zotero_finding("ABCD1234", "Seed paper")
    assert source_id_for_finding(f) == "src:zotero:ABCD1234"


def test_registry_assigns_stable_citation_numbers():
    reg = EvidenceRegistry()
    f1 = _web_finding("https://ex.com/a", "Alpha")
    f2 = _web_finding("https://ex.com/b", "Beta")
    n1 = reg.register(f1)
    n2 = reg.register(f2)
    n1_again = reg.register(_web_finding("https://ex.com/a", "Alpha again"))
    assert (n1, n2, n1_again) == (1, 2, 1)
    assert f1["citation_num"] == 1
    assert f1["source_id"].startswith("src:web:")


def test_select_for_synthesis_keeps_seeds_and_recent_window():
    reg = EvidenceRegistry()
    findings = [
        _zotero_finding("SEED1", "Seed one", is_seed=True),
        _web_finding("https://ex.com/1", "One"),
        _web_finding("https://ex.com/2", "Two"),
        _web_finding("https://ex.com/3", "Three"),
        _web_finding("https://ex.com/4", "Four"),
    ]
    reg.sync_findings(findings)
    selected = reg.select_for_synthesis(findings, window=2)
    titles = [f["title"] for f in selected]
    assert "Seed one" in titles
    assert "Three" in titles
    assert "Four" in titles
    assert "One" not in titles


def test_validate_and_repair_report_rebuilds_references():
    reg = EvidenceRegistry()
    reg.register(_web_finding("https://ex.com/a", "Alpha", authors="Smith", year="2024"))
    reg.register(_web_finding("https://ex.com/b", "Beta", authors="Jones", year="2023"))
    report = (
        "## Key Findings\n\n"
        "Alpha matters [1]. Beta too [2]. Also cites missing [99].\n\n"
        "## References\n\n"
        "[1] Wrong reference line\n"
    )
    repaired, warnings = reg.validate_and_repair_report(report)
    assert "[99]" not in repaired
    assert any("invalid" in w.lower() for w in warnings)
    assert "## References" in repaired
    assert "[1]" in repaired and "Alpha" in repaired
    assert "[2]" in repaired and "Beta" in repaired
    assert extract_citation_nums(repaired) <= {1, 2}


def test_structured_fallback_includes_references():
    r = DeepResearcher.__new__(DeepResearcher)
    r.evidence_registry = EvidenceRegistry()
    findings = [
        _web_finding("https://ex.com/a", "Diarization basics"),
        _web_finding("https://ex.com/b", "x-vectors"),
    ]
    report = r._fallback_report("how does speaker diarization work", findings)
    assert "speaker diarization" in report.lower()
    assert "Diarization basics" in report
    assert "x-vectors" in report
    assert "## References" in report
    assert "[1]" in report and "[2]" in report
    assert "No information could be gathered" not in report


def test_split_references_section():
    body, refs = split_references_section("## Intro\n\nBody\n\n## References\n\n[1] Foo")
    assert "Body" in body
    assert refs.startswith("## References")
