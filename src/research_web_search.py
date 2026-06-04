"""Deep Research web search — shared provider layer with chat/agents (Phase 1a).

Routes research queries through the same provider chain, time filters, ranking,
and error messages as ``comprehensive_web_search`` / the agent ``web_search`` tool.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

SEARCH_KINDS = ("discovery", "similar_papers", "gap_filling")

_DISCOVERY_MARKERS = ("systematic review", "meta-analysis", "meta analysis", "site:pubmed")
_SIMILAR_MARKERS = ("cited by", "related work", "doi.org")
_GAP_MARKERS = ("peer-reviewed", "randomized", "cohort study")


@dataclass
class ResearchSearchOutcome:
    results: List[dict]
    provider: str
    query: str
    search_kind: str
    time_filter: Optional[str] = None
    error: Optional[str] = None


def resolve_research_provider(provider_override: Optional[str] = None) -> str:
    from services.search.providers import _get_search_settings

    settings = _get_search_settings()
    provider = (provider_override or "").strip()
    if not provider:
        provider = (settings.get("research_search_provider") or "").strip()
    if not provider:
        provider = settings.get("search_provider", "searxng")
    return provider


def infer_search_kind(round_num: int) -> str:
    if round_num <= 1:
        return "discovery"
    return "gap_filling"


def infer_time_filter(query: str, search_kind: str = "discovery") -> Optional[str]:
    """Match agent web_search freshness heuristics."""
    q_lc = (query or "").lower()
    if any(kw in q_lc for kw in ("today", "latest", "breaking", "this morning", "right now", "currently")):
        return "day"
    if any(kw in q_lc for kw in ("this week", "past week", "recent news", "last few days")):
        return "week"
    if any(kw in q_lc for kw in ("this month", "past month")):
        return "month"
    if " news" in q_lc or q_lc.startswith("news ") or q_lc.endswith(" news"):
        return "week"
    if search_kind == "gap_filling" and any(kw in q_lc for kw in ("recent", "last five years", "2020", "2021", "2022", "2023", "2024", "2025", "2026")):
        return "year"
    return None


def enhance_query_for_kind(query: str, search_kind: str) -> str:
    """Light academic template — one enhanced query per LLM suggestion."""
    q = (query or "").strip()
    if not q:
        return q
    lower = q.lower()

    if search_kind == "discovery":
        if not any(m in lower for m in _DISCOVERY_MARKERS):
            return f"{q} systematic review OR meta-analysis"
        if "site:pubmed" not in lower and "pubmed" not in lower and "doi" not in lower:
            return f"{q} site:pubmed.ncbi.nlm.nih.gov"
        return q

    if search_kind == "similar_papers":
        if "cited by" not in lower and not lower.startswith('"'):
            return f'"{q}" cited by'
        if "related work" not in lower:
            return f"{q} related work"
        return q

    if search_kind == "gap_filling":
        if not any(m in lower for m in _GAP_MARKERS):
            return f"{q} peer-reviewed evidence"
        return q

    return q


def _parse_plan_sub_questions(research_plan: str, limit: int = 2) -> List[str]:
    if not research_plan:
        return []
    match = re.search(r"Sub-questions:\s*(.+?)(?:\n|$)", research_plan, re.IGNORECASE)
    if not match:
        return []
    chunk = match.group(1)
    parts = re.split(r"[;|]\s*|\d+\.\s+", chunk)
    out = []
    for part in parts:
        text = part.strip(" -•")
        if len(text) > 12:
            out.append(text)
        if len(out) >= limit:
            break
    return out


def apply_academic_query_templates(
    queries: List[str],
    *,
    search_kind: str,
    question: str = "",
    research_plan: str = "",
) -> List[str]:
    """Augment LLM queries with scholarly patterns; dedupe case-insensitively."""
    seen: set[str] = set()
    out: List[str] = []

    def _add(q: str) -> None:
        text = (q or "").strip()
        if not text:
            return
        key = text.lower()
        if key in seen:
            return
        seen.add(key)
        out.append(enhance_query_for_kind(text, search_kind))

    for q in queries or []:
        _add(q)

    if search_kind == "gap_filling":
        for sub in _parse_plan_sub_questions(research_plan, limit=2):
            _add(sub)

    if search_kind == "discovery" and question and len(out) < 4:
        _add(f"{question} systematic review")

    return out


def similar_paper_queries_from_findings(findings: List[dict], limit: int = 2) -> List[str]:
    """Build similarity queries from gathered DOIs/titles (Phase 1a prep for Phase 2)."""
    queries: List[str] = []
    for f in findings or []:
        doi = (f.get("doi_or_id") or "").strip()
        if doi.startswith("10."):
            queries.append(f"https://doi.org/{doi} cited by")
        title = (f.get("title") or "").strip()
        if title and len(queries) < limit:
            queries.append(f'"{title}" related work')
        if len(queries) >= limit:
            break
    return apply_academic_query_templates(
        queries,
        search_kind="similar_papers",
    )


def research_web_search(
    query: str,
    *,
    search_kind: str = "discovery",
    time_filter: Optional[str] = None,
    provider_override: Optional[str] = None,
    count: int = 10,
) -> ResearchSearchOutcome:
    """Run a web search using the shared provider layer (same semantics as chat)."""
    from services.search.core import _build_provider_chain, _call_provider
    from services.search.providers import _get_result_count, _get_search_settings
    from services.search.ranking import rank_search_results

    query = (query or "").strip()
    if not query:
        return ResearchSearchOutcome([], "", query, search_kind, time_filter, error="Empty search query")

    provider = resolve_research_provider(provider_override)
    if provider == "disabled":
        msg = "Web search is disabled by the administrator."
        logger.info(msg)
        return ResearchSearchOutcome([], provider, query, search_kind, time_filter, error=msg)

    if time_filter is None:
        time_filter = infer_time_filter(query, search_kind)

    if count == 10:
        count = max(count, _get_result_count())

    provider_chain = _build_provider_chain(provider)
    search_results: List[dict] = []
    provider_attempts: dict = {}
    winning_provider = ""

    for provider_name in provider_chain:
        last_err = None
        empty = False
        for attempt in range(2):
            try:
                search_results = _call_provider(provider_name, query, count, time_filter)
                if search_results:
                    provider_attempts[provider_name] = f"ok ({len(search_results)})"
                    winning_provider = provider_name
                    logger.info(
                        "Research web search: %s returned %d results for %r (%s)",
                        provider_name, len(search_results), query, search_kind,
                    )
                    break
                empty = True
            except Exception as e:
                last_err = e
                logger.warning(
                    "Research web search: %s attempt %d failed for %r: %s",
                    provider_name, attempt + 1, query, e,
                )
        if search_results:
            break
        if last_err is not None:
            provider_attempts[provider_name] = f"error: {last_err}"
        elif empty:
            provider_attempts[provider_name] = "empty"

    if not search_results:
        tally = ", ".join(f"{p}:{r}" for p, r in provider_attempts.items()) or "no providers configured"
        any_errors = any(str(r).startswith("error") for r in provider_attempts.values())
        if any_errors:
            msg = f"Web search failed — all providers errored or returned empty. Tried: {tally}"
        else:
            msg = (
                f"No search results found. Tried: {tally}. "
                "All providers returned empty — possibly a niche query or upstream rate-limiting; "
                "rephrasing may help."
            )
        logger.warning("Research web search empty for %r: %s", query, msg)
        return ResearchSearchOutcome([], winning_provider or provider, query, search_kind, time_filter, error=msg)

    search_results = rank_search_results(query, search_results)
    return ResearchSearchOutcome(
        search_results,
        winning_provider,
        query,
        search_kind,
        time_filter,
        error=None,
    )


def annotate_search_results(
    results: List[dict],
    outcome: ResearchSearchOutcome,
) -> List[dict]:
    """Attach provider/query/kind metadata for the evidence registry."""
    annotated = []
    for row in results or []:
        item = dict(row)
        item.setdefault("source_type", "web")
        item["search_query"] = outcome.query
        item["search_provider"] = outcome.provider
        item["search_kind"] = outcome.search_kind
        if outcome.time_filter:
            item["search_time_filter"] = outcome.time_filter
        annotated.append(item)
    return annotated
