"""Tests for Zotero local metadata catalog."""

import json

from src.zotero_catalog import (
    _catalog_row_from_item,
    _collection_matches,
    catalog_path,
    catalog_row_to_library_item,
    library_items_from_catalog,
    load_catalog,
    search_catalog,
    sync_zotero_catalog,
)


def test_catalog_row_from_item(tmp_path, monkeypatch):
    monkeypatch.setattr("src.zotero_catalog.ZOTERO_ROOT", tmp_path / "zotero")
    row = _catalog_row_from_item(
        {
            "key": "ABC123",
            "data": {
                "key": "ABC123",
                "itemType": "journalArticle",
                "title": "Attention Is All You Need",
                "creators": [{"firstName": "Ashish", "lastName": "Vaswani"}],
                "date": "2017",
                "DOI": "10.48550/arXiv.1706.03762",
                "abstractNote": "Transformers replace recurrence.",
                "collections": ["COL1"],
            },
        },
        path_by_key={"COL1": "Projects / ML"},
        user_id="12345",
    )
    assert row["zotero_key"] == "ABC123"
    assert row["title"] == "Attention Is All You Need"
    assert "Vaswani" in row["authors"]
    assert row["year"] == "2017"
    assert row["collection_paths"] == ["Projects / ML"]


def test_search_catalog_filters_collection(tmp_path, monkeypatch):
    monkeypatch.setattr("src.zotero_catalog.ZOTERO_ROOT", tmp_path / "zotero")
    owner = "tester"
    owner_dir = tmp_path / "zotero" / "users" / owner
    owner_dir.mkdir(parents=True)
    rows = [
        {
            "zotero_key": "A1",
            "title": "AlphaFold",
            "authors": "Jumper",
            "collection_keys": ["ML"],
            "collection_paths": ["Projects / ML"],
        },
        {
            "zotero_key": "B1",
            "title": "Other Paper",
            "authors": "Smith",
            "collection_keys": ["READ"],
            "collection_paths": ["Reading"],
        },
    ]
    catalog_path(owner).write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n",
        encoding="utf-8",
    )
    (owner_dir / "collections.json").write_text(
        json.dumps([
            {"key": "ML", "path": "Projects / ML", "name": "ML"},
            {"key": "READ", "path": "Reading", "name": "Reading"},
        ]),
        encoding="utf-8",
    )

    hits = search_catalog(owner, query="", collection="Projects / ML", limit=10)
    assert len(hits) == 1
    assert hits[0]["zotero_key"] == "A1"


def test_collection_matches_partial_path():
    row = {"collection_paths": ["Projects / ML"], "collection_keys": ["MLKEY"]}
    assert _collection_matches(row, "projects / ml", {"MLKEY": "Projects / ML"})
    assert _collection_matches(row, "MLKEY", {"MLKEY": "Projects / ML"})
    assert not _collection_matches(row, "Reading", {"MLKEY": "Projects / ML"})


def test_sync_writes_catalog(tmp_path, monkeypatch):
    monkeypatch.setattr("src.zotero_catalog.ZOTERO_ROOT", tmp_path / "zotero")
    monkeypatch.setattr("src.knowledge_sync.after_zotero_sync", lambda owner: None)

    class FakeClient:
        def list_collections(self):
            return [{"key": "C1", "path": "Reading", "name": "Reading", "parent": ""}]

        _headers = {}

        def _url(self, path):
            return f"https://example.test{path}"

    parent = {
        "key": "PARENT",
        "data": {
            "key": "PARENT",
            "itemType": "journalArticle",
            "title": "Sample Paper",
            "creators": [],
            "collections": ["C1"],
        },
    }
    pdf_child = {
        "key": "PDF1",
        "data": {
            "key": "PDF1",
            "itemType": "attachment",
            "contentType": "application/pdf",
            "title": "Full Text PDF",
            "parentItem": "PARENT",
            "linkMode": "imported_file",
        },
    }

    monkeypatch.setattr(
        "src.zotero_catalog.resolve_zotero_credentials",
        lambda owner="": {"api_key": "k", "user_id": "1"},
    )
    monkeypatch.setattr("src.zotero_catalog.ZoteroClient", lambda *a, **k: FakeClient())
    monkeypatch.setattr(
        "src.zotero_catalog._fetch_all_catalog_items",
        lambda client, max_items=5000: ([parent], {"PARENT": [pdf_child]}, []),
    )

    result = sync_zotero_catalog("tester")
    assert result["ok"] is True
    assert result["items"] == 1
    loaded = load_catalog("tester")
    assert len(loaded) == 1
    assert loaded[0]["title"] == "Sample Paper"
    assert loaded[0]["zotero_key"] == "PARENT"
    assert loaded[0]["has_pdf"] is True
    assert loaded[0]["pdf_attachment_key"] == "PDF1"
    assert loaded[0]["collection_paths"] == ["Reading"]


def test_legacy_attachment_rows_filtered_on_load(tmp_path, monkeypatch):
    monkeypatch.setattr("src.zotero_catalog.ZOTERO_ROOT", tmp_path / "zotero")
    owner = "tester"
    owner_dir = tmp_path / "zotero" / "users" / owner
    owner_dir.mkdir(parents=True)
    rows = [
        {"zotero_key": "BAD", "title": "Full Text PDF", "item_type": "attachment"},
        {"zotero_key": "GOOD", "title": "Real Paper", "item_type": "journalArticle"},
    ]
    catalog_path(owner).write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n",
        encoding="utf-8",
    )
    loaded = load_catalog(owner)
    assert len(loaded) == 1
    assert loaded[0]["zotero_key"] == "GOOD"


def test_catalog_row_to_library_item():
    item = catalog_row_to_library_item({
        "zotero_key": "ABC123",
        "title": "Attention Is All You Need",
        "authors": "Vaswani et al.",
        "year": "2017",
        "abstract": "Transformers replace recurrence.",
        "has_pdf": True,
        "url": "https://doi.org/10.48550/arXiv.1706.03762",
        "date_modified": "2024-01-15T12:00:00Z",
    })
    assert item["id"] == "zotero:ABC123"
    assert item["source"] == "zotero"
    assert item["language"] == "paper"
    assert item["session_name"] == "Zotero"
    assert item["has_pdf"] is True


def test_library_items_from_catalog_search(tmp_path, monkeypatch):
    monkeypatch.setattr("src.zotero_catalog.ZOTERO_ROOT", tmp_path / "zotero")
    owner = "alice"
    rows = [
        {"zotero_key": "A1", "title": "Machine Learning Basics", "authors": "Smith", "abstract": ""},
        {"zotero_key": "A2", "title": "Deep Networks", "authors": "Jones", "abstract": "neural nets"},
    ]
    catalog_path(owner).write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n",
        encoding="utf-8",
    )
    all_items = library_items_from_catalog(owner)
    assert len(all_items) == 2
    hits = library_items_from_catalog(owner, search="machine")
    assert len(hits) == 1
    assert hits[0]["zotero_key"] == "A1"
