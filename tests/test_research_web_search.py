"""Phase 1a — shared web search layer for Deep Research."""

from src.research_web_search import (
    ResearchSearchOutcome,
    apply_academic_query_templates,
    enhance_query_for_kind,
    infer_search_kind,
    infer_time_filter,
    rank_similar_paper_search_results,
    similar_paper_queries_from_findings,
    similar_paper_queries_from_seeds,
    similar_source_from_url,
)


def test_infer_search_kind_by_round():
    assert infer_search_kind(1) == "discovery"
    assert infer_search_kind(2) == "gap_filling"


def test_enhance_discovery_query_adds_scholarly_terms():
    out = enhance_query_for_kind("CRISPR gene editing outcomes", "discovery")
    assert "systematic review" in out.lower() or "pubmed" in out.lower()


def test_enhance_similar_papers_query():
    out = enhance_query_for_kind("Attention Is All You Need", "similar_papers")
    assert "scholar.google" in out.lower() or "pubmed" in out.lower()


def test_enhance_similar_papers_doi_prefers_pubmed():
    out = enhance_query_for_kind("10.1234/example.doi", "similar_papers")
    assert "pubmed" in out.lower()


def test_similar_paper_queries_from_seeds():
    seeds = [
        {
            "is_seed": True,
            "title": "Highly accurate protein structure prediction with AlphaFold",
            "doi_or_id": "10.1038/s41586-021-03819-2",
            "authors": "Jumper, John; Evans, Richard",
        },
        {
            "is_seed": True,
            "title": "Evolutionary-scale prediction with ESM3",
            "summary": "ESM3 generative protein language model",
        },
    ]
    queries = similar_paper_queries_from_seeds(
        seeds,
        "Compare AlphaFold and ESM3",
        limit=8,
    )
    joined = " | ".join(queries).lower()
    assert "pubmed" in joined
    assert "scholar.google" in joined
    assert "intitle:" in joined or "10.1038" in joined
    assert "jumper" not in joined
    assert "evans" not in joined
    assert "cited by" not in joined


def test_paper_lookup_queries_use_title_not_authors():
    finding = {
        "title": "Highly accurate protein structure prediction with AlphaFold",
        "doi_or_id": "10.1038/s41586-021-03819-2",
        "authors": "Jumper, John; Evans, Richard",
        "year": "2021",
    }
    from src.research_web_search import paper_lookup_queries_for_finding

    queries = paper_lookup_queries_for_finding(finding)
    joined = " | ".join(queries).lower()
    assert "alphafold" in joined or "10.1038" in joined
    assert "jumper" not in joined


def test_is_scholar_author_profile_url():
    from src.research_web_search import is_scholar_author_profile_url

    assert is_scholar_author_profile_url(
        "https://scholar.google.com/citations?user=abc&hl=en"
    )
    assert not is_scholar_author_profile_url(
        "https://scholar.google.com/scholar?q=alphafold"
    )


def test_rank_similar_paper_search_results_prefers_pubmed():
    results = [
        {"url": "https://www.semanticscholar.org/paper/abc", "title": "S2 hit", "snippet": "protein structure"},
        {"url": "https://pubmed.ncbi.nlm.nih.gov/123/", "title": "PubMed hit", "snippet": "protein structure"},
        {"url": "https://scholar.google.com/scholar?q=structure", "title": "Scholar hit", "snippet": "protein structure"},
    ]
    ranked = rank_similar_paper_search_results("protein structure prediction", results)
    assert "pubmed" in ranked[0]["url"]


def test_similar_source_from_url():
    assert similar_source_from_url("https://pubmed.ncbi.nlm.nih.gov/1/") == "pubmed"
    assert similar_source_from_url("https://scholar.google.com/scholar?q=x") == "google_scholar"


def test_apply_templates_dedupes():
    queries = apply_academic_query_templates(
        ["alpha outcomes", "alpha outcomes"],
        search_kind="discovery",
    )
    assert len(queries) == 1


def test_gap_filling_pulls_plan_subquestions():
    plan = "Sub-questions: What RCTs exist?; What are long-term effects?\nKey topics: x"
    queries = apply_academic_query_templates(
        ["extra gap query"],
        search_kind="gap_filling",
        research_plan=plan,
    )
    joined = " | ".join(queries).lower()
    assert "rct" in joined or "long-term" in joined


def test_similar_paper_queries_from_findings():
    findings = [
        {"title": "Transformer Architecture", "doi_or_id": "10.1234/abc.def"},
    ]
    queries = similar_paper_queries_from_findings(findings, limit=2)
    joined = " | ".join(queries).lower()
    assert "pubmed" in joined
    assert "scholar.google" in joined
    assert "10.1234" in joined


def test_infer_time_filter_matches_chat_heuristics():
    assert infer_time_filter("latest news on vaccines") == "day"
    assert infer_time_filter("recent peer-reviewed studies on X", "gap_filling") == "year"


def test_research_web_search_disabled(monkeypatch):
    monkeypatch.setattr(
        "src.research_web_search.resolve_research_provider",
        lambda override=None: "disabled",
    )
    from src.research_web_search import research_web_search

    outcome = research_web_search("anything")
    assert outcome.results == []
    assert outcome.error
    assert "disabled" in outcome.error.lower()


def test_research_web_search_uses_shared_ranking(monkeypatch):
    hits = [{"url": "https://pubmed.ncbi.nlm.nih.gov/1", "title": "Study", "snippet": "x"}]

    def _fake_call(provider, query, count, time_filter=None):
        return list(hits)

    monkeypatch.setattr("src.research_web_search.resolve_research_provider", lambda override=None: "brave")
    monkeypatch.setattr("services.search.core._call_provider", _fake_call)
    monkeypatch.setattr("services.search.core._build_provider_chain", lambda primary: ["brave"])
    monkeypatch.setattr(
        "services.search.ranking.rank_search_results",
        lambda query, results: results,
    )

    from src.research_web_search import research_web_search

    outcome = research_web_search("systematic review sleep", search_kind="discovery")
    assert isinstance(outcome, ResearchSearchOutcome)
    assert outcome.provider == "brave"
    assert len(outcome.results) == 1
    assert outcome.error is None
