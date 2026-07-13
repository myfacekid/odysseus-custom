"""Tests for LDR runner orchestration (mocked LDR stack)."""

from unittest.mock import MagicMock

import pytest

from src.research.ldr_runner import (
    LdrResearchNotReadyError,
    _harvest_partial_gather_links,
    _resolve_ldr_search_tool,
    run_ldr_research,
)
from src.research.ldr_session import LdrResearchSession


def _mock_content_enrichment(monkeypatch):
    async def fake_content_enrichment(**kwargs):
        return ""

    monkeypatch.setattr(
        "src.research.ldr_content_enrich.run_ldr_content_enrichment",
        fake_content_enrichment,
    )


def test_resolve_ldr_search_tool_aliases():
    assert _resolve_ldr_search_tool("searxng") == "searxng"
    assert _resolve_ldr_search_tool("brave") == "brave"
    assert _resolve_ldr_search_tool(None) == "searxng"


@pytest.mark.asyncio
async def test_run_ldr_research_raises_when_stack_missing(monkeypatch):
    monkeypatch.setattr("src.research.ldr_runner.ldr_stack_available", lambda: False)
    with pytest.raises(LdrResearchNotReadyError, match="not installed"):
        await run_ldr_research(
            "test question",
            llm_endpoint="http://localhost/v1/chat/completions",
            llm_model="test",
        )


