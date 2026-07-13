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
_SIMILAR_MARKERS = ("cited by", "related work", "doi.org", "site:pubmed", "site:scholar", "scholar.google")
_GAP_MARKERS = ("peer-reviewed", "randomized", "cohort study")
_PUBMED_SITE = "site:pubmed.ncbi.nlm.nih.gov"
_SCHOLAR_SITE = "site:scholar.google.com"


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
    """Freshness heuristics for web search — research avoids implicit year filters."""
    q_lc = (query or "").lower()
    if any(kw in q_lc for kw in ("today", "latest", "breaking", "this morning", "right now", "currently")):
        return "day"
    if any(kw in q_lc for kw in ("this week", "past week", "recent news", "last few days")):
        return "week"
    if any(kw in q_lc for kw in ("this month", "past month")):
        return "month"
    if " news" in q_lc or q_lc.startswith("news ") or q_lc.endswith(" news"):
        return "week"
    # Only apply academic time bounds when the query itself asks for recency —
    # not because gap-filling rounds echo the current calendar year.
    from src.research_relevance import user_requests_recency

    if user_requests_recency(query):
        if any(kw in q_lc for kw in ("today", "this week", "last few days")):
            return "week"
        if any(kw in q_lc for kw in ("this month", "past month")):
            return "month"
        return "year"
    return None


def enhance_query_for_kind(
    query: str,
    search_kind: str,
    *,
    has_seeds: bool = False,
    scope: str = "balanced",
) -> str:
    """Light academic template — one enhanced query per LLM suggestion."""
    q = (query or "").strip()
    if not q:
        return q
    lower = q.lower()
    narrow = scope in ("narrow_compare", "gap_analysis")

    if search_kind == "discovery":
        if has_seeds or narrow:
            if "site:pubmed" not in lower and "pubmed" not in lower and "doi" not in lower:
                return f"{q} site:pubmed.ncbi.nlm.nih.gov"
            return q
        if scope == "field_overview" and not any(m in lower for m in _DISCOVERY_MARKERS):
            return f"{q} systematic review OR meta-analysis"
        if "site:pubmed" not in lower and "pubmed" not in lower and "doi" not in lower:
            return f"{q} site:pubmed.ncbi.nlm.nih.gov"
        return q

    if search_kind == "similar_papers":
        if _PUBMED_SITE in lower or _SCHOLAR_SITE in lower or "scholar.google" in lower:
            return q
        if re.search(r"\b10\.\S+", lower) or "doi.org" in lower:
            return f"{q} {_PUBMED_SITE}"
        if lower.startswith('"') or "intitle:" in lower:
            return f"{q} {_SCHOLAR_SITE}"
        return f'{_SCHOLAR_SITE} intitle:"{q}"'

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
    has_seeds: bool = False,
    scope: str = "balanced",
    expansion_queries: Optional[List[str]] = None,
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
        out.append(enhance_query_for_kind(
            text, search_kind, has_seeds=has_seeds, scope=scope,
        ))

    for q in expansion_queries or []:
        _add(q)

    for q in queries or []:
        _add(q)

    if search_kind == "gap_filling":
        for sub in _parse_plan_sub_questions(research_plan, limit=2):
            _add(sub)

    if (
        search_kind == "discovery"
        and question
        and len(out) < 4
        and not has_seeds
        and scope == "field_overview"
    ):
        _add(f"{question} systematic review")

    return out


def normalize_paper_doi(finding: dict) -> str:
    """Return a bare DOI from a finding, if present."""
    from src.research_finding_enrich import extract_doi

    for raw in (
        finding.get("doi_or_id") or "",
        finding.get("doi") or "",
        finding.get("url") or "",
    ):
        text = (raw or "").strip()
        if text.lower().startswith("10.") and "/" in text:
            return text.split()[0].rstrip("/")
        doi = extract_doi(text)
        if doi:
            return doi
    return ""


def is_scholar_author_profile_url(url: str) -> bool:
    """True for Google Scholar author/citation profile pages, not paper hits."""
    lower = (url or "").lower()
    if "scholar.google" not in lower:
        return False
    if "/citations" in lower:
        return True
    if "view_op=list_works" in lower or "view_op=search_authors" in lower:
        return True
    if "user=" in lower and "citation" in lower:
        return True
    return False


