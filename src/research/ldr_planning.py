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
    merge_llm_into_approved_plan,
    missing_optional_plan_fields,
    parse_retrieval_plan,
    plan_to_display_text,
    sanitize_approved_plan,
)
from src.research_utils import strip_thinking

logger = logging.getLogger(__name__)

_RETRY_REMINDER = (
    "\n\nYour previous reply was missing required JSON fields or was not valid JSON. "
    "Reply with ONLY a single JSON object. You MUST include non-empty arrays for "
    "sub_questions, key_topics, and avoid_topics, plus a non-empty success_criteria "
    "string, along with anchor_terms, search_keywords, and scope."
)


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


def plan_has_scholarly_fields(raw: Optional[Dict]) -> bool:
    """True when planner JSON includes optional HITL scholarly fields."""
    if not raw or not isinstance(raw, dict):
        return False
    has_sub = bool(raw.get("sub_questions"))
    has_topics = bool(raw.get("key_topics"))
    has_success = bool(str(raw.get("success_criteria") or "").strip())
    return has_sub or has_topics or has_success


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


def _planner_prompt(
    question: str,
    research_mode: str,
    seed_findings: Optional[List[dict]],
) -> str:
    mode_ctx = MODE_PLAN_CONTEXT.get(research_mode, "")
    seed_ctx = format_seed_context(seed_findings or []) if seed_findings else ""
    prompt = current_date_context() + RESEARCH_PLAN_PROMPT.format(question=question)
    if mode_ctx:
        prompt += f"\n\n{mode_ctx}"
    if seed_ctx and seed_ctx != "(none)":
        prompt += (
            "\n\nSeed papers (pull named methods/acronyms into anchor_terms; "
            "pull thematic gaps into key_topics; unrelated nearby fields into avoid_topics):\n"
            f"{seed_ctx}"
        )
    return prompt


async def _call_planner_llm(
    prompt: str,
    *,
    llm_endpoint: str,
    llm_model: str,
    llm_headers: Optional[dict] = None,
) -> Optional[Dict]:
    from src.llm_core import llm_call_async

    async def _call(user_prompt: str) -> Optional[Dict]:
        response = await llm_call_async(
            url=llm_endpoint,
            model=llm_model,
            messages=[{"role": "user", "content": user_prompt}],
            temperature=0.3,
            max_tokens=2048,
            headers=llm_headers,
            timeout=45,
        )
        return parse_json_object(strip_thinking(response))

    parsed = await _call(prompt)
    if not plan_has_scholarly_fields(parsed):
        logger.warning(
            "LDR planning JSON incomplete or unparseable; retrying once "
            "(parsed_keys=%s)",
            sorted(parsed.keys()) if isinstance(parsed, dict) else None,
        )
        parsed = await _call(prompt + _RETRY_REMINDER)
    return parsed if plan_has_scholarly_fields(parsed) else None


async def build_retrieval_plan(
    *,
    question: str,
    llm_endpoint: str,
    llm_model: str,
    llm_headers: Optional[dict] = None,
    research_mode: str = "literature_review",
    seed_findings: Optional[List[dict]] = None,
    approved_plan: Optional[dict] = None,
) -> Tuple[ResearchRetrievalPlan, str, str]:
    """Create structured retrieval plan + display text + source tag.

    Returns ``(plan, display, plan_source)`` where ``plan_source`` is
    ``\"approved\"``, ``\"llm\"``, or ``\"fallback\"``.
    """
    approved = sanitize_approved_plan(approved_plan)
    if approved:
        missing = missing_optional_plan_fields(approved)
        if missing and llm_endpoint and llm_model:
            fill_prompt = _planner_prompt(question, research_mode, seed_findings)
            fill_prompt += (
                "\n\nThe user already approved these retrieval fields. Keep them "
                "unchanged and fill ONLY the missing fields "
                f"({', '.join(missing)}). Reply with a single JSON object that "
                "includes the existing fields plus the missing ones.\n"
                f"Already approved:\n{json.dumps(approved, ensure_ascii=False)}"
            )
            try:
                parsed = await _call_planner_llm(
                    fill_prompt,
                    llm_endpoint=llm_endpoint,
                    llm_model=llm_model,
                    llm_headers=llm_headers,
                )
                if parsed:
                    approved = merge_llm_into_approved_plan(approved, parsed, missing)
            except Exception as exc:
                logger.warning("LDR fill of empty optional plan fields failed: %s", exc)
        plan = parse_retrieval_plan(
            approved,
            question,
            seed_findings or [],
            research_mode=research_mode,
        )
        return plan, plan_to_display_text(plan), "approved"

    prompt = _planner_prompt(question, research_mode, seed_findings)
    try:
        parsed = await _call_planner_llm(
            prompt,
            llm_endpoint=llm_endpoint,
            llm_model=llm_model,
            llm_headers=llm_headers,
        )
        if parsed:
            plan = parse_retrieval_plan(
                parsed,
                question,
                seed_findings or [],
                research_mode=research_mode,
            )
            return plan, plan_to_display_text(plan), "llm"

        logger.warning(
            "LDR planning still incomplete after retry; using enriched heuristic fallback"
        )
    except Exception as exc:
        logger.warning("LDR planning failed: %s", exc)

    plan = derive_retrieval_plan_fallback(
        question,
        seed_findings or [],
        research_mode=research_mode,
    )
    return plan, plan_to_display_text(plan), "fallback"


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
        "You are gathering scholarly sources for a Nobody Deep Research report.",
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
