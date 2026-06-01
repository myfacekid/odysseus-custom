"""Tests for academic-only deep research filtering."""

from src.deep_research import (
    filter_and_rank_academic_results,
    _is_preprint_url,
    _is_academic_url,
    ACADEMIC_CATEGORY,
    DeepResearcher,
)


def test_academic_category_constant():
    assert ACADEMIC_CATEGORY == "academic"


def test_is_preprint_url():
    assert _is_preprint_url("https://arxiv.org/abs/2301.00001")
    assert _is_preprint_url("https://www.biorxiv.org/content/10.1101/example")
    assert not _is_preprint_url("https://doi.org/10.1234/example")


def test_is_academic_url():
    assert _is_academic_url("https://pubmed.ncbi.nlm.nih.gov/12345678/")
    assert _is_academic_url("https://doi.org/10.1234/example")
    assert _is_academic_url("https://example.edu/paper.pdf")
    assert not _is_academic_url("https://random-blog.example.com/post")


def test_filter_excludes_preprints_when_disabled():
    results = [
        {"url": "https://arxiv.org/abs/2301.00001", "title": "Preprint on X"},
        {"url": "https://pubmed.ncbi.nlm.nih.gov/12345678/", "title": "Peer-reviewed study"},
        {"url": "https://doi.org/10.1234/example", "title": "Journal article"},
    ]
    filtered = filter_and_rank_academic_results(results, include_preprints=False)
    urls = [r["url"] for r in filtered]
    assert "https://arxiv.org/abs/2301.00001" not in urls
    assert any("pubmed" in u or "doi.org" in u for u in urls)


def test_filter_includes_preprints_when_enabled():
    results = [
        {"url": "https://arxiv.org/abs/2301.00001", "title": "Preprint on X"},
        {"url": "https://pubmed.ncbi.nlm.nih.gov/12345678/", "title": "Peer-reviewed study"},
    ]
    filtered = filter_and_rank_academic_results(results, include_preprints=True)
    urls = [r["url"] for r in filtered]
    assert "https://arxiv.org/abs/2301.00001" in urls


def test_peer_reviewed_ranked_above_preprints():
    results = [
        {"url": "https://arxiv.org/abs/2301.00001", "title": "Preprint"},
        {"url": "https://pubmed.ncbi.nlm.nih.gov/12345678/", "title": "Systematic review of outcomes"},
    ]
    filtered = filter_and_rank_academic_results(results, include_preprints=True)
    assert "pubmed" in filtered[0]["url"]


def test_deep_researcher_defaults_to_academic():
    r = DeepResearcher(
        llm_endpoint="http://local.test/v1/chat/completions",
        llm_model="local-model",
    )
    assert r.category == "academic"
    assert r.include_preprints is True
