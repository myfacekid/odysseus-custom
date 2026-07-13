"""Tests for LDR collector → EvidenceRegistry mapping."""

from src.research.ldr_collector_mapper import (
    compile_gathering_draft,
    finding_passes_ingest_policy,
    ingest_ldr_links,
    is_preprint_url,
    ldr_link_to_finding,
)
from src.research_evidence import EvidenceRegistry


def test_is_preprint_url_detects_arxiv():
    assert is_preprint_url("https://arxiv.org/abs/2301.00001")
    assert not is_preprint_url("https://doi.org/10.1038/nature12345")


def test_ldr_link_to_finding_maps_fields():
    finding = ldr_link_to_finding(
        {
            "title": "Foldseek paper",
            "link": "https://doi.org/10.1234/fold",
            "snippet": "Structure search method",
            "source_engine": "openalex",
        },
        engine_name="openalex",
    )
    assert finding["title"] == "Foldseek paper"
    assert finding["url"] == "https://doi.org/10.1234/fold"
    assert finding["search_provider"] == "openalex"


def test_finding_passes_ingest_policy_rejects_preprints_when_off():
    finding = {"title": "Preprint", "url": "https://arxiv.org/abs/1", "content": "x"}
    assert not finding_passes_ingest_policy(finding, include_preprints=False)
    assert finding_passes_ingest_policy(finding, include_preprints=True)


def test_finding_passes_ingest_policy_avoid_topics():
    finding = {
        "title": "FuseGO gene ontology prediction",
        "url": "https://example.com/a",
        "content": "GO function",
    }
    assert not finding_passes_ingest_policy(
        finding,
        include_preprints=True,
        avoid_topics=["gene ontology"],
    )


def test_ingest_ldr_links_registers_accepted_only():
    registry = EvidenceRegistry()
    accepted = ingest_ldr_links(
        registry,
        [
            {"title": "Good", "link": "https://doi.org/10.1/a", "snippet": "ok"},
            {"title": "Bad GO", "link": "https://doi.org/10.1/b", "snippet": "gene ontology"},
        ],
        include_preprints=True,
        avoid_topics=["gene ontology"],
    )
    assert len(accepted) == 1
    assert len(registry) == 1


def test_ldr_link_to_finding_coerces_list_snippet():
    finding = ldr_link_to_finding(
        {
            "title": "Foldseek",
            "link": "https://doi.org/10.1/x",
            "snippet": ["line one", "line two"],
        }
    )
    assert "line one" in finding["content"]
    assert "line two" in finding["content"]


def test_compile_gathering_draft_includes_citation_numbers():
    registry = EvidenceRegistry()
    registry.register(
        {"title": "Paper A", "url": "https://doi.org/10.1/a", "content": "Finding text"},
    )
    draft = compile_gathering_draft(registry)
    assert "[1]" in draft
    assert "Paper A" in draft


def test_ingest_ldr_links_dedupes_by_doi_keeps_richer():
    registry = EvidenceRegistry()
    accepted = ingest_ldr_links(
        registry,
        [
            {"title": "Short", "link": "https://pubmed/1", "doi": "10.1234/same", "snippet": "brief"},
            {
                "title": "Long",
                "link": "https://doi.org/10.1234/same",
                "snippet": "much longer abstract text " * 5,
            },
            {"title": "C", "link": "https://example.com/c", "snippet": "no doi"},
        ],
    )
    assert len(registry) == 2
    assert len(accepted) == 2
    doi_finding = next(f for f in accepted if (f.get("doi_or_id") or "").startswith("10.1234"))
    assert "longer" in (doi_finding.get("content") or "").lower()


def test_ingest_rejects_duplicate_doi():
    registry = EvidenceRegistry()
    ingest_ldr_links(
        registry,
        [{"title": "A", "link": "https://doi.org/10.1234/a", "snippet": "one"}],
    )
    rejected = []
    ingest_ldr_links(
        registry,
        [{"title": "B", "link": "https://openalex.org/w/1", "doi": "10.1234/a", "snippet": "two"}],
        on_reject=lambda f, r: rejected.append(r),
    )
    assert len(registry) == 1
    assert "duplicate_doi" in rejected
