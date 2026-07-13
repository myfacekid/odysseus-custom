"""Tests for LDR DOI dedup and content enrichment."""

import pytest

from src.research.ldr_content_enrich import (
    build_deep_read_context_block,
    heuristic_deep_read_candidates,
    parse_citation_picker_response,
)
from src.research.ldr_doi import dedupe_raw_links_by_doi, raw_link_text_richness
from src.research_evidence import EvidenceRegistry


def test_dedupe_raw_links_by_doi_keeps_richer_row():
    links = [
        {"title": "A", "link": "https://a", "doi": "10.1234/x", "snippet": "short"},
        {"title": "B", "link": "https://b", "doi": "10.1234/x", "snippet": "x" * 200},
        {"title": "C", "link": "https://c", "snippet": "no doi"},
    ]
    deduped, dropped = dedupe_raw_links_by_doi(links)
    assert dropped == 1
    assert len(deduped) == 2
    doi_rows = [r for r in deduped if (r.get("doi") or "") == "10.1234/x"]
    assert len(doi_rows) == 1
    assert raw_link_text_richness(doi_rows[0]) == raw_link_text_richness(links[1])


def test_parse_citation_picker_response():
    assert parse_citation_picker_response("Pick [2, 5, 99] please", max_num=10) == [2, 5]
    assert parse_citation_picker_response("[]", max_num=5) == []


def test_heuristic_deep_read_prefers_thin_doi_sources():
    registry = EvidenceRegistry()
    registry.register(
        {
            "title": "Rich",
            "url": "https://doi.org/10.1/rich",
            "doi_or_id": "10.1234/rich",
            "evidence": "x" * 1200,
        }
    )
    registry.register(
        {
            "title": "Thin",
            "url": "https://doi.org/10.1/thin",
            "doi_or_id": "10.1234/thin",
            "content": "title only",
        }
    )
    findings = [
        {
            "citation_num": 1,
            "source_id": registry.sources()[0].source_id,
            "doi_or_id": "10.1234/rich",
            "evidence": "x" * 1200,
        },
        {
            "citation_num": 2,
            "source_id": registry.sources()[1].source_id,
            "doi_or_id": "10.1234/thin",
            "content": "title only",
        },
    ]
    picked = heuristic_deep_read_candidates(registry, findings, limit=3)
    assert 2 in picked
    assert 1 not in picked


def test_build_deep_read_context_block_only_includes_loaded():
    registry = EvidenceRegistry()
    registry.register({"title": "Loaded", "url": "https://a", "content": "meta"})
    findings = [
        {
            "citation_num": 1,
            "source_id": registry.sources()[0].source_id,
            "title": "Loaded",
            "evidence": "Full paper body " * 80,
            "deep_read_loaded": True,
            "sourcing_tier": "adequate",
        }
    ]
    block = build_deep_read_context_block(registry, findings, {1})
    assert "Full paper body" in block
    assert "Loaded" in block
