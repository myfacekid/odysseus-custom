"""Tests for Zotero client helpers."""

from src.zotero_client import (
    mask_api_key,
    sources_to_zotero_items,
    zotero_item_to_finding,
    _format_authors,
    _extract_search_terms,
    _title_matches_query,
    _extract_pdf_text,
    _is_pdf_attachment,
    fetch_zotero_findings,
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
    assert not _is_pdf_attachment({"itemType": "note", "contentType": "text/html"})


def test_extract_pdf_text_from_bytes():
    import httpx
    r = httpx.get("https://arxiv.org/pdf/1706.03762.pdf", timeout=30, follow_redirects=True)
    r.raise_for_status()
    text = _extract_pdf_text(r.content)
    assert len(text) > 500
    assert "attention" in text.lower()


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
