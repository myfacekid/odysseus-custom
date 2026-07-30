"""Phase L1 — research_engines registry, keyword search, settings bridge."""

from unittest.mock import MagicMock, patch

import pytest

from src.research_engines.keyword_search import (
    build_seed_search_queries,
    keyword_search_findings,
    preview_to_finding,
)
from src.research_engines.registry import (
    ACADEMIC_ENGINE_NAMES,
    DEFAULT_SIMILAR_ENGINES,
    nobody_web_to_ldr_tool,
)
from src.research_engines.settings_bridge import academic_engine_overrides


def test_registry_constants():
    assert "openalex" in ACADEMIC_ENGINE_NAMES
    assert "semantic_scholar" in DEFAULT_SIMILAR_ENGINES
    assert nobody_web_to_ldr_tool("google") == "serper"


def test_build_seed_search_queries_title_first():
    seed = {
        "title": "Highly accurate protein structure prediction with AlphaFold",
        "summary": "We present AlphaFold, a neural network for structure prediction.",
    }
    queries = build_seed_search_queries(seed)
    assert queries
    assert "AlphaFold" in queries[0]


def test_preview_to_finding_openalex_shape():
    preview = {
        "title": "Foldseek",
        "link": "https://doi.org/10.1038/s41587-022-01468-w",
        "snippet": "Fast structure search.",
        "authors": "van Kempen, M.",
        "year": 2024,
        "citations": 120,
        "is_open_access": True,
    }
    f = preview_to_finding(preview, "openalex")
    assert f["similar_source"] == "openalex"
    assert f["title"] == "Foldseek"
    assert "doi.org" in f["url"]


def test_academic_engine_overrides_reads_settings(monkeypatch):
    monkeypatch.setattr(
        "src.research_engines.settings_bridge._nobody_settings",
        lambda: {"openalex_email": "user@example.com", "semantic_scholar_api_key": "s2-key"},
    )
    overrides = academic_engine_overrides()
    assert overrides["search.engine.web.openalex.email"] == "user@example.com"
    assert overrides["search.engine.web.semantic_scholar.api_key"] == "s2-key"


def test_keyword_search_findings_dedupes(monkeypatch):
    finding = {
        "url": "https://doi.org/10.1/x",
        "title": "Paper A",
        "doi_or_id": "10.1/x",
        "similar_source": "openalex",
        "evidence": "abstract",
        "summary": "abstract",
    }

    monkeypatch.setattr(
        "src.research_engines.keyword_search._engine_keyword_search",
        lambda engine, query, **k: [finding] if engine == "openalex" else [],
    )
    out = keyword_search_findings(["foldseek"], engines=("openalex", "semantic_scholar"), limit_per_query=3)
    assert len(out.findings) == 1
    assert out.engine_counts.get("openalex") == 1


def test_openalex_keyword_native(monkeypatch):
    from src.research_engines.keyword_search import _openalex_keyword_native

    monkeypatch.setattr(
        "src.research_engines.keyword_search._http_json",
        lambda url, **k: {
            "results": [{
                "title": "Test paper",
                "doi": "https://doi.org/10.1/test",
                "publication_year": 2024,
                "authorships": [],
                "type": "article",
            }]
        },
    )
    findings = _openalex_keyword_native("foldseek", limit=5)
    assert len(findings) == 1
    assert findings[0]["similar_source"] == "openalex"


@patch("src.research_engines.ldr_factory.ldr_engines_available", return_value=False)
def test_engine_keyword_search_falls_back_native(_mock_ldr, monkeypatch):
    from src.research_engines.keyword_search import _engine_keyword_search

    monkeypatch.setattr(
        "src.research_engines.keyword_search._openalex_keyword_native",
        lambda query, **k: [{"url": "https://doi.org/10.1/x", "title": "T", "evidence": "e", "summary": "s", "similar_source": "openalex"}],
    )
    out = _engine_keyword_search("openalex", "query", limit=3)
    assert len(out) == 1
