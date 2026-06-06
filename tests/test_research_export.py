"""Phase 3d — research export pipeline."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from routes.research_routes import setup_research_routes
from src.research_evidence import EvidenceRegistry
from src.research_export import (
    build_export,
    export_bibtex,
    export_csl_json,
    export_markdown,
    select_export_sources,
    source_to_bibtex,
    source_to_csl_item,
)


def _registry_payload(*sources):
    reg = EvidenceRegistry()
    for src in sources:
        reg.register(src)
    return reg.to_dict()


def test_export_markdown_prefers_raw_report():
    md = export_markdown({
        "query": "Sleep and cognition",
        "raw_report": "Body text with finding [1].",
        "result": "older",
    })
    assert md.startswith("# Sleep and cognition")
    assert "Body text" in md

    existing = export_markdown({
        "query": "Sleep and cognition",
        "raw_report": "## Executive Summary\nFinding [1].",
    })
    assert existing.startswith("## Executive Summary")


def test_select_export_sources_cited_only():
    data = {
        "raw_report": "Claim [1] and [2].",
        "evidence_registry": _registry_payload(
            {"url": "https://ex.com/1", "title": "One", "authors": "A"},
            {"url": "https://ex.com/2", "title": "Two", "authors": "B"},
            {"url": "https://ex.com/3", "title": "Three", "authors": "C"},
        ),
    }
    reg = EvidenceRegistry.from_dict(data["evidence_registry"])
    cited = select_export_sources(reg, data["raw_report"], scope="cited")
    assert [s.citation_num for s in cited] == [1, 2]
    all_sources = select_export_sources(reg, data["raw_report"], scope="all")
    assert len(all_sources) == 3


def test_export_bibtex_includes_doi_and_preprint_note():
    data = {
        "raw_report": "Finding [1].",
        "evidence_registry": _registry_payload({
            "url": "https://arxiv.org/abs/1234",
            "title": "Trial",
            "authors": "Smith, J.",
            "year": "2024",
            "doi_or_id": "10.1234/trial",
            "peer_review_status": "preprint",
            "study_type": "RCT",
        }),
    }
    bib = export_bibtex(data, scope="cited")
    assert "@misc{" in bib or "@article{" in bib
    assert "doi = {10.1234/trial}" in bib
    assert "preprint" in bib
    assert "Smith, J." in bib


def test_export_csl_json_is_valid_list():
    data = {
        "raw_report": "Finding [1].",
        "evidence_registry": _registry_payload({
            "url": "https://ex.com/a",
            "title": "Alpha",
            "authors": "Lee, A.",
            "year": "2023",
            "doi_or_id": "10.5555/alpha",
        }),
    }
    raw = export_csl_json(data, scope="cited")
    items = json.loads(raw)
    assert len(items) == 1
    assert items[0]["DOI"] == "10.5555/alpha"
    assert items[0]["author"][0]["family"] == "Lee"


def test_build_export_returns_filename_and_media_type():
    content, media_type, filename = build_export(
        {
            "query": "Topic A/B",
            "raw_report": "Body [1].",
            "evidence_registry": _registry_payload(
                {"url": "https://ex.com/1", "title": "One", "authors": "A"},
            ),
        },
        "bibtex",
        session_id="sess123",
    )
    assert "@article{" in content or "@misc{" in content
    assert media_type.startswith("application/x-bibtex")
    assert filename.endswith(".bib")


def test_source_to_bibtex_and_csl_handle_minimal_source():
    reg = EvidenceRegistry()
    reg.register({"url": "https://ex.com/x", "title": "Minimal"})
    src = reg.sources()[0]
    assert "Minimal" in source_to_bibtex(src)
    item = source_to_csl_item(src)
    assert item["title"] == "Minimal"
    assert item["type"] == "document"


def _request(user: str):
    return SimpleNamespace(state=SimpleNamespace(current_user=user))


def _route(router, path: str, method: str):
    for route in router.routes:
        if getattr(route, "path", "") != path:
            continue
        if method in getattr(route, "methods", set()):
            return route.endpoint
    raise AssertionError(f"{method} {path} route not registered")


def _write_research(data_dir, session_id: str, **data):
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / f"{session_id}.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_export_route_returns_attachment_for_owner(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    data_dir = tmp_path / "data" / "deep_research"
    registry = _registry_payload(
        {"url": "https://ex.com/1", "title": "One", "authors": "A"},
    )
    _write_research(
        data_dir,
        "alice-export",
        owner="alice",
        query="Export me",
        raw_report="Finding [1].",
        evidence_registry=registry,
    )

    handler = MagicMock()
    handler._active_tasks = {}
    from src.research_handler import ResearchHandler

    real = ResearchHandler()
    handler.export_research = real.export_research

    router = setup_research_routes(handler)
    target = _route(router, "/api/research/{session_id}/export", "GET")

    resp = asyncio.run(target(
        session_id="alice-export",
        request=_request("alice"),
        format="markdown",
        scope="cited",
    ))
    assert resp.status_code == 200
    assert "Export_me.md" in resp.headers["content-disposition"]
    assert b"Finding [1]" in resp.body


def test_export_route_rejects_cross_owner(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    data_dir = tmp_path / "data" / "deep_research"
    _write_research(
        data_dir,
        "bob-export",
        owner="bob",
        raw_report="Secret [1].",
        evidence_registry=_registry_payload(
            {"url": "https://ex.com/1", "title": "One"},
        ),
    )

    handler = MagicMock()
    handler._active_tasks = {}
    router = setup_research_routes(handler)
    target = _route(router, "/api/research/{session_id}/export", "GET")

    with pytest.raises(HTTPException) as exc:
        asyncio.run(target(
            session_id="bob-export",
            request=_request("alice"),
            format="markdown",
            scope="cited",
        ))
    assert exc.value.status_code == 404
