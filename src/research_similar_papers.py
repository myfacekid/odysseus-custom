"""Similar-paper discovery for Deep Research (Phase 2 / L1).

Primary discovery uses PubMed and Google Scholar web searches (see
``research_web_search.similar_paper_queries_from_seeds``). When scholarly web
search is sparse, **keyword search** on OpenAlex / Semantic Scholar (via
``src.research_engines``) replaces co-citation recommenders (S2 ``forpaper``,
OpenAlex ``related_to``).
"""
from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Set

logger = logging.getLogger(__name__)

_USER_AGENT = "Odysseus-DeepResearch/1.0 (mailto:support@example.com)"
_OPENALEX_BASE = "https://api.openalex.org"
_S2_BASE = "https://api.semanticscholar.org"


@dataclass
class SimilarPapersOutcome:
    findings: List[dict]
    openalex_count: int = 0
    semantic_scholar_count: int = 0
    web_search_count: int = 0
    note: str = ""


def _http_json(url: str, *, method: str = "GET", data: bytes = b"", timeout: int = 20) -> Optional[dict]:
    req = urllib.request.Request(
        url,
        data=data or None,
        method=method,
        headers={
            "User-Agent": _USER_AGENT,
            "Accept": "application/json",
        },
    )
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as e:
        logger.info("Similar-paper API request failed (%s): %s", url[:80], e)
        return None


def _format_authors(raw) -> str:
    if isinstance(raw, str):
        return raw
    if not isinstance(raw, list):
        return ""
    names: List[str] = []
    for a in raw[:6]:
        if isinstance(a, str):
            names.append(a)
        elif isinstance(a, dict):
            names.append(a.get("name") or a.get("author", {}).get("name") or "")
    return ", ".join(n for n in names if n)


def _finding_from_openalex_work(work: dict) -> Optional[dict]:
    if not work:
        return None
    title = (work.get("title") or work.get("display_name") or "").strip()
    if not title:
        return None
    doi = (work.get("doi") or "").replace("https://doi.org/", "").strip()
    year = str(work.get("publication_year") or "")
    url = work.get("id") or ""
    if doi:
        url = f"https://doi.org/{doi}"
    elif not url.startswith("http"):
        oa_id = (work.get("id") or "").rsplit("/", 1)[-1]
        url = f"https://openalex.org/{oa_id}" if oa_id else ""

    abstract = ""
    inv = work.get("abstract_inverted_index")
    if isinstance(inv, dict) and inv:
        positions: List[int] = []
        for pos_list in inv.values():
            positions.extend(pos_list)
        max_pos = max(positions) if positions else 0
        words = [""] * (max_pos + 1)
        for word, pos_list in inv.items():
            for pos in pos_list:
                if 0 <= pos < len(words):
                    words[pos] = word
        abstract = " ".join(w for w in words if w).strip()

    authors = _format_authors(work.get("authorships") or [])
    if not authors and work.get("authorships"):
        authors = ", ".join(
            (a.get("author") or {}).get("display_name", "")
            for a in work.get("authorships", [])[:6]
            if (a.get("author") or {}).get("display_name")
        )

    peer = "preprint" if (work.get("type") or "").lower() == "preprint" else "peer-reviewed"
    evidence = abstract or title
    return {
        "url": url,
        "title": title,
        "rational": "Similar work from OpenAlex",
        "evidence": evidence[:15000],
        "summary": (abstract or title)[:800],
        "authors": authors,
        "year": year,
        "doi_or_id": doi or (work.get("id") or "").rsplit("/", 1)[-1],
        "peer_review_status": peer,
        "study_type": work.get("type") or "journalArticle",
        "source_type": "similar_paper",
        "similar_source": "openalex",
    }


def _finding_from_s2_paper(paper: dict) -> Optional[dict]:
    if not paper:
        return None
    title = (paper.get("title") or "").strip()
    if not title:
        return None
    ext = paper.get("externalIds") or {}
    doi = (ext.get("DOI") or "").strip()
    url = (paper.get("url") or "").strip()
    if not url and doi:
        url = f"https://doi.org/{doi}"
    elif not url:
        sid = paper.get("paperId") or ""
        url = f"https://www.semanticscholar.org/paper/{sid}" if sid else ""

    abstract = (paper.get("abstract") or "").strip()
    authors = _format_authors(paper.get("authors") or [])
    year = str(paper.get("year") or "")
    peer = "peer-reviewed"
    if paper.get("isOpenAccess") and paper.get("openAccessPdf"):
        peer = "open access"

    return {
        "url": url,
        "title": title,
        "rational": "Similar work from Semantic Scholar",
        "evidence": (abstract or title)[:15000],
        "summary": (abstract or title)[:800],
        "authors": authors,
        "year": year,
        "doi_or_id": doi or paper.get("paperId") or "",
        "peer_review_status": peer,
        "study_type": "journalArticle",
        "source_type": "similar_paper",
        "similar_source": "semantic_scholar",
        "citation_count": paper.get("citationCount"),
    }


def openalex_similar_works(
    *,
    doi: str = "",
    openalex_id: str = "",
    limit: int = 8,
    query: str = "",
) -> List[dict]:
    """Keyword search on OpenAlex (replaces ``related_to`` co-citation expansion)."""
    from src.research_engines.keyword_search import _engine_keyword_search

    search_q = (query or "").strip()
    if not search_q and doi:
        search_q = doi
    if not search_q:
        return []
    return _engine_keyword_search("openalex", search_q, limit=limit)


