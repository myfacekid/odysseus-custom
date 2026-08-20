"""Tests for Zotero client helpers."""

from src.zotero_client import (
    format_zotero_search_context,
    mask_api_key,
    sources_to_zotero_items,
    zotero_item_to_finding,
    _format_authors,
    _extract_search_terms,
    _title_matches_query,
    _extract_pdf_text,
    collapse_extracted_pdf_text,
    _is_pdf_attachment,
    _normalize_searchable_item,
    _expand_searchable_items,
    _summarize_top_level_items,
    fetch_zotero_findings,
    resolve_collection_match,
    ZoteroClient,
)


def test_mask_api_key():
    assert mask_api_key("dvM7Bx5ZUOBwT45zfoK6zpeG") == "dvM7****"
    assert mask_api_key("") == ""


def test_format_authors():
    creators = [
        {"firstName": "Ashish", "lastName": "Vaswani"},
        {"firstName": "Noam", "lastName": "Shazeer"},
    ]
    assert "Vaswani" in _format_authors(creators)


def test_zotero_item_to_finding():
    item = {
        "key": "ABC123",
        "data": {
            "itemType": "journalArticle",
            "title": "Attention Is All You Need",
            "creators": [{"firstName": "Ashish", "lastName": "Vaswani"}],
            "date": "2017",
            "DOI": "10.48550/arXiv.1706.03762",
            "abstractNote": "The dominant sequence transduction models are based on complex recurrent or convolutional neural networks.",
        },
    }
    finding = zotero_item_to_finding(item, "20716472", pdf_text="")
    assert finding["title"] == "Attention Is All You Need"
    assert finding["source_type"] == "zotero"
    assert finding["zotero_key"] == "ABC123"
    assert "10.48550" in finding["doi_or_id"]


def test_sources_to_zotero_items():
    sources = [
        {"title": "Example Paper", "url": "https://doi.org/10.1234/example"},
    ]
    items = sources_to_zotero_items(sources)
    assert len(items) == 1
    assert items[0]["DOI"] == "10.1234/example"


def test_extract_search_terms_shortens_long_questions():
    q = (
        "What is the evidence for intermittent fasting on cardiovascular outcomes "
        "in adults? Include RCTs and systematic reviews."
    )
    short = _extract_search_terms(q)
    assert len(short) < len(q)
    assert "intermittent" in short
    assert "fasting" in short
    assert "what" not in short.split()


def test_title_matches_query():
    assert _title_matches_query(
        "Attention Is All You Need",
        "attention all need",
    )
    assert not _title_matches_query(
        "Highly accurate protein structure prediction with AlphaFold",
        "attention is all you need",
    )


def test_is_pdf_attachment():
    assert _is_pdf_attachment({"itemType": "attachment", "contentType": "application/pdf"})
    assert _is_pdf_attachment({
        "itemType": "attachment",
        "linkMode": "imported_url",
        "filename": "paper.pdf",
    })
    assert _is_pdf_attachment({
        "itemType": "attachment",
        "linkMode": "imported_file",
        "title": "Full Text PDF",
    })
    assert _is_pdf_attachment({
        "itemType": "attachment",
        "linkMode": "imported_url",
        "url": "https://arxiv.org/pdf/1706.03762",
    })
    assert _is_pdf_attachment({
        "itemType": "attachment",
        "linkMode": "linked_file",
        "path": "/home/user/papers/study.PDF",
    })
    assert not _is_pdf_attachment({"itemType": "note", "contentType": "text/html"})
    assert not _is_pdf_attachment({
        "itemType": "attachment",
        "linkMode": "imported_url",
        "contentType": "text/html",
        "title": "Snapshot",
    })


def test_extract_pdf_text_from_bytes():
    import httpx
    r = httpx.get("https://arxiv.org/pdf/1706.03762.pdf", timeout=30, follow_redirects=True)
    r.raise_for_status()
    text = _extract_pdf_text(r.content)
    assert len(text) > 500
    assert "attention" in text.lower()


