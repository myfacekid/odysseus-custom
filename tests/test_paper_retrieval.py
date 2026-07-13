"""Paper Token Retrieval Phase R0 — tier defaults and PDF budget."""

import json
from unittest.mock import patch

from src.knowledge_graph import execute_knowledge_tool, rebuild_owner_graph
from src.paper_retrieval import PAPER_PDF_MAX_CHARS, PAPER_READ_DEFAULT_MAX_CHARS
from src.zotero_client import execute_search_zotero_tool


def _seed_paper_catalog(tmp_path, owner):
    zdir = tmp_path / "zotero" / "users" / owner
    zdir.mkdir(parents=True)
    (zdir / "catalog.jsonl").write_text(
        json.dumps({
            "zotero_key": "PAPER1",
            "title": "Attention Is All You Need",
            "authors": "Vaswani",
            "year": "2017",
            "abstract": "Transformers use self-attention.",
            "collection_keys": [],
            "collection_paths": [],
            "item_type": "journalArticle",
            "doi": "",
            "url": "https://example.test/paper",
            "has_pdf": True,
        }) + "\n",
        encoding="utf-8",
    )
    (zdir / "manifest.json").write_text(
        json.dumps({"synced_at": "2026-01-01T00:00:00Z", "user_id": "1"}),
        encoding="utf-8",
    )


def test_paper_read_default_skips_pdf(tmp_path, monkeypatch):
    monkeypatch.setattr("src.knowledge_graph.KNOWLEDGE_ROOT", tmp_path / "knowledge")
    monkeypatch.setattr("src.zotero_catalog.ZOTERO_ROOT", tmp_path / "zotero")
    owner = "tester"
    _seed_paper_catalog(tmp_path, owner)

    with patch("src.knowledge_graph.OBSIDIAN_INTEGRATION_ENABLED", False):
        rebuild_owner_graph(owner)

    with patch(
        "src.zotero_client.fetch_paper_pdf_text",
        side_effect=AssertionError("PDF should not be fetched on default paper read"),
    ):
        out = execute_knowledge_tool({"action": "read", "id": "paper:PAPER1"}, owner=owner)

    assert out["exit_code"] == 0
    assert "Transformers use self-attention." in out["output"]
    assert "PDF extraction skipped" in out["output"]
    assert "PDF text" not in out["output"]


def test_paper_read_respects_pdf_max_chars_budget(tmp_path, monkeypatch):
    monkeypatch.setattr("src.knowledge_graph.KNOWLEDGE_ROOT", tmp_path / "knowledge")
    monkeypatch.setattr("src.zotero_catalog.ZOTERO_ROOT", tmp_path / "zotero")
    owner = "tester"
    _seed_paper_catalog(tmp_path, owner)

    with patch("src.knowledge_graph.OBSIDIAN_INTEGRATION_ENABLED", False):
        rebuild_owner_graph(owner)

    seen = {}

    def _fetch(_owner, key, max_chars=15000):
        seen["max_chars"] = max_chars
        return ("x" * max_chars, "")

    with patch("src.zotero_client.fetch_paper_pdf_text", side_effect=_fetch):
        execute_knowledge_tool(
            {
                "action": "read",
                "id": "paper:PAPER1",
                "include_pdf": True,
                "max_chars": 2000,
            },
            owner=owner,
        )

    assert seen["max_chars"] == 2000
    assert seen["max_chars"] < 12000


def test_paper_pdf_budget_capped_at_policy_max(tmp_path, monkeypatch):
    monkeypatch.setattr("src.knowledge_graph.KNOWLEDGE_ROOT", tmp_path / "knowledge")
    monkeypatch.setattr("src.zotero_catalog.ZOTERO_ROOT", tmp_path / "zotero")
    owner = "tester"
    _seed_paper_catalog(tmp_path, owner)

    with patch("src.knowledge_graph.OBSIDIAN_INTEGRATION_ENABLED", False):
        rebuild_owner_graph(owner)

    seen = {}

    def _fetch(_owner, key, max_chars=15000):
        seen["max_chars"] = max_chars
        return ("body", "")

    with patch("src.zotero_client.fetch_paper_pdf_text", side_effect=_fetch):
        execute_knowledge_tool(
            {
                "action": "read",
                "id": "paper:PAPER1",
                "include_pdf": True,
                "max_chars": 999_999,
            },
            owner=owner,
        )

    assert seen["max_chars"] == PAPER_PDF_MAX_CHARS


