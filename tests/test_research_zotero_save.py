"""Phase 5b — batch save research sources to Zotero."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from routes.research_routes import setup_research_routes
from src.research_evidence import EvidenceRegistry
from src.research_zotero_save import (
    is_in_library,
    is_saveable,
    preview_save_sources,
    save_research_sources_to_zotero,
    select_save_sources,
    source_to_zotero_item,
)


def _registry_payload(*findings):
    reg = EvidenceRegistry()
    for finding in findings:
        reg.register(finding)
    return reg.to_dict()


def test_is_in_library_and_saveable():
    reg = EvidenceRegistry()
    reg.register({"zotero_key": "ABC12345", "title": "Seed"})
    reg.register({"url": "https://example.com/paper", "title": "Web hit"})
    zotero_src, web_src = reg.sources()
    assert is_in_library(zotero_src)
    assert not is_saveable(zotero_src)
    assert not is_in_library(web_src)
    assert is_saveable(web_src)


def test_select_save_sources_skips_library_and_uncited():
    data = {
        "raw_report": "Claim [1] and [2].",
        "evidence_registry": _registry_payload(
            {"zotero_key": "SEED0001", "title": "Seed paper", "is_seed": True},
            {"url": "https://ex.com/web", "title": "Web finding"},
            {"url": "https://ex.com/other", "title": "Uncited"},
        ),
    }
    reg = EvidenceRegistry.from_dict(data["evidence_registry"])
    selected = select_save_sources(reg, data["raw_report"], scope="cited")
    assert len(selected) == 1
    assert selected[0].title == "Web finding"


def test_source_to_zotero_item_maps_metadata():
    reg = EvidenceRegistry()
    reg.register({
        "url": "https://doi.org/10.1234/example",
        "title": "Example RCT",
        "authors": "Smith, J. and Lee, A.",
        "year": "2024",
        "doi_or_id": "10.1234/example",
        "peer_review_status": "preprint",
        "study_type": "RCT",
        "content_excerpt": "Methods summary.",
    })
    src = reg.sources()[0]
    item = source_to_zotero_item(src)
    assert item["itemType"] == "preprint"
    assert item["DOI"] == "10.1234/example"
    assert item["creators"]
    assert item["date"] == "2024"
    assert item["abstractNote"]
    assert "RCT" in item["abstractNote"]
    assert "collections" not in item

    filed = source_to_zotero_item(src, collection_key="COLLKEY1")
    assert filed["collections"] == ["COLLKEY1"]


def test_resolve_save_collection_key():
    from src.research_zotero_save import resolve_save_collection_key

    cols = [
        {"key": "AAAA1111", "name": "Papers", "path": "Research / Papers"},
        {"key": "BBBB2222", "name": "Drafts", "path": "Drafts"},
    ]
    assert resolve_save_collection_key(None, cols) is None
    assert resolve_save_collection_key("", cols) is None
    assert resolve_save_collection_key("BBBB2222", cols) == "BBBB2222"
    with pytest.raises(ValueError, match="Unknown Zotero collection"):
        resolve_save_collection_key("MISSING", cols)


def test_save_research_sources_to_zotero_batches_and_skips_library():
    data = {
        "raw_report": "Finding [1] and [2].",
        "evidence_registry": _registry_payload(
            {"zotero_key": "SEED0001", "title": "Already in library"},
            {"url": "https://ex.com/a", "title": "Save me A"},
            {"url": "https://ex.com/b", "title": "Save me B"},
        ),
    }

    class FakeClient:
        def __init__(self):
            self.calls = []

        def create_items(self, items):
            self.calls.append(items)
            return len(items), None

    client = FakeClient()
    result = save_research_sources_to_zotero(
        data,
        client,
        scope="cited",
        citation_nums=[1, 2, 3],
    )
    assert result["ok"] is True
    assert result["created"] == 2
    assert result["attempted"] == 2
    assert result["skipped_in_library"] == 1
    assert result["collection_key"] is None
    assert len(client.calls) == 1
    assert client.calls[0][0]["title"] == "Save me A"
    assert "collections" not in client.calls[0][0]


def test_save_research_sources_to_zotero_with_collection():
    data = {
        "raw_report": "Finding [1].",
        "evidence_registry": _registry_payload(
            {"url": "https://ex.com/a", "title": "Save me A"},
        ),
    }

    class FakeClient:
        def __init__(self):
            self.calls = []

        def create_items(self, items):
            self.calls.append(items)
            return len(items), None

        def list_collections(self):
            return [{"key": "FOLDER99", "name": "Deep Research", "path": "Deep Research"}]

    client = FakeClient()
    result = save_research_sources_to_zotero(
        data,
        client,
        scope="cited",
        citation_nums=[1],
        collection_key="FOLDER99",
    )
    assert result["ok"] is True
    assert result["created"] == 1
    assert result["collection_key"] == "FOLDER99"
    assert client.calls[0][0]["collections"] == ["FOLDER99"]


def test_save_research_sources_to_zotero_rejects_unknown_collection():
    data = {
        "raw_report": "Finding [1].",
        "evidence_registry": _registry_payload(
            {"url": "https://ex.com/a", "title": "Save me A"},
        ),
    }

    class FakeClient:
        def create_items(self, items):
            raise AssertionError("should not create")

        def list_collections(self):
            return [{"key": "REALKEY1", "name": "Real", "path": "Real"}]

    with pytest.raises(ValueError, match="Unknown Zotero collection"):
        save_research_sources_to_zotero(
            {"raw_report": data["raw_report"], "evidence_registry": data["evidence_registry"]},
            FakeClient(),
            collection_key="NOPE0000",
        )


def test_preview_save_sources_defaults():
    data = {
        "raw_report": "See [2]. Also [2] again.",
        "evidence_registry": _registry_payload(
            {"zotero_key": "SEED0001", "title": "Seed", "is_seed": True},
            {
                "url": "https://ex.com/cited",
                "title": "Cited web",
                "peer_review_status": "preprint",
                "study_type": "RCT",
                "year": "2024",
                "authors": "Doe, J.",
                "content_excerpt": "A" * 300,
            },
            {"url": "https://ex.com/other", "title": "Other web"},
        ),
    }
    # Preserve explicit tiers the way session JSON does (to_dict / from_dict).
    reg = EvidenceRegistry.from_dict(data["evidence_registry"])
    for src in reg.sources():
        if src.citation_num == 1:
            src.sourcing_tier = "adequate"
            src.is_seed = True
        elif src.citation_num == 2:
            src.sourcing_tier = "abstract_only"
        else:
            src.sourcing_tier = "metadata_only"
    data["evidence_registry"] = reg.to_dict()

    preview = preview_save_sources(data, scope="cited")
    assert len(preview["in_library"]) == 1
    assert len(preview["saveable"]) == 2
    assert preview["default_citation_nums"] == [2]
    cited = next(s for s in preview["saveable"] if s["citation_num"] == 2)
    assert cited["cite_count"] == 2
    assert cited["cited"] is True
    assert cited["sourcing_tier"] == "abstract_only"
    assert cited["sourcing_tier_label"] == "Abstract only"
    assert cited["sourcing_tier_class"] == "abstract"
    assert cited["peer_review_status"] == "preprint"
    assert cited["study_type"] == "RCT"
    seed = preview["in_library"][0]
    assert seed["is_seed"] is True
    assert seed["sourcing_tier_label"] == "Full text"


def _request(user: str):
    return SimpleNamespace(state=SimpleNamespace(current_user=user))


def _route(router, path: str, method: str):
    for route in router.routes:
        if getattr(route, "path", None) == path and method in getattr(route, "methods", set()):
            return route.endpoint
    raise AssertionError(f"Route not found: {method} {path}")


def _write_research(data_dir, session_id: str, **data):
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / f"{session_id}.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_research_save_to_zotero_route(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    data_dir = tmp_path / "data" / "deep_research"
    _write_research(
        data_dir,
        "save-zotero-test",
        owner="alice",
        raw_report="Finding [1].",
        evidence_registry=_registry_payload(
            {"url": "https://ex.com/new", "title": "Fresh source", "authors": "Doe, J."},
        ),
    )

    handler = MagicMock()
    handler._active_tasks = {}
    handler.save_to_zotero.return_value = {
        "ok": True,
        "created": 1,
        "attempted": 1,
        "skipped_in_library": 0,
        "saved_citation_nums": [1],
    }

    monkeypatch.setattr("src.auth_helpers.require_privilege", lambda req, priv: "alice")
    monkeypatch.setattr("src.zotero_catalog.sync_zotero_catalog", lambda owner: {"ok": True})

    router = setup_research_routes(handler)
    save_route = _route(router, "/api/research/{session_id}/save-to-zotero", "POST")

    result = asyncio.run(save_route(
        "save-zotero-test",
        SimpleNamespace(citation_nums=[1], scope="cited", collection_key="FOLDER99"),
        _request("alice"),
    ))
    assert result["created"] == 1
    handler.save_to_zotero.assert_called_once_with(
        "save-zotero-test",
        scope="cited",
        citation_nums=[1],
        collection_key="FOLDER99",
    )


def test_research_save_to_zotero_route_rejects_cross_owner(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    data_dir = tmp_path / "data" / "deep_research"
    _write_research(
        data_dir,
        "bob-save",
        owner="bob",
        raw_report="Secret [1].",
        evidence_registry=_registry_payload(
            {"url": "https://ex.com/1", "title": "One"},
        ),
    )

    handler = MagicMock()
    handler._active_tasks = {}
    monkeypatch.setattr("src.auth_helpers.require_privilege", lambda req, priv: "alice")

    router = setup_research_routes(handler)
    save_route = _route(router, "/api/research/{session_id}/save-to-zotero", "POST")

    with pytest.raises(HTTPException) as exc:
        asyncio.run(save_route(
            "bob-save",
            SimpleNamespace(citation_nums=[1], scope="cited"),
            _request("alice"),
        ))
    assert exc.value.status_code == 404
