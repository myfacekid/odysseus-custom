"""Tests for non-DOI URL enrichment (L6)."""

from src.research.ldr_url_enrich import (
    enrich_finding_from_url,
    is_enrichable_scholarly_url,
    scholarly_url_candidates,
)


def test_is_enrichable_scholarly_url():
    assert is_enrichable_scholarly_url("https://arxiv.org/abs/2401.12345")
    assert is_enrichable_scholarly_url("https://www.nature.com/articles/s41587-023-01773-0")
    assert not is_enrichable_scholarly_url("https://doi.org/10.1038/x")
    assert not is_enrichable_scholarly_url("https://scholar.google.com/citations?user=abc")
    assert not is_enrichable_scholarly_url("https://www.google.com/search?q=foldseek")


def test_scholarly_url_candidates_arxiv():
    urls = scholarly_url_candidates("https://arxiv.org/abs/2401.12345v2")
    assert "https://arxiv.org/html/2401.12345" in urls
    assert "https://arxiv.org/pdf/2401.12345.pdf" in urls


def test_enrich_finding_from_url_mocked(monkeypatch):
    finding = {
        "title": "Example arXiv paper",
        "url": "https://arxiv.org/abs/2401.12345",
        "content": "short",
    }
    monkeypatch.setattr(
        "src.research.ldr_url_enrich.fetch_url_article_text",
        lambda url, title="", max_chars=15000: {
            "text": "Detailed arXiv full text about protein structure search benchmarks. " * 30,
            "source": "url_html",
            "source_url": url,
        },
    )
    assert enrich_finding_from_url(finding, as_fulltext=True)
    assert finding.get("deep_read_loaded")
    assert finding.get("sourcing_tier") == "adequate"
