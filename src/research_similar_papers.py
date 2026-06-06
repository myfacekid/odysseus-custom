"""Similar-paper discovery for Deep Research (Phase 2).

Primary discovery uses PubMed and Google Scholar web searches (see
``research_web_search.similar_paper_queries_from_seeds``). OpenAlex and
Semantic Scholar remain available as a fallback when scholarly web search
returns too few on-topic hits.
"""
from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
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


def _openalex_id_from_doi(doi: str) -> Optional[str]:
    if not doi:
        return None
    encoded = urllib.parse.quote(f"https://doi.org/{doi}", safe="")
    data = _http_json(f"{_OPENALEX_BASE}/works/{encoded}?select=id,related_works")
    if not data:
        return None
    wid = (data.get("id") or "").rsplit("/", 1)[-1]
    return wid or None


def openalex_similar_works(
    *,
    doi: str = "",
    openalex_id: str = "",
    limit: int = 8,
) -> List[dict]:
    """Return similar-work findings from OpenAlex related_works."""
    wid = (openalex_id or "").strip()
    if not wid and doi:
        wid = _openalex_id_from_doi(doi.strip()) or ""

    if not wid:
        return []

    if wid.startswith("http"):
        wid = wid.rsplit("/", 1)[-1]

    filter_val = f"related_to:{wid}"
    url = (
        f"{_OPENALEX_BASE}/works?"
        f"filter={urllib.parse.quote(filter_val, safe=':')}&per_page={min(limit, 25)}"
        f"&select=id,title,doi,publication_year,authorships,type,abstract_inverted_index"
    )
    data = _http_json(url)
    if not data:
        return []

    findings: List[dict] = []
    for work in data.get("results") or []:
        f = _finding_from_openalex_work(work)
        if f:
            findings.append(f)
        if len(findings) >= limit:
            break
    return findings


def semantic_scholar_recommendations(
    *,
    doi: str = "",
    paper_id: str = "",
    limit: int = 8,
) -> List[dict]:
    """Return recommendation findings from Semantic Scholar."""
    pid = (paper_id or "").strip()
    if not pid and doi:
        pid = f"DOI:{doi.strip()}"
    if not pid:
        return []

    fields = "title,authors,year,abstract,url,externalIds,isOpenAccess,openAccessPdf,citationCount"
    encoded_pid = urllib.parse.quote(pid, safe=":")
    url = f"{_S2_BASE}/recommendations/v1/papers/forpaper/{encoded_pid}?fields={fields}&limit={min(limit, 25)}"
    data = _http_json(url)
    if not data:
        return []

    findings: List[dict] = []
    for paper in data.get("recommendedPapers") or []:
        f = _finding_from_s2_paper(paper)
        if f:
            findings.append(f)
        if len(findings) >= limit:
            break
    return findings


def _rank_similar(finding: dict) -> float:
    score = 0.0
    if finding.get("peer_review_status") == "peer-reviewed":
        score += 2.0
    try:
        yr = int(finding.get("year") or 0)
        if yr >= 2020:
            score += 1.5
        elif yr >= 2015:
            score += 1.0
    except ValueError:
        pass
    cite = finding.get("citation_count")
    if isinstance(cite, (int, float)):
        score += min(cite / 100.0, 3.0)
    if finding.get("similar_source") == "semantic_scholar":
        score += 0.25
    if finding.get("evidence") and len(finding["evidence"]) > 200:
        score += 0.5
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
) -> SimilarPapersOutcome:
    """Fallback similar-paper pass via OpenAlex + Semantic Scholar APIs."""
    from src.research_relevance import build_relevance_query, is_similar_paper_relevant

    exclude = {k.upper() for k in (exclude_keys or set()) if k}
    seen: Set[str] = set()
    pooled: List[dict] = []
    oa_count = 0
    s2_count = 0
    gate_q = (relevance_query or build_relevance_query("", seed_findings=seed_findings)).strip()

    for seed in seed_findings or []:
        if not seed.get("is_seed") and not seed.get("paper_key"):
            continue
        doi = (seed.get("doi_or_id") or "").strip()
        if doi and not doi.startswith("10."):
            doi = ""
        if not doi:
            # Try to pull DOI from URL
            url = seed.get("url") or ""
            m = re.search(r"doi\.org/(10\.\S+)", url, re.I)
            if m:
                doi = m.group(1).rstrip("/")

        per_seed = max(limit_per_seed, 1)
        for f in openalex_similar_works(doi=doi, limit=per_seed):
            key = _dedupe_key(f)
            if key in seen:
                continue
            zkey = (seed.get("paper_key") or seed.get("zotero_key") or "").upper()
            if zkey and zkey in exclude:
                continue
            seen.add(key)
            pooled.append(f)
            oa_count += 1

        for f in semantic_scholar_recommendations(doi=doi, limit=per_seed):
            key = _dedupe_key(f)
            if key in seen:
                continue
            seen.add(key)
            pooled.append(f)
            s2_count += 1

    if gate_q:
        pooled = [
            f for f in pooled
            if is_similar_paper_relevant(f, gate_q, seed_findings)
        ]

    pooled.sort(key=_rank_similar, reverse=True)
    findings = pooled[: max(total_limit, 1)]
    note = (
        f"Similar papers (API fallback): {len(findings)} "
        f"(OpenAlex {oa_count}, Semantic Scholar {s2_count})"
    )
    return SimilarPapersOutcome(findings, oa_count, s2_count, note=note)
