"""Phase 1b — catalog-first Zotero for Deep Research."""

import json

from src.research_zotero import (
    catalog_row_to_finding,
    findings_from_catalog_rows,
    research_zotero_findings,
    seed_catalog_rows,
)


def _write_catalog(tmp_path, owner, rows, synced_at="2026-01-01T00:00:00Z"):
    import src.zotero_catalog as zc

    monkey_root = tmp_path / "zotero"
    owner_dir = monkey_root / "users" / owner
    owner_dir.mkdir(parents=True)
    (owner_dir / "catalog.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n",
        encoding="utf-8",
    )
    (owner_dir / "manifest.json").write_text(
        json.dumps({"synced_at": synced_at, "user_id": "1"}) + "\n",
        encoding="utf-8",
    )


def test_seed_catalog_rows_prefers_pdf(tmp_path, monkeypatch):
    monkeypatch.setattr("src.zotero_catalog.ZOTERO_ROOT", tmp_path / "zotero")
    owner = "tester"
    _write_catalog(tmp_path, owner, [
        {"zotero_key": "A", "title": "No PDF", "has_pdf": False, "date_modified": "2026-01-02"},
        {"zotero_key": "B", "title": "Has PDF", "has_pdf": True, "date_modified": "2026-01-01"},
    ])
    rows = seed_catalog_rows(owner, 2)
    assert rows[0]["zotero_key"] == "B"


def test_catalog_row_to_finding_includes_paper_key():
    row = {
        "zotero_key": "PAPER123",
        "title": "Attention",
        "authors": "Vaswani et al.",
        "year": "2017",
        "doi": "10.1234/abc",
        "abstract": "Transformers.",
        "has_pdf": True,
        "url": "https://doi.org/10.1234/abc",
        "item_type": "journalArticle",
    }
    finding = catalog_row_to_finding(row, "20716472", pdf_text="full pdf text")
    assert finding["paper_key"] == "PAPER123"
    assert finding["zotero_source"] == "catalog"
    assert "full pdf text" in finding["evidence"]
    assert finding["pdf_extracted"] is True


def test_research_zotero_uses_catalog_before_live_api(tmp_path, monkeypatch):
    monkeypatch.setattr("src.zotero_catalog.ZOTERO_ROOT", tmp_path / "zotero")
    owner = "tester"
    _write_catalog(tmp_path, owner, [
        {
            "zotero_key": "MATCH1",
            "title": "Sleep and cognition",
            "authors": "Smith",
            "year": "2024",
            "abstract": "Sleep matters.",
            "has_pdf": False,
            "item_type": "journalArticle",
            "url": "https://example.com/sleep",
        },
    ])

    monkeypatch.setattr(
        "src.zotero_client.resolve_zotero_credentials",
        lambda o="": {"api_key": "k", "user_id": "1"},
    )
    monkeypatch.setattr(
        "src.zotero_client.fetch_paper_pdf_text",
        lambda owner, key, max_chars=15000: ("", "No PDF"),
    )

    class FailClient:
        def search_items(self, *a, **k):
            raise AssertionError("live API should not be called when catalog matches")

    monkeypatch.setattr("src.zotero_client.ZoteroClient", lambda *a, **k: FailClient())

    outcome = research_zotero_findings("sleep cognition", owner, limit=5)
    assert outcome.source == "catalog"
    assert len(outcome.findings) == 1
    assert outcome.findings[0]["zotero_key"] == "MATCH1"


def test_research_zotero_falls_back_to_live_api(tmp_path, monkeypatch):
        def search_items(self, query, limit=10, seed_library=False):
            return [{
                "key": "LIVE01",
                "data": {"itemType": "journalArticle", "title": "Live hit", "date": "2023"},
            }]

        def get_item(self, key):
            return None

        def get_children(self, key):
            return []

    monkeypatch.setattr(
        "src.zotero_client.resolve_zotero_credentials",
        lambda o="": {"api_key": "k", "user_id": "1"},
    )
    monkeypatch.setattr("src.zotero_client.ZoteroClient", lambda *a, **k: FakeClient())
    monkeypatch.setattr(
        "src.zotero_client.zotero_item_to_finding",
        lambda item, uid, pdf_text="": {
            "title": item["data"]["title"],
            "zotero_key": item["key"],
            "source_type": "zotero",
        },
    )

    outcome = research_zotero_findings("specific niche query", owner, limit=3)
    assert outcome.source == "live_api"
    assert outcome.findings[0]["zotero_key"] == "LIVE01"
    assert outcome.findings[0]["zotero_source"] == "live_api"


def test_research_zotero_does_not_seed_unrelated_when_query_misses(tmp_path, monkeypatch):
    monkeypatch.setattr("src.zotero_catalog.ZOTERO_ROOT", tmp_path / "zotero")
    owner = "tester"
    _write_catalog(tmp_path, owner, [
        {
            "zotero_key": "OTHER",
            "title": "Astronomy survey",
            "abstract": "Stars and galaxies",
            "has_pdf": True,
            "item_type": "journalArticle",
        },
    ])
    monkeypatch.setattr(
        "src.zotero_client.resolve_zotero_credentials",
        lambda o="": {"api_key": "k", "user_id": "1"},
    )

    class FailClient:
        def search_items(self, *a, **k):
            raise AssertionError("live API should not run when catalog is synced")

    monkeypatch.setattr("src.zotero_client.ZoteroClient", lambda *a, **k: FailClient())

    outcome = research_zotero_findings(
        "protein structure prediction alphafold",
        owner,
        limit=5,
        seed_library=True,
    )
    assert outcome.findings == []


def test_findings_from_catalog_rows_extracts_pdf(tmp_path, monkeypatch):
    monkeypatch.setattr("src.zotero_catalog.ZOTERO_ROOT", tmp_path / "zotero")
    owner = "tester"
    row = {
        "zotero_key": "PDF1",
        "title": "Paper",
        "authors": "A",
        "year": "2020",
        "abstract": "abs",
        "has_pdf": True,
        "item_type": "journalArticle",
        "url": "https://example.com",
    }
    monkeypatch.setattr(
        "src.zotero_client.resolve_zotero_credentials",
        lambda o="": {"api_key": "k", "user_id": "1"},
    )
    monkeypatch.setattr(
        "src.zotero_client.fetch_paper_pdf_text",
        lambda owner, key, max_chars=15000: ("Extracted PDF body", ""),
    )
    findings = findings_from_catalog_rows(owner, [row], extract_pdfs=True)
    assert "Extracted PDF body" in findings[0]["evidence"]
