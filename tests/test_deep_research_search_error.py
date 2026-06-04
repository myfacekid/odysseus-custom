"""Regression tests for deep-research search error reporting (issue #344).

When every configured search provider returns no results *without raising*
(e.g. SearXNG is reachable but all of its engines fail), ``_search`` used to
leave ``_last_search_error`` unset. The caller then surfaced a useless
"Search unavailable ... Error: unknown error" message.

Phase 1a routes ``_search`` through ``research_web_search`` (shared provider
layer). These tests mock that layer directly.
"""
import asyncio

from src.deep_research import DeepResearcher
from src.research_web_search import ResearchSearchOutcome


def _make_researcher():
    from src.research_evidence import EvidenceRegistry

    r = DeepResearcher.__new__(DeepResearcher)
    r.search_provider_override = None
    r.providers_used = []
    r.include_preprints = True
    r.evidence_registry = EvidenceRegistry()
    return r


def test_empty_results_without_exception_record_reason(monkeypatch):
    def _empty(*args, **kwargs):
        return ResearchSearchOutcome(
            [], "searxng", kwargs.get("query") or args[0], "discovery",
            error="No search results found. Tried: searxng:empty",
        )

    monkeypatch.setattr("src.deep_research.research_web_search", _empty)
    r = _make_researcher()
    results = asyncio.run(r._search("anything"))

    assert results == []
    err = getattr(r, "_last_search_error", None)
    assert err
    assert "No search results" in err


def test_provider_exception_is_still_surfaced(monkeypatch):
    def _boom(*args, **kwargs):
        raise RuntimeError("connection refused")

    monkeypatch.setattr("src.deep_research.research_web_search", _boom)
    r = _make_researcher()
    results = asyncio.run(r._search("anything"))

    assert results == []
    err = getattr(r, "_last_search_error", None)
    assert err and "connection refused" in err


def test_results_are_returned_and_provider_recorded(monkeypatch):
    hits = [{"url": "https://example.com", "title": "x", "snippet": "s"}]

    def _ok(query, **kwargs):
        return ResearchSearchOutcome(hits, "brave", query, "discovery")

    monkeypatch.setattr("src.deep_research.research_web_search", _ok)
    r = _make_researcher()
    results = asyncio.run(r._search("anything"))

    assert len(results) == 1
    assert results[0]["search_provider"] == "brave"
    assert results[0]["search_kind"] == "discovery"
    assert r.providers_used == ["brave"]
