"""Phase 5d — catalog vs live Zotero PDF staleness in seed preview."""

from src.research_seeds import _annotate_catalog_staleness, preview_seed_refs


def test_annotate_catalog_staleness_flags_missing_pdf(monkeypatch):
    previews = [{
        "in_catalog": True,
        "zotero_key": "STALE001",
        "has_pdf": False,
        "catalog_has_pdf": False,
    }]

    class FakeClient:
        pass

    monkeypatch.setattr(
        "src.zotero_client.resolve_zotero_credentials",
        lambda owner: {"api_key": "k", "user_id": "u"},
    )
    monkeypatch.setattr("src.zotero_client.ZoteroClient", lambda *a, **k: FakeClient())
    monkeypatch.setattr(
        "src.research_seeds._live_has_pdf_for_key",
        lambda client, key: True,
    )

    _annotate_catalog_staleness(previews, "tester")
    assert previews[0]["live_has_pdf"] is True
    assert previews[0]["catalog_stale"] is True
    assert previews[0]["has_pdf"] is True


def test_preview_seed_refs_skips_live_check_without_credentials(tmp_path, monkeypatch):
    monkeypatch.setattr("src.zotero_catalog.ZOTERO_ROOT", tmp_path / "zotero")
    from tests.test_research_phase2 import _write_catalog

    owner = "tester"
    _write_catalog(tmp_path, owner, [{
        "zotero_key": "PAPER123",
        "title": "Paper",
        "doi": "10.1234/abc",
        "has_pdf": False,
        "item_type": "journalArticle",
    }])
    monkeypatch.setattr("src.zotero_client.resolve_zotero_credentials", lambda owner: None)

    previews = preview_seed_refs(owner, ["PAPER123"])
    assert previews[0]["catalog_stale"] is False
    assert previews[0]["live_has_pdf"] is None
