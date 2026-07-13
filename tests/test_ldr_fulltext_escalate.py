"""Tests for LDR full-text escalation ladder (Phase L7)."""

from src.research.ldr_fulltext_escalate import (
    _openalex_abstract,
    escalate_fulltext_by_doi,
    fetch_openalex_by_doi,
    fetch_semantic_scholar_by_doi,
    format_sourcing_summary,
    sourcing_tier_counts,
)
from src.research_evidence import EvidenceRegistry
from src.research_sourcing import SOURCING_TIER_UNSOURCED


def test_openalex_abstract_reconstruction():
    work = {
        "abstract_inverted_index": {
            "Foldseek": [0],
            "enables": [1],
            "fast": [2],
            "structure": [3],
            "search": [4],
        }
    }
    text = _openalex_abstract(work)
    assert "Foldseek" in text
    assert "structure search" in text


def test_fetch_openalex_by_doi_mocked(monkeypatch):
    monkeypatch.setattr(
        "src.research.ldr_fulltext_escalate._http_json",
        lambda url, timeout=20: {
            "abstract_inverted_index": {
                word: [i]
                for i, word in enumerate(
                    "Protein structure alignment methods enable rapid comparison across large "
                    "databases of predicted models using structural alphabets and fast "
                    "sequence alignment algorithms for remote homology detection".split()
                )
            },
            "open_access": {"is_oa": True},
            "best_oa_location": {"pdf_url": "https://example.org/paper.pdf"},
            "id": "https://openalex.org/W1",
        },
    )
    out = fetch_openalex_by_doi("10.1038/s41587-023-01773-0")
    assert out.get("pdf_url") == "https://example.org/paper.pdf"
    assert _openalex_abstract(
        {
            "abstract_inverted_index": {
                word: [i]
                for i, word in enumerate(
                    "Protein structure alignment methods enable rapid comparison across large "
                    "databases of predicted models using structural alphabets".split()
                )
            }
        }
    )


def test_fetch_semantic_scholar_by_doi_mocked(monkeypatch):
    monkeypatch.setattr(
        "src.research.ldr_fulltext_escalate._http_json",
        lambda url, timeout=20: {
            "abstract": "Foldseek converts protein structures to a 3Di alphabet for fast alignment. " * 8,
            "openAccessPdf": {"url": "https://example.org/oa.pdf"},
            "paperId": "abc123",
        },
    )
    out = fetch_semantic_scholar_by_doi("10.1038/s41587-023-01773-0")
    assert len(out.get("abstract", "")) > 200
    assert out.get("pdf_url") == "https://example.org/oa.pdf"


def test_escalate_fulltext_prefers_oa_pdf(monkeypatch):
    monkeypatch.setattr(
        "src.research_paper_fetch.resolve_paper_content_by_doi",
        lambda doi, title="", fetch_fulltext=True: {
            "abstract": "Short abstract from pubmed.",
        },
    )
    monkeypatch.setattr(
        "src.research.ldr_fulltext_escalate.fetch_openalex_by_doi",
        lambda doi: {"pdf_url": "https://example.org/foldseek.pdf"},
    )
    monkeypatch.setattr(
        "src.research.ldr_fulltext_escalate.fetch_semantic_scholar_by_doi",
        lambda doi: {},
    )
    monkeypatch.setattr(
        "src.research.ldr_fulltext_escalate.fetch_preprint_fulltext",
        lambda doi, title="", max_chars=50000: {},
    )
    monkeypatch.setattr(
        "src.research.ldr_fulltext_escalate.fetch_pdf_text_from_url",
        lambda url, max_chars=50000: "Full paper body about Foldseek and 3Di structural alphabet. " * 40,
    )

    out = escalate_fulltext_by_doi(
        "10.1038/s41587-023-01773-0",
        title="Foldseek",
        fetch_fulltext=True,
    )
    assert out.get("fulltext")
    assert len(out["fulltext"]) > 900
    assert out.get("source", "").endswith("pdf")


def test_sourcing_tier_counts():
    registry = EvidenceRegistry()
    registry.register(
        {
            "title": "Rich",
            "url": "https://a",
            "evidence": "x" * 1200,
        }
    )
    registry.register(
        {
            "title": "Thin",
            "url": "https://b",
            "content": "title only",
        }
    )
    findings = [
        {
            "citation_num": 1,
            "source_id": registry.sources()[0].source_id,
            "evidence": "x" * 1200,
        },
        {
            "citation_num": 2,
            "source_id": registry.sources()[1].source_id,
            "content": "title only",
        },
    ]
    counts = sourcing_tier_counts(registry, findings)
    assert counts.get(SOURCING_TIER_UNSOURCED, 0) >= 1
    summary = format_sourcing_summary(registry, findings)
    assert "sourcing:" in summary