@pytest.mark.asyncio
async def test_run_ldr_research_end_to_end_mocked(monkeypatch):
    monkeypatch.setattr("src.research.ldr_runner.ldr_stack_available", lambda: True)

    holder: dict = {}
    events = []

    async def fake_plan(**kwargs):
        from src.research_retrieval_plan import derive_retrieval_plan_fallback

        plan = derive_retrieval_plan_fallback(kwargs["question"], [], research_mode="literature_review")
        return plan, "plan text"

    async def fake_synthesis(**kwargs):
        return "## Executive Summary\n\nMock report [1].\n\n## References\n\n[1] Test."

    monkeypatch.setattr("src.research.ldr_runner.build_retrieval_plan", fake_plan)
    monkeypatch.setattr("src.research.ldr_runner.synthesize_academic_report", fake_synthesis)
    monkeypatch.setattr(
        "src.research.ldr_runner.build_langchain_chat_model",
        lambda **kwargs: MagicMock(),
    )

    _mock_content_enrichment(monkeypatch)

    def fake_gather(**kwargs):
        return [
            {
                "title": "Collected paper",
                "link": "https://doi.org/10.5555/collected",
                "snippet": "Important finding",
                "source_engine": "pubmed",
            }
        ]

    async def fake_to_thread(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    monkeypatch.setattr("src.research.ldr_runner.asyncio.to_thread", fake_to_thread)
    monkeypatch.setattr("src.research.ldr_runner._run_ldr_gather_sync", fake_gather)

    report = await run_ldr_research(
        "What is protein folding?",
        llm_endpoint="http://localhost/v1/chat/completions",
        llm_model="test",
        progress_callback=events.append,
        include_preprints=True,
        include_zotero=False,
        include_knowledge=False,
        result_holder=holder,
    )

    assert "Mock report" in report
    session = holder.get("researcher")
    assert isinstance(session, LdrResearchSession)
    assert len(session.evidence_registry) >= 1
    phases = [e.get("phase") for e in events]
    assert "planning" in phases
    assert "searching" in phases
    assert "synthesizing" in phases


@pytest.mark.asyncio
async def test_run_ldr_research_honors_preprint_toggle(monkeypatch):
    monkeypatch.setattr("src.research.ldr_runner.ldr_stack_available", lambda: True)

    async def fake_plan(**kwargs):
        from src.research_retrieval_plan import derive_retrieval_plan_fallback

        plan = derive_retrieval_plan_fallback(kwargs["question"], [], research_mode="literature_review")
        return plan, ""

    async def fake_synthesis_async(**kwargs):
        return "report"

    monkeypatch.setattr("src.research.ldr_runner.build_retrieval_plan", fake_plan)
    monkeypatch.setattr("src.research.ldr_runner.synthesize_academic_report", fake_synthesis_async)
    monkeypatch.setattr(
        "src.research.ldr_runner.build_langchain_chat_model",
        lambda **kwargs: MagicMock(),
    )

    def fake_gather(**kwargs):
        return [
            {
                "title": "Arxiv preprint",
                "link": "https://arxiv.org/abs/2301.00001",
                "snippet": "preprint",
                "source_engine": "arxiv",
            },
            {
                "title": "Journal",
                "link": "https://doi.org/10.5555/journal",
                "snippet": "peer reviewed",
                "source_engine": "pubmed",
            },
        ]

    async def fake_to_thread(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    monkeypatch.setattr("src.research.ldr_runner.asyncio.to_thread", fake_to_thread)
    monkeypatch.setattr("src.research.ldr_runner._run_ldr_gather_sync", fake_gather)

    _mock_content_enrichment(monkeypatch)

    holder: dict = {}
    await run_ldr_research(
        "folding",
        llm_endpoint="http://localhost/v1/chat/completions",
        llm_model="test",
        include_preprints=False,
        result_holder=holder,
    )
    session = holder["researcher"]
    urls = [s.url for s in session.evidence_registry.sources()]
    assert all("arxiv.org" not in u for u in urls)
    assert any("doi.org" in u for u in urls)


@pytest.mark.asyncio
async def test_run_ldr_research_emits_source_rejected_events(monkeypatch):
    monkeypatch.setattr("src.research.ldr_runner.ldr_stack_available", lambda: True)
    events = []

    async def fake_plan(**kwargs):
        from src.research_retrieval_plan import derive_retrieval_plan_fallback

        return derive_retrieval_plan_fallback(kwargs["question"], [], research_mode="literature_review"), ""

    async def fake_synthesis(**kwargs):
        return "report"

    monkeypatch.setattr("src.research.ldr_runner.build_retrieval_plan", fake_plan)
    monkeypatch.setattr("src.research.ldr_runner.synthesize_academic_report", fake_synthesis)
    monkeypatch.setattr("src.research.ldr_runner.build_langchain_chat_model", lambda **k: MagicMock())

    def fake_gather(**kwargs):
        return [
            {"title": "Preprint", "link": "https://arxiv.org/abs/1", "snippet": "p", "source_engine": "arxiv"},
            {"title": "Journal", "link": "https://doi.org/10.1/j", "snippet": "j", "source_engine": "pubmed"},
        ]

    async def fake_to_thread(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    monkeypatch.setattr("src.research.ldr_runner.asyncio.to_thread", fake_to_thread)
    monkeypatch.setattr("src.research.ldr_runner._run_ldr_gather_sync", fake_gather)

    _mock_content_enrichment(monkeypatch)

    await run_ldr_research(
        "folding",
        llm_endpoint="http://localhost/v1/chat/completions",
        llm_model="test",
        include_preprints=False,
        progress_callback=events.append,
    )
    reject_events = [e for e in events if e.get("event") == "source_rejected"]
    assert reject_events
    assert reject_events[0]["reason"] == "preprint_excluded"


def test_harvest_partial_gather_links_from_collector():
    collector = MagicMock()
    collector.results = [{"title": "A", "link": "https://a"}]
    system = MagicMock()
    system.all_links_of_system = None
    system.strategy.collector = collector

    links = _harvest_partial_gather_links({"system": system})
    assert len(links) == 1
    assert links[0]["title"] == "A"


@pytest.mark.asyncio
async def test_run_ldr_research_continues_on_gather_timeout_with_partial_links(monkeypatch):
    import asyncio

    monkeypatch.setattr("src.research.ldr_runner.ldr_stack_available", lambda: True)
    events = []

    async def fake_plan(**kwargs):
        from src.research_retrieval_plan import derive_retrieval_plan_fallback

        return derive_retrieval_plan_fallback(kwargs["question"], [], research_mode="literature_review"), ""

    async def fake_synthesis(**kwargs):
        return "## Summary\n\nPartial gather report [1]."

    monkeypatch.setattr("src.research.ldr_runner.build_retrieval_plan", fake_plan)
    monkeypatch.setattr("src.research.ldr_runner.synthesize_academic_report", fake_synthesis)
    monkeypatch.setattr("src.research.ldr_runner.build_langchain_chat_model", lambda **k: MagicMock())

    async def raise_timeout(coro, timeout=None):
        raise asyncio.TimeoutError()

    monkeypatch.setattr("src.research.ldr_runner.asyncio.wait_for", raise_timeout)
    monkeypatch.setattr(
        "src.research.ldr_runner._harvest_partial_gather_links",
        lambda state: [
            {"title": "Partial", "link": "https://doi.org/10.1/partial", "snippet": "text"}
        ],
    )

    _mock_content_enrichment(monkeypatch)

    holder: dict = {}
    report = await run_ldr_research(
        "What is Foldseek?",
        llm_endpoint="http://localhost/v1/chat/completions",
        llm_model="test",
        progress_callback=events.append,
        result_holder=holder,
    )
    assert "Partial gather report" in report
    session = holder["researcher"]
    assert len(session.evidence_registry) >= 1
    assert any(e.get("phase") == "warning" for e in events)

