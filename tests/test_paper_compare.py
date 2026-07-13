"""Paper comparison tool tests (Paper Token Retrieval R3)."""

import json
from unittest.mock import patch

import pytest

from src.paper_compare import (
    COMPARE_SYNC_MAX_PAPERS,
    execute_compare_papers,
    format_compare_output,
    gather_paper_slice,
    normalize_paper_keys,
    resolve_focus_section,
)


def test_normalize_paper_keys_dedupes_and_strips_prefix():
    keys = normalize_paper_keys(["paper:abc12345", "ABC12345", "DEF67890", "bad", ""])
    assert keys == ["ABC12345", "DEF67890"]


def test_resolve_focus_section_maps_methods():
    assert resolve_focus_section("methodology") == "methods"
    assert resolve_focus_section("overview") is None


def test_execute_compare_papers_requires_two_keys():
    result = execute_compare_papers({"paper_keys": ["ABC12345"]}, owner="tester")
    assert result["exit_code"] == 1
    assert "At least two" in result["error"]


def test_execute_compare_papers_defers_when_more_than_three():
    keys = ["ABCD0001", "ABCD0002", "ABCD0003", "ABCD0004"]
    result = execute_compare_papers({"paper_keys": keys, "focus": "methods"}, owner="tester")
    assert result.get("defer_to_research") is True
    assert len(result["paper_keys"]) == 4


@patch("src.paper_summaries.load_cached_paper_summary_body", return_value=None)
@patch("src.zotero_client.fetch_paper_section_text")
@patch("src.zotero_catalog.load_catalog")
def test_gather_paper_slice_prefers_section(mock_catalog, mock_section, _mock_summary):
    mock_catalog.return_value = [{
        "zotero_key": "PAPER001",
        "title": "Paper One",
        "authors": "Author A",
        "year": "2024",
        "abstract": "Abstract text.",
    }]
    mock_section.return_value = ("Methods body here.", "", {"matched_slug": "methods"})

    slice_ = gather_paper_slice("tester", "PAPER001", focus="methods")

    assert slice_["source_tier"] == "section"
    assert "Methods body" in slice_["content"]


@patch("src.paper_compare._catalog_row")
def test_format_compare_output_includes_taxonomy(mock_row):
    mock_row.return_value = {
        "title": "Alpha",
        "authors": "A",
        "year": "2021",
    }
    slices = [
        {
            "zotero_key": "AFOLD001",
            "title": "Alpha",
            "authors": "A",
            "year": "2021",
            "source_tier": "section",
            "source_label": "Methods",
            "content": "Uses MSA.",
            "note": "",
        },
        {
            "zotero_key": "ESMF001",
            "title": "Beta",
            "authors": "B",
            "year": "2023",
            "source_tier": "summary",
            "source_label": "Deep Research summary",
            "content": "Language model only.",
            "note": "",
        },
    ]
    with patch("src.paper_compare._catalog_row", mock_row):
        out = format_compare_output(slices, focus="methods", question="Compare pipelines")
    assert "# Paper comparison" in out
    assert "Compare pipelines" in out
    assert "AFOLD001" in out
    assert "ESMF001" in out
    assert "## At a glance" in out
    assert "Suggested graph edges" in out or "suggest_link" in out


def test_execute_compare_papers_sync_three_papers(tmp_path, monkeypatch):
    owner = "tester"
    zdir = tmp_path / "zotero" / "users" / owner
    zdir.mkdir(parents=True)
    rows = [
        {"zotero_key": "PAPER001", "title": "One", "authors": "A", "year": "2020", "abstract": "A1"},
        {"zotero_key": "PAPER002", "title": "Two", "authors": "B", "year": "2021", "abstract": "B1"},
        {"zotero_key": "PAPER003", "title": "Three", "authors": "C", "year": "2022", "abstract": "C1"},
    ]
    (zdir / "catalog.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("src.zotero_catalog._owner_dir", lambda o: tmp_path / "zotero" / "users" / o)

    with patch("src.zotero_client.fetch_paper_section_text", return_value=("", "no pdf", {})):
        with patch("src.paper_summaries.load_cached_paper_summary_body", return_value=None):
            result = execute_compare_papers(
                {"paper_keys": ["PAPER001", "PAPER002", "PAPER003"], "focus": "methods"},
                owner=owner,
            )

    assert result["exit_code"] == 0
    assert result.get("defer_to_research") is None
    assert len(result["slices"]) == COMPARE_SYNC_MAX_PAPERS
    assert "One" in result["output"]
    assert "Three" in result["output"]
