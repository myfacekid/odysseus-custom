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


def _topics_distinct_from_anchors(topics: List[str], anchors: List[str]) -> List[str]:
    """Drop key_topics that are exact copies of anchor_terms (case-insensitive)."""
    anchor_set = {a.lower() for a in anchors}
    return [t for t in topics if t.lower() not in anchor_set]


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

    q = (question or "").strip()
    sub_questions: List[str] = []
    if q:
        sub_questions.append(f"What are the main findings and methods addressing: {q}?")
        sub_questions.append(f"What limitations, open questions, or conflicting evidence exist for: {q}?")
        if seeds:
            titles = [
                (f.get("title") or "").strip()
                for f in seeds[:2]
                if (f.get("title") or "").strip()
            ]
            if titles:
                sub_questions.append(
                    "How do the seed papers ("
                    + "; ".join(t[:80] for t in titles)
                    + ") relate to this question?"
                )
        else:
            sub_questions.append(
                f"Which peer-reviewed sources best establish background and recent progress on: {q}?"
            )
    sub_questions = _clean_str_list(sub_questions, limit=6)

    key_topics = _topics_distinct_from_anchors(
        _clean_str_list(
            [
                "methods and experimental design",
                "key results and effect sizes",
                "limitations and open questions",
            ],
            limit=6,
        ),
        anchors,
    )
    success = (
        f"A sourced academic synthesis that answers: {q}"
        if q
        else "A sourced academic synthesis covering the research question."
    )
    if len(success) > 240:
        success = success[:237] + "…"

    return ResearchRetrievalPlan(
        sub_questions=sub_questions,
        key_topics=key_topics,
        success_criteria=success,
        anchor_terms=anchors,
        search_keywords=keywords,
        scope=scope,
        must_stay_close_to_seeds=bool(seeds) or scope == "narrow_compare",
        foundational_ok=scope == "field_overview",
        expansion_queries=_derive_expansion_queries(question, seeds),
        avoid_topics=[],
        openalex_search_queries=keywords,
    )


_OPTIONAL_LIST_FIELDS = (
    "key_topics",
    "sub_questions",
    "avoid_topics",
    "anchor_terms",
)
_OPTIONAL_STR_FIELDS = ("success_criteria",)


def missing_optional_plan_fields(raw: Optional[Dict[str, Any]]) -> List[str]:
    """Optional HITL fields that the user left unset (blank means fill later)."""
    if not raw or not isinstance(raw, dict):
        return list(_OPTIONAL_LIST_FIELDS) + list(_OPTIONAL_STR_FIELDS)
    missing: List[str] = []
    for key in _OPTIONAL_LIST_FIELDS:
        if not _clean_str_list(raw.get(key)):
            missing.append(key)
    for key in _OPTIONAL_STR_FIELDS:
        if not str(raw.get(key) or "").strip():
            missing.append(key)
    return missing


def sanitize_approved_plan(raw: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Drop blank optional fields so run-time fill can tell them from user pins."""
    if not raw or not isinstance(raw, dict):
        return None
    out: Dict[str, Any] = {}
    keywords = _clean_str_list(raw.get("search_keywords"))
    if keywords:
        out["search_keywords"] = keywords
    for key in _OPTIONAL_LIST_FIELDS:
        cleaned = _clean_str_list(raw.get(key), limit=12 if key == "avoid_topics" else 24)
        if cleaned:
            out[key] = cleaned
    success = str(raw.get("success_criteria") or "").strip()
    if success:
        out["success_criteria"] = success
    scope = str(raw.get("scope") or "").strip().lower()
    if scope:
        out["scope"] = scope
    for key in ("must_stay_close_to_seeds", "foundational_ok"):
        if key in raw and raw[key] is not None:
            out[key] = bool(raw[key])
    expansion = _clean_str_list(raw.get("expansion_queries"), limit=12)
    if expansion:
        out["expansion_queries"] = expansion
    openalex = _clean_str_list(raw.get("openalex_search_queries"))
    if openalex:
        out["openalex_search_queries"] = openalex
    return out or None


def merge_llm_into_approved_plan(
    approved: Dict[str, Any],
    llm_raw: Optional[Dict[str, Any]],
    missing: Sequence[str],
) -> Dict[str, Any]:
    """Copy only unset optional fields from planner JSON onto the user plan."""
    merged = dict(approved or {})
    if not llm_raw or not isinstance(llm_raw, dict) or not missing:
        return merged
    for key in missing:
        if key in _OPTIONAL_STR_FIELDS:
            val = str(llm_raw.get(key) or "").strip()
            if val:
                merged[key] = val
            continue
        cleaned = _clean_str_list(llm_raw.get(key), limit=12 if key == "avoid_topics" else 24)
        if cleaned:
            merged[key] = cleaned
    return merged


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

    raw_topics = _clean_str_list(raw.get("key_topics"))
    key_topics = (
        _topics_distinct_from_anchors(raw_topics, anchor_terms)
        if raw_topics
        else list(fallback.key_topics)
    )

    return ResearchRetrievalPlan(
        sub_questions=_clean_str_list(raw.get("sub_questions"), limit=8) or fallback.sub_questions,
        key_topics=key_topics,
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
