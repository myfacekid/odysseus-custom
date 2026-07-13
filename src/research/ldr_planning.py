"""Retrieval planning and seed loading for the LDR research path."""
from __future__ import annotations

import json
import logging
import re
from typing import Dict, List, Optional, Tuple

from src.research.research_prompts import MODE_PLAN_CONTEXT, RESEARCH_PLAN_PROMPT, current_date_context
from src.research_relevance import format_seed_context
from src.research_retrieval_plan import (
    ResearchRetrievalPlan,
    derive_retrieval_plan_fallback,
    parse_retrieval_plan,
    plan_to_display_text,
)
from src.research_utils import strip_thinking

logger = logging.getLogger(__name__)


def _strip_code_block(text: str) -> str:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def parse_json_object(text: str) -> Optional[Dict]:
    text = _strip_code_block(text)
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            parsed = json.loads(text[start : end + 1])
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None
    return None


async def load_seed_findings(
    *,
    owner: str,
    seed_papers: Optional[List[str]],
    max_content_chars: int = 15000,
) -> Tuple[List[dict], str]:
    """Load user seed papers; returns (findings, note)."""
    if not owner or not seed_papers:
        return [], ""
    import asyncio

    from src.research_seeds import enrich_seed_findings_from_web, seed_findings_from_refs

    outcome = await asyncio.to_thread(
        seed_findings_from_refs,
        owner,
        seed_papers,
        extract_pdfs=True,
        pdf_max_chars=max_content_chars,
    )
    enriched = await asyncio.to_thread(
        enrich_seed_findings_from_web,
        outcome.findings,
        owner=owner,
        max_chars=max_content_chars,
    )
    return enriched, outcome.note or ""


async def build_retrieval_plan(
    *,
    question: str,
    llm_endpoint: str,
    llm_model: str,
    llm_headers: Optional[dict] = None,
    research_mode: str = "literature_review",
    seed_findings: Optional[List[dict]] = None,
    approved_plan: Optional[dict] = None,
) -> Tuple[ResearchRetrievalPlan, str]:
    """Create structured retrieval plan + human-readable display text."""
    if approved_plan:
        plan = parse_retrieval_plan(
            approved_plan,
            question,
            seed_findings or [],
            research_mode=research_mode,
        )
        return plan, plan_to_display_text(plan)

    mode_ctx = MODE_PLAN_CONTEXT.get(research_mode, "")
    seed_ctx = format_seed_context(seed_findings or []) if seed_findings else ""
    prompt = current_date_context() + RESEARCH_PLAN_PROMPT.format(question=question)
    if mode_ctx:
        prompt += f"\n\n{mode_ctx}"
    if seed_ctx and seed_ctx != "(none)":
        prompt += f"\n\nSeed papers (use titles and abstracts for anchor_terms and avoid_topics):\n{seed_ctx}"

    from src.llm_core import llm_call_async

    try:
        response = await llm_call_async(
            url=llm_endpoint,
            model=llm_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=1536,
            headers=llm_headers,
            timeout=45,
        )
        parsed = parse_json_object(strip_thinking(response))
        plan = parse_retrieval_plan(
            parsed,
            question,
            seed_findings or [],
            research_mode=research_mode,
        )
        display = plan_to_display_text(plan)
        return plan, display or strip_thinking(response)
    except Exception as exc:
        logger.warning("LDR planning failed: %s", exc)
        plan = derive_retrieval_plan_fallback(
            question,
            seed_findings or [],
            research_mode=research_mode,
        )
        return plan, plan_to_display_text(plan)


def build_agent_context_prompt(
    *,
    question: str,
    plan: ResearchRetrievalPlan,
    plan_display: str,
    research_mode: str,
    include_preprints: bool,
    include_zotero: bool,
    include_knowledge: bool,
    seed_findings: Optional[List[dict]] = None,
    prior_report: str = "",
) -> str:
    """Prefix injected into the LangGraph agent user message."""
    parts = [
        "You are gathering scholarly sources for an Odysseus Deep Research report.",
        "Search thoroughly using academic engines (PubMed, Semantic Scholar, OpenAlex, Scholar).",
        "Do not answer from memory — collect citable sources with titles, URLs, and snippets.",
        f"Research mode: {research_mode}.",
        # State the objective FIRST so the agent optimizes searches around the
        # user's actual question rather than the supporting keyword plan below.
        "\n## PRIMARY RESEARCH QUESTION (your objective — every search must serve this)\n"
        + question.strip(),
        "The retrieval plan, keywords, and anchor terms below are SUPPORTING HINTS "
        "to help you find sources for the question above — they do not replace it. "
        "If a hint conflicts with the question, follow the question.",
    ]
    if not include_preprints:
        parts.append(
            "Exclude preprints (arXiv, bioRxiv, medRxiv, SSRN) — peer-reviewed sources only."
        )
    if include_zotero:
        parts.append(
            "When the user's library may help, call search_zotero with focused keyword queries."
        )
    if include_knowledge:
        parts.append(
            "When Links/knowledge graph nodes may help, call search_knowledge with focused queries."
        )
    if plan.avoid_topics:
        parts.append("Reject sources about: " + "; ".join(plan.avoid_topics[:8]) + ".")
    if plan.anchor_terms:
        parts.append("Stay close to anchor terms: " + ", ".join(plan.anchor_terms[:12]) + ".")
    if plan_display:
        parts.append("\n## Retrieval plan\n" + plan_display.strip())
    seed_ctx = format_seed_context(seed_findings or []) if seed_findings else ""
    if seed_ctx and seed_ctx != "(none)":
        parts.append("\n## Seed papers\n" + seed_ctx)
    if prior_report.strip():
        parts.append("\n## Prior synthesis (continue gathering)\n" + prior_report.strip()[:4000])
    parts.append(
        "\n## Reminder — the research question (restated) is your goal\n"
        + question.strip()
    )
    return "\n".join(parts)