def test_collapse_extracted_pdf_text_joins_visual_lines():
    raw = "Attention Is All You Need\nVaswani et al.\n\nAbstract\nWe propose a new network."
    out = collapse_extracted_pdf_text(raw)
    assert "Attention Is All You Need Vaswani et al." in out
    assert "\n\n" in out
    assert "Abstract We propose a new network." in out


def test_format_zotero_search_context():
    findings = [{
        "title": "AlphaFold",
        "url": "https://doi.org/10.1038/s41586-021-03819-2",
        "authors": "Jumper, J.",
        "year": "2021",
        "summary": "Protein structure prediction breakthrough.",
        "evidence": "Detailed methods and results.",
    }]
    text, sources = format_zotero_search_context(findings)
    assert "AlphaFold" in text
    assert sources and sources[0]["source"] == "zotero"


def test_format_zotero_search_context_empty():
    text, sources = format_zotero_search_context([])
    assert "No matching items" in text
    assert sources == []


def test_is_broad_library_query():
    from src.zotero_client import _is_broad_library_query
    assert _is_broad_library_query("my publications")
    assert _is_broad_library_query("")
    assert not _is_broad_library_query("transformer attention mechanisms")


def test_fetch_zotero_findings_seed_library(monkeypatch):
    """Small-library seed returns top items even when the query does not match."""
    class FakeClient:
        def search_items(self, query, limit=10, seed_library=False):
            if seed_library:
                return [{
                    "key": "ABC",
                    "data": {
                        "itemType": "journalArticle",
                        "title": "AlphaFold paper",
                        "date": "2021",
                    },
                }]
            return []

        def get_item(self, key):
            return None

        def get_children(self, key):
            return []

    def fake_resolve(owner=""):
        return {"api_key": "k", "user_id": "1"}

    monkeypatch.setattr("src.zotero_client.resolve_zotero_credentials", fake_resolve)
    monkeypatch.setattr("src.zotero_client.ZoteroClient", lambda *a, **k: FakeClient())
    monkeypatch.setattr(
        "src.zotero_client.zotero_item_to_finding",
        lambda item, uid, pdf_text="": {"title": item["data"]["title"], "zotero_key": item["key"]},
    )

    findings = fetch_zotero_findings(
        "unrelated cardiovascular fasting question",
        owner="user",
        limit=3,
        extract_pdfs=False,
        seed_library=True,
    )
    assert len(findings) == 1
    assert findings[0]["title"] == "AlphaFold paper"


def _sample_collections():
    return [
        {"key": "ROOT1", "name": "Projects", "path": "Projects", "parent": ""},
        {"key": "CHILD1", "name": "ML", "path": "Projects / ML", "parent": "ROOT1"},
        {"key": "CHILD2", "name": "NLP", "path": "Projects / NLP", "parent": "ROOT1"},
        {"key": "OTHER", "name": "Reading", "path": "Reading", "parent": ""},
    ]


def test_collection_subtree_keys():
    cols = _sample_collections()
    keys = ZoteroClient.collection_subtree_keys("ROOT1", cols)
    assert keys == ["ROOT1", "CHILD1", "CHILD2"]


def test_resolve_collection_match_by_path():
    cols = _sample_collections()
    key, err = resolve_collection_match("Projects / ML", cols)
    assert err is None
    assert key == "CHILD1"


def test_resolve_collection_match_by_key():
    cols = _sample_collections()
    key, err = resolve_collection_match("CHILD2", cols)
    assert err is None
    assert key == "CHILD2"


def test_resolve_collection_match_ambiguous():
    cols = _sample_collections()
    key, err = resolve_collection_match("project", cols)
    assert key is None
    assert err and "Multiple collections" in err


def test_resolve_collection_match_missing():
    cols = _sample_collections()
    key, err = resolve_collection_match("Nonexistent", cols)
    assert key is None
    assert err and "No collection matching" in err


