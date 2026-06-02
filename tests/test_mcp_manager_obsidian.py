"""Tests for Obsidian / remote MCP connection helpers."""

from src.mcp_manager import (
    _build_http_headers,
    _normalize_mcp_url,
    _resolve_effective_transport,
    McpManager,
)


def test_normalize_obsidian_root_url():
    assert _normalize_mcp_url("https://127.0.0.1:27124/") == "https://127.0.0.1:27124/mcp/"
    assert _normalize_mcp_url("http://127.0.0.1:27123") == "http://127.0.0.1:27123/mcp/"


def test_resolve_streamable_http_for_obsidian_sse():
    assert _resolve_effective_transport(
        "sse", "https://127.0.0.1:27124/mcp/"
    ) == "streamable_http"
    assert _resolve_effective_transport(
        "sse", "https://127.0.0.1:27124/"
    ) == "streamable_http"


def test_build_headers_from_obsidian_api_key():
    headers = _build_http_headers({"OBSIDIAN_API_KEY": "secret-key"})
    assert headers["Authorization"] == "Bearer secret-key"


def test_match_tools_for_query_obsidian_intent():
    mgr = McpManager()
    mgr._tools["abc123"] = [
        {"name": "vault_read", "description": "Read a vault file", "input_schema": {}},
        {"name": "search_simple", "description": "Search vault", "input_schema": {}},
    ]
    mgr._connections["abc123"] = {"status": "connected", "name": "Obsidian_MCP", "tool_count": 2}
    matched = mgr.match_tools_for_query("read my daily note in obsidian")
    assert "mcp__abc123__vault_read" in matched
    assert "mcp__abc123__search_simple" in matched
