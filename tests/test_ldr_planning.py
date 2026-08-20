"""Tests for LDR planning and agent context prompts."""

import pytest

from src.research.ldr_planning import (
    build_agent_context_prompt,
    parse_json_object,
    plan_has_scholarly_fields,
)
from src.research_retrieval_plan import ResearchRetrievalPlan, plan_to_display_text


def test_parse_json_object_strips_fences():
    raw = '```json\n{"sub_questions": ["a"], "scope": "balanced"}\n```'
    parsed = parse_json_object(raw)
    assert parsed["sub_questions"] == ["a"]


def test_plan_has_scholarly_fields():
    assert plan_has_scholarly_fields({"sub_questions": ["a"]})
    assert plan_has_scholarly_fields({"key_topics": ["t"]})
    assert plan_has_scholarly_fields({"success_criteria": "done"})
    assert not plan_has_scholarly_fields({"anchor_terms": ["x"]})
    assert not plan_has_scholarly_fields(None)


def test_build_agent_context_prompt_includes_toggles():
    plan = ResearchRetrievalPlan(
        anchor_terms=["foldseek"],
        avoid_topics=["gene ontology"],
        scope="narrow_compare",
    )
    prompt = build_agent_context_prompt(
        question="Compare Foldseek and ESM3",
        plan=plan,
        plan_display=plan_to_display_text(plan),
        research_mode="compare",
        include_preprints=False,
        include_zotero=True,
        include_knowledge=False,
        seed_findings=[{"title": "Seed", "content": "abstract", "is_seed": True}],
    )
    assert "peer-reviewed sources only" in prompt
    assert "search_zotero" in prompt
    assert "search_knowledge" not in prompt
    assert "gene ontology" in prompt
    assert "Compare Foldseek and ESM3" in prompt


@pytest.mark.asyncio
async def test_build_retrieval_plan_fallback_on_llm_failure(monkeypatch):
    from src.research.ldr_planning import build_retrieval_plan

    async def _boom(**kwargs):
        raise RuntimeError("offline")

    monkeypatch.setattr("src.llm_core.llm_call_async", _boom)
    plan, display, source = await build_retrieval_plan(
        question="ESM3 structure",
        llm_endpoint="http://localhost/v1/chat/completions",
        llm_model="test",
        research_mode="compare",
        seed_findings=[],
    )
    assert source == "fallback"
    assert plan.scope in ("narrow_compare", "balanced", "gap_analysis", "field_overview")
    assert plan.sub_questions
    assert plan.success_criteria
    assert isinstance(display, str)


@pytest.mark.asyncio
async def test_build_retrieval_plan_retries_incomplete_json(monkeypatch):
    from src.research.ldr_planning import build_retrieval_plan

    calls = {"n": 0}

    async def _llm(**kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return '{"anchor_terms": ["esm3"], "search_keywords": ["esm3"]}'
        return """{
          "sub_questions": ["How does ESM3 encode structure?"],
          "key_topics": ["structure representation"],
          "success_criteria": "Clear comparison.",
          "anchor_terms": ["esm3", "foldseek"],
          "search_keywords": ["esm3 structure"],
          "scope": "narrow_compare",
          "avoid_topics": ["gene ontology"]
        }"""

    monkeypatch.setattr("src.llm_core.llm_call_async", _llm)
    plan, _display, source = await build_retrieval_plan(
        question="Compare ESM3 and Foldseek",
        llm_endpoint="http://localhost/v1/chat/completions",
        llm_model="test",
        research_mode="compare",
        seed_findings=[],
    )
    assert calls["n"] == 2
    assert source == "llm"
    assert plan.sub_questions
    assert "gene ontology" in plan.avoid_topics


@pytest.mark.asyncio
async def test_build_retrieval_plan_fills_empty_key_topics(monkeypatch):
    from src.research.ldr_planning import build_retrieval_plan

    calls = {"n": 0}

    async def _llm(**kwargs):
        calls["n"] += 1
        return """{
          "search_keywords": ["SHOULD_NOT_REPLACE"],
          "key_topics": ["structure representation"],
          "sub_questions": ["How does Foldseek encode structure?"],
          "success_criteria": "A sourced comparison.",
          "anchor_terms": ["foldseek"],
          "avoid_topics": ["gene ontology"]
        }"""

    monkeypatch.setattr("src.llm_core.llm_call_async", _llm)
    plan, _display, source = await build_retrieval_plan(
        question="Compare Foldseek and ESM3",
        llm_endpoint="http://localhost/v1/chat/completions",
        llm_model="test",
        research_mode="compare",
        seed_findings=[],
        approved_plan={"search_keywords": ["foldseek structure"], "scope": "narrow_compare"},
    )
    assert calls["n"] >= 1
    assert source == "approved"
    assert plan.search_keywords == ["foldseek structure"]
    assert "structure representation" in plan.key_topics


@pytest.mark.asyncio
async def test_build_retrieval_plan_approved_missing_topics_heuristic_on_llm_failure(monkeypatch):
    from src.research.ldr_planning import build_retrieval_plan

    async def _boom(**kwargs):
        raise RuntimeError("offline")

    monkeypatch.setattr("src.llm_core.llm_call_async", _boom)
    plan, _display, source = await build_retrieval_plan(
        question="Compare Foldseek and ESM3",
        llm_endpoint="http://localhost/v1/chat/completions",
        llm_model="test",
        research_mode="compare",
        seed_findings=[],
        approved_plan={"search_keywords": ["foldseek structure"], "scope": "narrow_compare"},
    )
    assert source == "approved"
    assert plan.search_keywords == ["foldseek structure"]
    assert plan.key_topics