def test_expand_searchable_items_includes_standalone_pdf():
    attachment = {
        "key": "ATT1",
        "data": {
            "itemType": "attachment",
            "contentType": "application/pdf",
            "filename": "my-paper.pdf",
        },
    }
    note = {
        "key": "NOTE1",
        "data": {"itemType": "note", "note": "Reading list for thesis"},
    }
    expanded = _expand_searchable_items([attachment, note], limit=5)
    assert len(expanded) == 2
    assert expanded[0]["data"]["title"] == "my-paper.pdf"
    assert "Reading list" in expanded[1]["data"]["title"]


def test_normalize_searchable_item_skips_non_pdf_attachment():
    html = {
        "key": "HTML1",
        "data": {"itemType": "attachment", "contentType": "text/html", "filename": "page.html"},
    }
    assert _normalize_searchable_item(html) is None


def test_summarize_top_level_items_attachment_hint():
    attachment = {
        "key": "ATT1",
        "data": {
            "itemType": "attachment",
            "contentType": "application/pdf",
            "filename": "paper.pdf",
        },
    }
    summary = _summarize_top_level_items([attachment], limit=5)
    assert "[attachment]" in summary
    assert "paper.pdf" in summary
    assert "Create Parent Item" in summary


def test_findings_from_items_extracts_pdf_from_standalone_attachment(monkeypatch):
    from src.zotero_client import findings_from_items

    attachment = {
        "key": "ATT1",
        "data": {
            "itemType": "attachment",
            "contentType": "application/pdf",
            "filename": "paper.pdf",
            "title": "paper.pdf",
        },
    }

    class FakeClient:
        def get_item(self, key):
            return attachment

        def get_children(self, key):
            return []

        def download_attachment_pdf(self, key, fallback_url=""):
            return "extracted pdf text"

    findings = findings_from_items(FakeClient(), "1", [attachment], extract_pdfs=True)
    assert len(findings) == 1
    assert findings[0]["title"] == "paper.pdf"
    assert "extracted pdf text" in findings[0]["evidence"]


def test_findings_from_items_resolves_child_pdf_to_parent(monkeypatch):
    from src.zotero_client import findings_from_items

    parent = {
        "key": "PARENT",
        "data": {
            "key": "PARENT",
            "itemType": "journalArticle",
            "title": "Attention Is All You Need",
            "creators": [{"lastName": "Vaswani"}],
        },
    }
    child = {
        "key": "PDF1",
        "data": {
            "key": "PDF1",
            "itemType": "attachment",
            "contentType": "application/pdf",
            "title": "Full Text PDF",
            "parentItem": "PARENT",
            "url": "https://example.test/paper.pdf",
        },
    }

    class FakeClient:
        def get_item(self, key):
            if key == "PARENT":
                return parent
            return child

        def get_children(self, key):
            return [child] if key == "PARENT" else []

        def download_attachment_pdf(self, key, fallback_url=""):
            assert key == "PDF1"
            return "pdf body text"

    findings = findings_from_items(FakeClient(), "1", [child], extract_pdfs=True)
    assert len(findings) == 1
    assert findings[0]["title"] == "Attention Is All You Need"
    assert "pdf body text" in findings[0]["evidence"]


def test_findings_from_items_uses_catalog_pdf_key(monkeypatch):
    from src.zotero_client import findings_from_items

    parent = {
        "key": "PARENT",
        "data": {
            "key": "PARENT",
            "itemType": "journalArticle",
            "title": "Sample Paper",
        },
    }
    catalog_rows = [{
        "zotero_key": "PARENT",
        "title": "Sample Paper",
        "pdf_attachment_key": "PDF1",
    }]

    class FakeClient:
        def get_item(self, key):
            return parent

        def get_children(self, key):
            return []

        def download_attachment_pdf(self, key, fallback_url=""):
            assert key == "PDF1"
            return "from catalog key"

    findings = findings_from_items(
        FakeClient(), "1", [parent], extract_pdfs=True, catalog_rows=catalog_rows,
    )
    assert "from catalog key" in findings[0]["evidence"]