def is_paper_landing_url(url: str) -> bool:
    """True when URL likely points at a paper record, not a person/profile."""
    if is_scholar_author_profile_url(url):
        return False
    lower = (url or "").lower()
    if not lower.startswith("http"):
        return False
    markers = (
        "doi.org",
        "pubmed.ncbi.nlm.nih.gov",
        "/pubmed/",
        "ncbi.nlm.nih.gov/pmc/",
        "springer.com",
        "sciencedirect.com",
        "wiley.com",
        "nature.com",
        "science.org",
        "cell.com",
        "plos.org",
        "ieee.org",
        "acm.org",
        "arxiv.org",
        "biorxiv.org",
    )
    if any(m in lower for m in markers):
        return True
    if "scholar.google" in lower and "/scholar?" in lower:
        return True
    return lower.endswith(".pdf")


def paper_lookup_queries_for_finding(finding: dict) -> List[str]:
    """Build paper-identified PubMed/Scholar queries — never author-only."""
    title = (finding.get("title") or "").strip()
    doi = normalize_paper_doi(finding)
    year = (finding.get("year") or "").strip()
    queries: List[str] = []

    if doi.startswith("10."):
        queries.append(f"{_PUBMED_SITE} {doi}")
        queries.append(f"https://doi.org/{doi}")
    if title and len(title) >= 10:
        short = title if len(title) <= 120 else title[:120]
        queries.append(f'{_PUBMED_SITE} "{short}"')
        queries.append(f'{_SCHOLAR_SITE} intitle:"{short}"')
        if year.isdigit():
            queries.append(f'{_SCHOLAR_SITE} intitle:"{short}" {year}')
    return queries


def similar_paper_queries_from_findings(findings: List[dict], limit: int = 2) -> List[str]:
    """Build PubMed / Google Scholar paper lookup queries from gathered papers."""
    queries: List[str] = []
    for f in findings or []:
        for q in paper_lookup_queries_for_finding(f):
            queries.append(q)
            if len(queries) >= limit * 2:
                break
        if len(queries) >= limit * 2:
            break
    return apply_academic_query_templates(
        queries,
        search_kind="similar_papers",
    )


def similar_paper_queries_from_seeds(
    seed_findings: List[dict],
    question: str = "",
    *,
    limit: int = 8,
) -> List[str]:
    """Paper-focused PubMed + Google Scholar queries from seed metadata."""
    seen: set[str] = set()
    raw_queries: List[str] = []

    def _add(raw: str) -> None:
        text = (raw or "").strip()
        if len(text) < 8:
            return
        key = text.lower()
        if key in seen:
            return
        seen.add(key)
        raw_queries.append(text)

    seeds = [
        f for f in seed_findings or []
        if f.get("is_seed") or f.get("paper_key") or f.get("title")
    ]
    for seed in seeds:
        for q in paper_lookup_queries_for_finding(seed):
            _add(q)

    if question:
        q_short = question.strip()[:120]
        _add(f"{_PUBMED_SITE} {q_short}")

    return apply_academic_query_templates(raw_queries, search_kind="similar_papers")[: max(limit, 1)]


def rank_similar_paper_search_results(query: str, results: List[dict]) -> List[dict]:
    """Rank search hits for similar-paper discovery — prefer PubMed and paper pages."""
    from src.research_relevance import score_search_result

    def _score(row: dict) -> float:
        url = (row.get("url") or "").lower()
        if is_scholar_author_profile_url(url):
            return -1.0
        base = score_search_result(row, query)
        bonus = 0.0
        if "pubmed.ncbi.nlm.nih.gov" in url or "/pubmed/" in url:
            bonus += 0.35
        elif "doi.org" in url:
            bonus += 0.28
        elif "scholar.google" in url and is_paper_landing_url(url):
            bonus += 0.2
        elif "ncbi.nlm.nih.gov" in url:
            bonus += 0.15
        if "semanticscholar.org" in url or "openalex.org" in url:
            bonus -= 0.2
        return base + bonus

    return sorted(results or [], key=_score, reverse=True)


def similar_source_from_url(url: str) -> str:
    """Label similar-paper provenance from a resolved URL."""
    lower = (url or "").lower()
    if "pubmed.ncbi.nlm.nih.gov" in lower or "/pubmed/" in lower:
        return "pubmed"
    if "scholar.google" in lower:
        return "google_scholar"
    if "doi.org" in lower:
        return "doi"
    if "semanticscholar.org" in lower:
        return "semantic_scholar"
    if "openalex.org" in lower:
        return "openalex"
    return "web"


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

    search_results = rank_search_results(query, search_results, recency_weight=0.0)
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
