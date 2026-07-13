"""Tests for LDR planning and agent context prompts."""

import pytest

from src.research.ldr_planning import (
    build_agent_context_prompt,
    parse_json_object,
)
from src.research_retrieval_plan import ResearchRetrievalPlan, plan_to_display_text


def test_parse_json_object_strips_fences():
    raw = '```json\n{"sub_questions": ["a"], "scope": "balanced"}\n```'
    parsed = parse_json_object(raw)
    assert parsed["sub_questions"] == ["a"]


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
    plan, display = await build_retrieval_plan(
        question="ESM3 structure",
        llm_endpoint="http://localhost/v1/chat/completions",
        llm_model="test",
        research_mode="compare",
        seed_findings=[],
    )
    assert plan.scope in ("narrow_compare", "balanced", "gap_analysis", "field_overview")
    assert isinstance(display, str)