def semantic_scholar_recommendations(
    *,
    doi: str = "",
    paper_id: str = "",
    limit: int = 8,
    query: str = "",
) -> List[dict]:
    """Keyword search on Semantic Scholar (replaces ``forpaper`` recommendations)."""
    from src.research_engines.keyword_search import _engine_keyword_search

    search_q = (query or "").strip()
    if not search_q and doi:
        search_q = doi
    if not search_q:
        return []
    return _engine_keyword_search("semantic_scholar", search_q, limit=limit)


def _soft_age_score(year: int, *, now_year: Optional[int] = None) -> float:
    """Gentle preference for newer work — never penalize seminal older papers."""
    if year <= 0:
        return 0.0
    now_year = now_year or datetime.now().year
    age = now_year - year
    if age <= 5:
        return 0.3
    if age <= 15:
        return 0.15
    if age <= 30:
        return 0.05
    return 0.0


def _rank_similar(finding: dict) -> float:
    from src.research_relevance import score_seed_overlap

    score = 0.0
    if finding.get("peer_review_status") == "peer-reviewed":
        score += 2.0
    try:
        yr = int(finding.get("year") or 0)
        score += _soft_age_score(yr)
    except ValueError:
        pass
    cite = finding.get("citation_count")
    if isinstance(cite, (int, float)):
        score += min(cite / 100.0, 3.0)
    if finding.get("evidence") and len(finding["evidence"]) > 200:
        score += 0.5
    seed_overlap = finding.get("_seed_overlap_score")
    if isinstance(seed_overlap, (int, float)):
        score += seed_overlap * 4.0
    return score


def _dedupe_key(finding: dict) -> str:
    doi = (finding.get("doi_or_id") or "").strip().lower()
    if doi.startswith("10."):
        return f"doi:{doi}"
    url = (finding.get("url") or "").strip().lower().rstrip("/")
    if url:
        return f"url:{url}"
    return f"title:{(finding.get('title') or '').lower()}"


def similar_papers_from_seeds(
    seed_findings: List[dict],
    *,
    limit_per_seed: int = 5,
    total_limit: int = 12,
    exclude_keys: Optional[Set[str]] = None,
    relevance_query: str = "",
    research_mode: str = "",
    use_semantic_scholar: Optional[bool] = None,
    avoid_topics: Optional[List[str]] = None,
    plan_anchor_terms: Optional[List[str]] = None,
) -> SimilarPapersOutcome:
    """Keyword-search similar papers via LDR engines (OpenAlex + optional S2).

    Replaces co-citation APIs (OpenAlex ``related_to``, S2 ``forpaper``) with
    title/abstract-derived keyword queries — better topical fit for compare mode.
    """
    from src.research_engines.keyword_search import build_seed_search_queries, keyword_search_findings
    from src.research_engines.registry import DEFAULT_SIMILAR_ENGINES
    from src.research_relevance import build_relevance_query, is_similar_paper_relevant, score_seed_overlap

    exclude = {k.upper() for k in (exclude_keys or set()) if k}
    gate_q = (relevance_query or build_relevance_query("", seed_findings=seed_findings)).strip()
    mode = (research_mode or "").strip().lower()

    engines = list(DEFAULT_SIMILAR_ENGINES)
    if use_semantic_scholar is False:
        engines = [e for e in engines if e != "semantic_scholar"]
    elif use_semantic_scholar is None and mode in ("compare", "similar_papers"):
        engines = [e for e in engines if e != "semantic_scholar"]

    queries: List[str] = []
    for seed in seed_findings or []:
        if not seed.get("is_seed") and not seed.get("paper_key"):
            continue
        queries.extend(build_seed_search_queries(seed))

    if not queries:
        return SimilarPapersOutcome([], note="Similar papers (keyword): no seed queries")

    outcome = keyword_search_findings(
        queries,
        engines=tuple(engines),
        limit_per_query=max(limit_per_seed, 1),
    )
    pooled = list(outcome.findings)
    oa_count = outcome.engine_counts.get("openalex", 0)
    s2_count = outcome.engine_counts.get("semantic_scholar", 0)

    if exclude:
        pooled = [
            f for f in pooled
            if (f.get("doi_or_id") or "").upper() not in exclude
            and not any(
                k in exclude
                for k in (
                    (f.get("paper_key") or "").upper(),
                    (f.get("zotero_key") or "").upper(),
                )
            )
        ]

    if gate_q:
        pooled = [
            f for f in pooled
            if is_similar_paper_relevant(
                f,
                gate_q,
                seed_findings,
                research_mode=mode,
                avoid_topics=avoid_topics,
                plan_anchor_terms=plan_anchor_terms,
            )
        ]

    for f in pooled:
        f["_seed_overlap_score"] = score_seed_overlap(f, seed_findings)

    pooled.sort(key=_rank_similar, reverse=True)
    findings = pooled[: max(total_limit, 1)]
    note = (
        f"Similar papers (keyword fallback): {len(findings)} "
        f"(OpenAlex {oa_count}, Semantic Scholar {s2_count})"
    )
    return SimilarPapersOutcome(findings, oa_count, s2_count, note=note)
