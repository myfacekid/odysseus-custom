"""Paper summary pipeline tests (Paper Token Retrieval R2)."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src import knowledge_graph as kg
from src.paper_summaries import (
    PAPER_SUMMARY_EDGE_KIND,
    PAPER_SUMMARY_EDGE_SOURCE,
    build_summary_markdown,
    collect_papers_for_summary,
    sync_paper_summaries_on_complete,
)


@pytest.fixture
def compare_fixture():
    path = Path(__file__).parent / "fixtures" / "research" / "compare_alphafold_esm.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_collect_papers_for_summary_prefers_seeds(compare_fixture):
    papers = collect_papers_for_summary(compare_fixture)
    keys = [p["zotero_key"] for p in papers]
    assert keys[:2] == ["AFOLD001", "ESMF001"]
    assert "AFOLD001" in keys


def test_build_summary_markdown_includes_sections(compare_fixture):
    papers = collect_papers_for_summary(compare_fixture)
    body = build_summary_markdown(
        papers[0],
        session_id="fixture-compare-alphafold-esm",
        research_query=compare_fixture["query"],
        generated_at="2026-06-08T12:00:00+00:00",
    )
    assert "## Focus / claim" in body
    assert "## Method" in body
    assert "## Key results" in body
    assert "AFOLD001" in body
    assert "AlphaFold" in body


def test_pipeline_edge_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(kg, "KNOWLEDGE_ROOT", tmp_path / "knowledge")
    owner = "tester"
    paper_id = kg.node_id("paper", "PAPER1")
    doc_id = kg.node_id("document", "doc-uuid-1")
    kg.save_graph(owner, {
        paper_id: {"id": paper_id, "type": "paper", "title": "T", "snippet": "s", "meta": {}},
        doc_id: {"id": doc_id, "type": "document", "title": "Summary", "snippet": "s", "meta": {}},
    }, [])

    result = kg.add_pipeline_edge(
        owner,
        paper_id,
        doc_id,
        kind=PAPER_SUMMARY_EDGE_KIND,
        source=PAPER_SUMMARY_EDGE_SOURCE,
        generated_at="2026-06-08T12:00:00+00:00",
        research_session_id="sess-1",
        zotero_key="PAPER1",
    )
    assert result["ok"] is True

    manual = kg.load_manual_edges(owner)
    edge = next(e for e in manual if e.get("kind") == "summarizes")
    assert edge["from"] == paper_id
    assert edge["to"] == doc_id
    assert edge["generated_at"] == "2026-06-08T12:00:00+00:00"
    assert edge["zotero_key"] == "PAPER1"

    merged = kg.load_edges(owner)
    assert any(e.get("kind") == "summarizes" for e in merged)


def test_sync_paper_summaries_creates_edges_when_nodes_exist(tmp_path, monkeypatch, compare_fixture):
    monkeypatch.setattr(kg, "KNOWLEDGE_ROOT", tmp_path / "knowledge")
    owner = "fixture-user"
    for key in ("AFOLD001", "ESMF001"):
        pid = kg.node_id("paper", key)
        kg.save_graph(owner, {
            pid: {
                "id": pid,
                "type": "paper",
                "title": key,
                "snippet": "seed",
                "meta": {"zotero_key": key},
            }
        }, [])

    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = None

    with patch("core.database.SessionLocal", return_value=mock_db), patch(
        "core.database.Document", MagicMock(),
    ), patch("core.database.DocumentVersion", MagicMock()), patch(
        "src.knowledge_sync.after_document_change", lambda owner: None,
    ):
        result = sync_paper_summaries_on_complete(
            owner,
            compare_fixture["session_id"],
            compare_fixture,
        )

    assert result["ok"] is True
    assert len(result["summaries"]) >= 2
    manual = kg.load_manual_edges(owner)
    assert not any(e.get("kind") == "summarizes" for e in manual)
    from src.pending_graph_edges import load_pending_edges

    pending = load_pending_edges(owner)
    assert sum(1 for p in pending if p.get("kind") == "summarizes") >= 2
    mock_db.commit.assert_called()


def test_load_cached_summary_in_read(tmp_path, monkeypatch):
    monkeypatch.setattr(kg, "KNOWLEDGE_ROOT", tmp_path / "knowledge")
    monkeypatch.setattr("src.zotero_catalog.ZOTERO_ROOT", tmp_path / "zotero")
    owner = "tester"
    zdir = tmp_path / "zotero" / "users" / owner
    zdir.mkdir(parents=True)
    (zdir / "catalog.jsonl").write_text(
        json.dumps({
            "zotero_key": "PAPER1",
            "title": "Test Paper",
            "authors": "Author",
            "year": "2024",
            "abstract": "Abstract line.",
            "has_pdf": True,
            "item_type": "journalArticle",
        }) + "\n",
        encoding="utf-8",
    )
    (zdir / "manifest.json").write_text("{}", encoding="utf-8")

    with patch("src.knowledge_graph.OBSIDIAN_INTEGRATION_ENABLED", False):
        kg.rebuild_owner_graph(owner)

    with patch(
        "src.paper_summaries.load_cached_paper_summary_body",
        return_value={
            "body": "## Key results\nCached finding from DR.",
            "generated_at": "2026-06-08T12:00:00+00:00",
            "document_id": "doc-1",
        },
    ), patch(
        "src.zotero_client.fetch_paper_pdf_text",
        side_effect=AssertionError("should use cached summary"),
    ):
        out = kg.execute_knowledge_tool({"action": "read", "id": "paper:PAPER1"}, owner=owner)

    assert out["exit_code"] == 0
    assert "Research summary (cached" in out["output"]
    assert "Cached finding from DR" in out["output"]
