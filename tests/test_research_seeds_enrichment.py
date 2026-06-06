"""Seed paper online enrichment when Zotero content is thin."""

from unittest.mock import patch

from src.research_seeds import (
    enrich_seed_finding_from_web,
    seed_needs_online_enrichment,
)


def test_seed_needs_online_enrichment_when_pdf_failed():
    finding = {
        "title": "AlphaFold protein structure prediction",
        "summary": "Short note",
        "evidence": "Short note",
        "pdf_fetch_failed": True,
        "has_pdf": True,
    }
    assert seed_needs_online_enrichment(finding)


def test_seed_needs_online_enrichment_when_rich_enough():
    finding = {
        "title": "AlphaFold protein structure prediction",
        "summary": "x" * 300,
        "evidence": "x" * 800,
        "pdf_extracted": True,
    }
    assert not seed_needs_online_enrichment(finding)


def test_enrich_seed_finding_from_web_fetches_doi(monkeypatch):
    finding = {
        "title": "Highly accurate protein structure prediction with AlphaFold",
        "doi_or_id": "10.1038/s41586-021-03819-2",
        "url": "https://www.zotero.org/items/ABC12345",
        "summary": "",
        "evidence": "",
        "pdf_fetch_failed": True,
        "has_pdf": True,
    }

    def _fake_fetch(url, **kwargs):
        if "doi.org" in url:
            return {
                "success": True,
                "content": "AlphaFold predicts protein structures with high accuracy. " * 40,
                "title": finding["title"],
            }
        return {"success": False, "content": ""}

    monkeypatch.setattr("src.search.content.fetch_webpage_content", _fake_fetch)
    import src.search as search_mod
    monkeypatch.setattr(search_mod, "fetch_webpage_content", _fake_fetch)
    enriched = enrich_seed_finding_from_web(finding, owner="tester", max_chars=5000)
    assert enriched.get("web_enriched") is True
    assert len(enriched.get("evidence") or "") > 500
