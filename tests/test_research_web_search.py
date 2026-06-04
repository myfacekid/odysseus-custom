"""Phase 1a — shared web search layer for Deep Research."""

from src.research_web_search import (
    ResearchSearchOutcome,
    apply_academic_query_templates,
    enhance_query_for_kind,
    infer_search_kind,
    infer_time_filter,
    similar_paper_queries_from_findings,
)


def test_infer_search_kind_by_round():
    assert infer_search_kind(1) == "discovery"
    assert infer_search_kind(2) == "gap_filling"


def test_enhance_discovery_query_adds_scholarly_terms():
    out = enhance_query_for_kind("CRISPR gene editing outcomes", "discovery")
    assert "systematic review" in out.lower() or "pubmed" in out.lower()


def test_enhance_similar_papers_query():
    out = enhance_query_for_kind("Attention Is All You Need", "similar_papers")
    assert "cited by" in out.lower() or "related work" in out.lower()


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
    assert any("doi.org" in q or "cited by" in q.lower() for q in queries)


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
