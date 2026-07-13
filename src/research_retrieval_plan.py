"""Structured retrieval plan for Deep Research (RT3).

The planner LLM emits search keywords, anchors, and avoid-topics derived from the
user question and seed paper metadata — not from static domain lists in code.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence

RETRIEVAL_SCOPES = frozenset({
    "narrow_compare",
    "field_overview",
    "gap_analysis",
    "balanced",
})

_MODE_DEFAULT_SCOPE = {
    "compare": "narrow_compare",
    "similar_papers": "narrow_compare",
    "gap_analysis": "gap_analysis",
    "literature_review": "balanced",
}


def _clean_str_list(raw: Any, *, limit: int = 24) -> List[str]:
    if not raw:
        return []
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, (list, tuple)):
        return []
    out: List[str] = []
    seen: set[str] = set()
    for item in raw:
        text = (item or "").strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
        if len(out) >= limit:
            break
    return out


def default_scope_for_mode(research_mode: str) -> str:
    mode = (research_mode or "").strip().lower()
    return _MODE_DEFAULT_SCOPE.get(mode, "balanced")


@dataclass
class ResearchRetrievalPlan:
    sub_questions: List[str] = field(default_factory=list)
    key_topics: List[str] = field(default_factory=list)
    success_criteria: str = ""
    anchor_terms: List[str] = field(default_factory=list)
    search_keywords: List[str] = field(default_factory=list)
    scope: str = "balanced"
    must_stay_close_to_seeds: bool = False
    foundational_ok: bool = False
    expansion_queries: List[str] = field(default_factory=list)
    avoid_topics: List[str] = field(default_factory=list)
    openalex_search_queries: List[str] = field(default_factory=list)

    def normalized_scope(self) -> str:
        scope = (self.scope or "").strip().lower()
        if scope in RETRIEVAL_SCOPES:
            return scope
        return "balanced"

    def is_narrow(self) -> bool:
        return self.normalized_scope() in ("narrow_compare", "gap_analysis")

    def openalex_queries(self) -> List[str]:
        if self.openalex_search_queries:
            return list(self.openalex_search_queries)
        return list(self.search_keywords)


def _derive_anchor_terms(question: str, seed_findings: Sequence[dict]) -> List[str]:
    from src.research_relevance import (
        author_terms_from_finding,
        build_seed_fingerprint,
        extract_anchor_terms,
    )

    fingerprint = build_seed_fingerprint(seed_findings)
    author_block: set[str] = set()
    for finding in seed_findings or []:
        author_block.update(author_terms_from_finding(finding))
    return extract_anchor_terms(question or "", fingerprint, exclude_terms=author_block)


def _derive_expansion_queries(
    question: str,
    seed_findings: Sequence[dict],
    *,
    limit: int = 6,
) -> List[str]:
    from src.research_web_search import similar_paper_queries_from_seeds

    if seed_findings:
        return similar_paper_queries_from_seeds(
            list(seed_findings),
            question,
            limit=limit,
        )
    q = (question or "").strip()
    return [q] if len(q) >= 8 else []


def derive_retrieval_plan_fallback(
    question: str,
    seed_findings: Optional[Sequence[dict]] = None,
    *,
    research_mode: str = "literature_review",
) -> ResearchRetrievalPlan:
    """Build a plan from question + seeds when the planner JSON is missing or invalid."""
    seeds = list(seed_findings or [])
    scope = default_scope_for_mode(research_mode)
    anchors = _derive_anchor_terms(question, seeds)
    keywords = list(anchors)
    for finding in seeds:
        title = (finding.get("title") or "").strip()
        if title and len(title) >= 10:
            keywords.append(title[:120])
    keywords = _clean_str_list(keywords, limit=16)
    return ResearchRetrievalPlan(
        sub_questions=[],
        key_topics=keywords[:8],
        success_criteria="",
        anchor_terms=anchors,
        search_keywords=keywords,
        scope=scope,
        must_stay_close_to_seeds=bool(seeds) or scope == "narrow_compare",
        foundational_ok=scope == "field_overview",
        expansion_queries=_derive_expansion_queries(question, seeds),
        avoid_topics=[],
        openalex_search_queries=keywords,
    )


def parse_retrieval_plan(
    raw: Optional[Dict[str, Any]],
    question: str,
    seed_findings: Optional[Sequence[dict]] = None,
    *,
    research_mode: str = "literature_review",
) -> ResearchRetrievalPlan:
    """Merge planner JSON with seed-derived fallbacks for missing fields."""
    fallback = derive_retrieval_plan_fallback(
        question,
        seed_findings,
        research_mode=research_mode,
    )
    if not raw or not isinstance(raw, dict):
        return fallback

    scope = (raw.get("scope") or fallback.scope or "").strip().lower()
    if scope not in RETRIEVAL_SCOPES:
        scope = fallback.normalized_scope()

    anchor_terms = _clean_str_list(raw.get("anchor_terms")) or fallback.anchor_terms
    search_keywords = _clean_str_list(raw.get("search_keywords")) or anchor_terms or fallback.search_keywords
    expansion_queries = _clean_str_list(raw.get("expansion_queries"), limit=12) or fallback.expansion_queries
    openalex = _clean_str_list(raw.get("openalex_search_queries")) or search_keywords

    must_stay = raw.get("must_stay_close_to_seeds")
    if must_stay is None:
        must_stay = bool(seed_findings) or scope == "narrow_compare"
    foundational = raw.get("foundational_ok")
    if foundational is None:
        foundational = scope == "field_overview"

    return ResearchRetrievalPlan(
        sub_questions=_clean_str_list(raw.get("sub_questions"), limit=8) or fallback.sub_questions,
        key_topics=_clean_str_list(raw.get("key_topics")) or fallback.key_topics,
        success_criteria=(raw.get("success_criteria") or fallback.success_criteria or "").strip(),
        anchor_terms=anchor_terms,
        search_keywords=search_keywords,
        scope=scope,
        must_stay_close_to_seeds=bool(must_stay),
        foundational_ok=bool(foundational),
        expansion_queries=expansion_queries,
        avoid_topics=_clean_str_list(raw.get("avoid_topics"), limit=12),
        openalex_search_queries=openalex,
    )


def plan_to_display_text(plan: ResearchRetrievalPlan) -> str:
    """Human-readable plan block for prompts and logs."""
    lines: List[str] = []
    if plan.sub_questions:
        lines.append("Sub-questions: " + "; ".join(plan.sub_questions))
    if plan.key_topics:
        lines.append("Key topics: " + ", ".join(plan.key_topics))
    if plan.anchor_terms:
        lines.append("Anchor terms: " + ", ".join(plan.anchor_terms))
    if plan.search_keywords:
        lines.append("Search keywords: " + ", ".join(plan.search_keywords))
    if plan.avoid_topics:
        lines.append("Avoid topics: " + ", ".join(plan.avoid_topics))
    lines.append(f"Scope: {plan.normalized_scope()}")
    if plan.success_criteria:
        lines.append("Success: " + plan.success_criteria)
    return "\n".join(lines)


def plan_to_dict(plan: ResearchRetrievalPlan) -> Dict[str, Any]:
    """Serialize a retrieval plan for API / session storage."""
    return {
        "sub_questions": list(plan.sub_questions),
        "key_topics": list(plan.key_topics),
        "success_criteria": plan.success_criteria or "",
        "anchor_terms": list(plan.anchor_terms),
        "search_keywords": list(plan.search_keywords),
        "scope": plan.normalized_scope(),
        "must_stay_close_to_seeds": bool(plan.must_stay_close_to_seeds),
        "foundational_ok": bool(plan.foundational_ok),
        "expansion_queries": list(plan.expansion_queries),
        "avoid_topics": list(plan.avoid_topics),
        "openalex_search_queries": list(plan.openalex_queries()),
    }
