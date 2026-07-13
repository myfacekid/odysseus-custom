"""Tests for forward-citation ("papers that cite/use X") discovery."""
from __future__ import annotations

import src.research_citation_lookup as cl


def test_detects_citation_target_from_paper_reference():
    q = "Please find the most cited papers that use #Di from the foldseek paper"
    assert cl.has_citation_intent(q) is True
    assert cl.detect_citation_target(q) == "foldseek"


def test_detects_cite_verb_with_named_target():
    assert cl.detect_citation_target("papers that cite AlphaFold") == "AlphaFold"
    assert cl.detect_citation_target("works citing the DALL-E model") == "DALL-E"


def test_ignores_non_citation_queries():
    assert cl.detect_citation_target("summarize the foldseek paper") is None
    assert cl.detect_citation_target("what is protein structure prediction") is None
    assert cl.has_citation_intent("what is protein structure prediction") is False


def test_fetch_citing_works_ranks_and_flags(monkeypatch):
    resolved = {
        "id": "https://openalex.org/W123",
        "title": "Fast and accurate protein structure search with Foldseek",
        "cited_by_count": 2000,
    }
    citing_payload = {
        "results": [
            {
                "id": "https://openalex.org/W1",
                "title": "Downstream method using 3Di",
                "publication_year": 2024,
                "cited_by_count": 900,
                "type": "article",
            },
            {
                "id": "https://openalex.org/W2",
                "title": "Another 3Di application",
                "publication_year": 2023,
                "cited_by_count": 120,
                "type": "preprint",
            },
        ]
    }

    def fake_http_json(url, *, timeout=20):
        if "filter=cites" in url:
            return citing_payload
        return {"results": [resolved]}

    monkeypatch.setattr(cl, "_http_json", fake_http_json)

    findings = cl.fetch_citing_works("foldseek", limit=10)
    assert len(findings) == 2
    assert all(f["always_include"] for f in findings)
    assert findings[0]["citation_count"] == 900
    assert findings[0]["source_type"] == "citing_paper"
    assert "Cites" in findings[0]["rational"]

    # Preprints excluded when include_preprints=False.
    peer_only = cl.fetch_citing_works("foldseek", limit=10, include_preprints=False)
    assert len(peer_only) == 1
    assert peer_only[0]["citation_count"] == 900