def test_search_zotero_broad_search_skips_pdf(tmp_path, monkeypatch):
    monkeypatch.setattr("src.zotero_catalog.ZOTERO_ROOT", tmp_path / "zotero")
    owner = "tester"
    _seed_paper_catalog(tmp_path, owner)
    monkeypatch.setattr(
        "src.zotero_client.resolve_zotero_credentials",
        lambda o="": {"api_key": "k", "user_id": "1"},
    )

    with patch(
        "src.zotero_client.fetch_paper_pdf_text",
        side_effect=AssertionError("broad search must not extract PDFs"),
    ):
        out = execute_search_zotero_tool({"action": "search", "query": "attention"}, owner=owner)

    assert out["exit_code"] == 0
    assert "Attention Is All You Need" in out["output"]


def test_search_zotero_key_fetches_pdf_by_default(tmp_path, monkeypatch):
    monkeypatch.setattr("src.zotero_catalog.ZOTERO_ROOT", tmp_path / "zotero")
    owner = "tester"
    _seed_paper_catalog(tmp_path, owner)
    monkeypatch.setattr(
        "src.zotero_client.resolve_zotero_credentials",
        lambda o="": {"api_key": "k", "user_id": "1"},
    )

    with patch(
        "src.zotero_client.fetch_paper_pdf_text",
        return_value=("Full PDF body.", ""),
    ):
        out = execute_search_zotero_tool(
            {"action": "search", "zotero_key": "PAPER1"},
            owner=owner,
        )

    assert out["exit_code"] == 0
    assert "Full PDF body." in out["output"]


def test_paper_read_default_max_chars_constant():
    assert PAPER_READ_DEFAULT_MAX_CHARS == 3000


def test_paper_read_section_uses_tier2(tmp_path, monkeypatch):
    monkeypatch.setattr("src.knowledge_graph.KNOWLEDGE_ROOT", tmp_path / "knowledge")
    monkeypatch.setattr("src.zotero_catalog.ZOTERO_ROOT", tmp_path / "zotero")
    owner = "tester"
    _seed_paper_catalog(tmp_path, owner)

    with patch("src.knowledge_graph.OBSIDIAN_INTEGRATION_ENABLED", False):
        rebuild_owner_graph(owner)

    with patch(
        "src.zotero_client.fetch_paper_section_text",
        return_value=(
            "We train with AdamW and cosine decay.",
            "",
            {"matched_slug": "methods", "matched_label": "Methods", "available_sections": ["methods"]},
        ),
    ), patch(
        "src.zotero_client.fetch_paper_pdf_text",
        side_effect=AssertionError("section read must not fetch full PDF"),
    ):
        out = execute_knowledge_tool(
            {"action": "read", "id": "paper:PAPER1", "section": "methods"},
            owner=owner,
        )

    assert out["exit_code"] == 0
    assert "AdamW" in out["output"]
    assert "Section: Methods" in out["output"]


def test_search_zotero_section_extract(tmp_path, monkeypatch):
    monkeypatch.setattr("src.zotero_catalog.ZOTERO_ROOT", tmp_path / "zotero")
    owner = "tester"
    _seed_paper_catalog(tmp_path, owner)
    monkeypatch.setattr(
        "src.zotero_client.resolve_zotero_credentials",
        lambda o="": {"api_key": "k", "user_id": "1"},
    )

    with patch(
        "src.zotero_client.fetch_paper_section_text",
        return_value=(
            "Optimization procedure details here.",
            "",
            {"matched_slug": "methods", "matched_label": "Methods"},
        ),
    ):
        out = execute_search_zotero_tool(
            {"action": "search", "zotero_key": "PAPER1", "section": "methods"},
            owner=owner,
        )

    assert out["exit_code"] == 0
    assert "Optimization procedure" in out["output"]
    assert "section: Methods" in out["output"]
