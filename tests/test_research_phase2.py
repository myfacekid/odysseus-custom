"""Phase 2 — seed papers and similar-paper discovery."""

import json
from unittest.mock import patch

from src.research_seeds import (
    normalize_seed_ref,
    resolve_seed_catalog_rows,
    seed_findings_from_refs,
)
from src.research_similar_papers import (
    _finding_from_openalex_work,
    _finding_from_s2_paper,
    similar_papers_from_seeds,
)


def _write_catalog(tmp_path, owner, rows):
    zdir = tmp_path / "zotero" / "users" / owner
    zdir.mkdir(parents=True)
    (zdir / "catalog.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n",
        encoding="utf-8",
    )
    (zdir / "manifest.json").write_text(
        json.dumps({"synced_at": "2026-01-01T00:00:00Z"}) + "\n",
        encoding="utf-8",
    )


def test_normalize_seed_ref():
    assert normalize_seed_ref("paper:abc12345") == "ABC12345"
    assert normalize_seed_ref("doi:10.1234/abc") == "10.1234/abc"
    assert normalize_seed_ref("https://doi.org/10.1234/xyz") == "10.1234/xyz"


def test_resolve_seed_catalog_rows(tmp_path, monkeypatch):
    monkeypatch.setattr("src.zotero_catalog.ZOTERO_ROOT", tmp_path / "zotero")
    owner = "tester"
    _write_catalog(tmp_path, owner, [
        {
            "zotero_key": "PAPER123",
            "title": "Attention",
            "doi": "10.1234/abc",
            "abstract": "Transformers.",
            "has_pdf": True,
            "item_type": "journalArticle",
        },
    ])
    rows, missing = resolve_seed_catalog_rows(owner, ["PAPER123", "MISSING1", "10.1234/abc"])
    assert len(rows) == 1
    assert rows[0]["zotero_key"] == "PAPER123"
    assert "MISSING1" in missing


def test_seed_findings_from_refs(tmp_path, monkeypatch):
    monkeypatch.setattr("src.zotero_catalog.ZOTERO_ROOT", tmp_path / "zotero")
    owner = "tester"
    _write_catalog(tmp_path, owner, [
        {
            "zotero_key": "SEED1",
            "title": "Seed paper",
            "abstract": "Abstract text.",
            "has_pdf": False,
            "item_type": "journalArticle",
            "url": "https://example.com/seed",
        },
    ])
    monkeypatch.setattr(
        "src.zotero_client.resolve_zotero_credentials",
        lambda o="": {"api_key": "k", "user_id": "1"},
    )
    outcome = seed_findings_from_refs(owner, ["SEED1"])
    assert len(outcome.findings) == 1
    assert outcome.findings[0]["is_seed"] is True
    assert outcome.findings[0]["paper_key"] == "SEED1"


def test_openalex_work_to_finding():
    work = {
        "title": "Related Study",
        "doi": "https://doi.org/10.5555/related",
        "publication_year": 2023,
        "authorships": [{"author": {"display_name": "Smith"}}],
        "type": "journal-article",
        "abstract_inverted_index": {"Hello": [0], "world": [1]},
    }
    f = _finding_from_openalex_work(work)
    assert f["title"] == "Related Study"
    assert f["similar_source"] == "openalex"
    assert "Hello world" in f["evidence"]


def test_semantic_scholar_paper_to_finding():
    paper = {
        "title": "Recommended Paper",
        "year": 2022,
        "abstract": "Important follow-up work.",
        "externalIds": {"DOI": "10.5555/rec"},
        "authors": [{"name": "Lee"}],
        "citationCount": 42,
    }
    f = _finding_from_s2_paper(paper)
    assert f["similar_source"] == "semantic_scholar"
    assert f["citation_count"] == 42


def test_similar_papers_from_seeds_merged(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "src.research_similar_papers.openalex_similar_works",
        lambda **k: [_finding_from_openalex_work({"title": "OA Paper", "doi": "https://doi.org/10.1/oa"})],
    )
    monkeypatch.setattr(
        "src.research_similar_papers.semantic_scholar_recommendations",
        lambda **k: [_finding_from_s2_paper({"title": "S2 Paper", "abstract": "x", "externalIds": {}})],
    )
    seeds = [{"is_seed": True, "paper_key": "SEED1", "doi_or_id": "10.1234/seed", "title": "Seed"}]
    outcome = similar_papers_from_seeds(seeds, total_limit=5)
    assert len(outcome.findings) == 2
    assert outcome.openalex_count >= 1
    assert outcome.semantic_scholar_count >= 1
