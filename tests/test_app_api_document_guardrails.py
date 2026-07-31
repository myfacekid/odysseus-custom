"""app_api must not be used for Library/document create/register/link."""

from __future__ import annotations

import json

import pytest

from src.tool_implementations import (
    _APP_API_BLOCKLIST_PREFIXES,
    _APP_API_DOC_REDIRECT,
    _cookbook_base_url,
    do_app_api,
)


@pytest.mark.asyncio
async def test_app_api_blocks_library_documents_register():
    result = await do_app_api(json.dumps({
        "action": "call",
        "method": "POST",
        "path": "/api/library/documents/register",
        "body": {"paths": ["/tmp/edge-type.md"]},
    }))
    assert result["exit_code"] == 1
    assert "create_document" in result["error"]
    assert result["error"] == _APP_API_DOC_REDIRECT


@pytest.mark.asyncio
async def test_app_api_blocks_documents_library_get():
    result = await do_app_api(json.dumps({
        "action": "call",
        "method": "GET",
        "path": "/api/documents/library",
    }))
    assert result["exit_code"] == 1
    assert "create_document" in result["error"]
    assert "manage_documents" in result["error"]


@pytest.mark.asyncio
async def test_app_api_blocks_singular_document_path():
    result = await do_app_api(json.dumps({
        "action": "call",
        "method": "GET",
        "path": "/api/document/abc-123",
    }))
    assert result["exit_code"] == 1
    assert "search_knowledge" in result["error"]


@pytest.mark.asyncio
async def test_app_api_endpoints_filter_document_redirects_without_openapi(monkeypatch):
    """filter=document must redirect before OpenAPI fetch (no connection attempt)."""
    calls = []

    class BoomClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, **kwargs):
            calls.append(url)
            raise AssertionError("OpenAPI must not be fetched for document filter")

    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", BoomClient)

    result = await do_app_api(json.dumps({
        "action": "endpoints",
        "filter": "document",
    }))
    assert result["exit_code"] == 1
    assert "create_document" in result["error"]
    assert calls == []


@pytest.mark.asyncio
async def test_app_api_endpoints_hides_document_paths(monkeypatch):
    """Even if OpenAPI lists document routes, blocklist strips them."""
    openapi = {
        "paths": {
            "/api/documents/library": {
                "get": {"summary": "List library documents"},
            },
            "/api/document/{id}": {
                "get": {"summary": "Get one document"},
            },
            "/api/library/documents/register": {
                "post": {"summary": "Register documents"},
            },
            "/api/cookbook/gpus": {
                "get": {"summary": "List GPUs"},
            },
            "/api/gallery/list": {
                "get": {"summary": "List gallery"},
            },
        }
    }

    class FakeResp:
        def json(self):
            return openapi

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, **kwargs):
            return FakeResp()

    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)

    result = await do_app_api(json.dumps({"action": "endpoints", "filter": "gallery"}))
    assert result["exit_code"] == 0
    paths = [e["path"] for e in result["endpoints"]]
    assert "/api/gallery/list" in paths
    assert all(not p.startswith(("/api/document", "/api/library")) for p in paths)

    # Unfiltered list must also omit document/library prefixes
    result_all = await do_app_api(json.dumps({"action": "endpoints"}))
    assert result_all["exit_code"] == 0
    all_paths = [e["path"] for e in result_all["endpoints"]]
    assert "/api/cookbook/gpus" in all_paths
    assert all(not p.startswith(("/api/document", "/api/library")) for p in all_paths)


def test_document_prefixes_are_blocklisted():
    assert "/api/document" in _APP_API_BLOCKLIST_PREFIXES
    assert "/api/library" in _APP_API_BLOCKLIST_PREFIXES
    # /api/document covers /api/documents via startswith
    assert "/api/documents/library".startswith("/api/document")


def test_cookbook_base_url_honors_ports(monkeypatch):
    monkeypatch.delenv("NOBODY_PORT", raising=False)
    monkeypatch.delenv("APP_PORT", raising=False)
    assert _cookbook_base_url() == "http://localhost:7000"

    monkeypatch.setenv("APP_PORT", "7860")
    assert _cookbook_base_url() == "http://localhost:7860"

    monkeypatch.setenv("NOBODY_PORT", "7900")
    assert _cookbook_base_url() == "http://localhost:7900"  # NOBODY_PORT wins
