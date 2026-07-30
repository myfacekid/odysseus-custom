"""Keyword academic search for similar-paper discovery (replaces co-citation APIs)."""
from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from src.research_engines.registry import DEFAULT_SIMILAR_ENGINES

logger = logging.getLogger(__name__)

_USER_AGENT = "Nobody-DeepResearch/1.0 (mailto:support@example.com)"
_OPENALEX_BASE = "https://api.openalex.org"
_S2_BASE = "https://api.semanticscholar.org/graph/v1"


@dataclass
class KeywordSearchOutcome:
    findings: List[dict]
    engine_counts: Dict[str, int] = field(default_factory=dict)
    note: str = ""


def build_seed_search_queries(seed: dict, *, max_queries: int = 2) -> List[str]:
    """Derive keyword queries from a seed finding (title-first, no co-citation)."""
    queries: List[str] = []
    title = (seed.get("title") or "").strip()
    if title:
        queries.append(title[:140])
        short = title.split(":")[0].strip()
        if short and short != title and len(short) > 12:
            queries.append(short[:120])

    abstract = (
        seed.get("content")
        or seed.get("evidence")
        or seed.get("summary")
        or ""
    ).strip()
    if abstract and len(queries) < max_queries:
        sentence = re.split(r"[.!?]\s+", abstract)[0].strip()
        if len(sentence) > 20:
            queries.append(sentence[:140])

    # Deduplicate while preserving order
    seen: Set[str] = set()
    out: List[str] = []
    for q in queries:
        key = q.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(q)
        if len(out) >= max_queries:
            break
    return out


def _http_json(url: str, *, headers: Optional[dict] = None, timeout: int = 20) -> Optional[dict]:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": _USER_AGENT, "Accept": "application/json", **(headers or {})},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as e:
        logger.info("Keyword search HTTP failed (%s): %s", url[:80], e)
        return None


def preview_to_finding(preview: dict, engine_name: str) -> Optional[dict]:
    """Map an LDR search preview dict to an Nobody similar-paper finding."""
    if not preview:
        return None
    title = (preview.get("title") or "").strip()
    if not title:
        return None
    url = (preview.get("link") or preview.get("url") or "").strip()
    snippet = (preview.get("snippet") or preview.get("abstract") or title)[:15000]
    doi = (preview.get("doi") or "").replace("https://doi.org/", "").strip()
    if not url and doi:
        url = f"https://doi.org/{doi}"

    authors = preview.get("authors") or ""
    if isinstance(authors, list):
        authors = ", ".join(str(a) for a in authors[:6] if a)

    year = str(preview.get("year") or preview.get("publication_year") or "")
    cite = preview.get("citations") or preview.get("citation_count")
    peer = "peer-reviewed"
    if preview.get("is_open_access") or preview.get("isOpenAccess"):
        peer = "open access"

    label = engine_name.replace("_", " ").title()
    return {
        "url": url or title,
        "title": title,
        "rational": f"Similar work from {label} keyword search",
        "evidence": snippet,
        "summary": snippet[:800],
        "authors": authors,
        "year": year,
        "doi_or_id": doi or preview.get("paperId") or "",
        "peer_review_status": peer,
        "study_type": "journalArticle",
        "source_type": "similar_paper",
        "similar_source": engine_name,
        "citation_count": cite,
    }


def _openalex_keyword_native(query: str, *, limit: int, email: str = "") -> List[dict]:
    from src.research_similar_papers import _finding_from_openalex_work

    params = {
        "search": query,
        "per_page": min(limit, 25),
        "select": "id,title,doi,publication_year,authorships,type,abstract_inverted_index,cited_by_count",
    }
    if email:
        params["mailto"] = email
    url = f"{_OPENALEX_BASE}/works?{urllib.parse.urlencode(params)}"
    data = _http_json(url)
    if not data:
        return []
    findings: List[dict] = []
    for work in data.get("results") or []:
        f = _finding_from_openalex_work(work)
        if f:
            f["rational"] = "Similar work from OpenAlex keyword search"
            f["similar_source"] = "openalex"
            findings.append(f)
        if len(findings) >= limit:
            break
    return findings


def _s2_keyword_native(query: str, *, limit: int, api_key: str = "") -> List[dict]:
    from src.research_similar_papers import _finding_from_s2_paper

    fields = "title,authors,year,abstract,url,externalIds,isOpenAccess,openAccessPdf,citationCount"
    params = urllib.parse.urlencode({"query": query, "limit": min(limit, 25), "fields": fields})
    headers = {"x-api-key": api_key} if api_key else None
    url = f"{_S2_BASE}/paper/search?{params}"
    data = _http_json(url, headers=headers)
    if not data:
        return []
    findings: List[dict] = []
    for paper in data.get("data") or []:
        f = _finding_from_s2_paper(paper)
        if f:
            f["rational"] = "Similar work from Semantic Scholar keyword search"
            f["similar_source"] = "semantic_scholar"
            findings.append(f)
        if len(findings) >= limit:
            break
    return findings


def _engine_keyword_search(
    engine_name: str,
    query: str,
    *,
    limit: int,
    include_preprints: bool = True,
) -> List[dict]:
    """Keyword search on one engine — LDR when installed, native HTTP fallback."""
    engine_name = (engine_name or "").strip().lower()
    if not engine_name or not query.strip():
        return []

    try:
        from src.research_engines.ldr_factory import close_engine, create_academic_engine, ldr_engines_available

        if ldr_engines_available():
            engine = create_academic_engine(
                engine_name,
                max_results=limit,
                include_preprints=include_preprints,
            )
            try:
                previews = engine._get_previews(query.strip())  # noqa: SLF001 — LDR two-phase contract
                findings = []
                for preview in previews or []:
                    f = preview_to_finding(preview, engine_name)
                    if f:
                        findings.append(f)
                    if len(findings) >= limit:
                        break
                return findings
            finally:
                close_engine(engine)
    except Exception as e:
        logger.info("LDR engine %s keyword search failed, using native fallback: %s", engine_name, e)

    from src.research_engines.settings_bridge import _nobody_settings

    settings = _nobody_settings()
    if engine_name == "openalex":
        email = (settings.get("openalex_email") or "").strip()
        return _openalex_keyword_native(query, limit=limit, email=email)
    if engine_name == "semantic_scholar":
        key = (settings.get("semantic_scholar_api_key") or "").strip()
        return _s2_keyword_native(query, limit=limit, api_key=key)
    return []


def keyword_search_findings(
    queries: List[str],
    *,
    engines: Tuple[str, ...] = DEFAULT_SIMILAR_ENGINES,
    limit_per_query: int = 5,
    include_preprints: bool = True,
) -> KeywordSearchOutcome:
    """Run keyword search across engines; dedupe by DOI/URL."""
    seen: Set[str] = set()
    pooled: List[dict] = []
    counts: Dict[str, int] = {e: 0 for e in engines}

    def _dedupe_key(finding: dict) -> str:
        doi = (finding.get("doi_or_id") or "").strip().lower()
        if doi.startswith("10."):
            return f"doi:{doi}"
        url = (finding.get("url") or "").strip().lower().rstrip("/")
        return f"url:{url}" if url else f"title:{(finding.get('title') or '').lower()}"

    for query in queries:
        q = (query or "").strip()
        if not q:
            continue
        for engine in engines:
            for f in _engine_keyword_search(
                engine,
                q,
                limit=limit_per_query,
                include_preprints=include_preprints,
            ):
                key = _dedupe_key(f)
                if key in seen:
                    continue
                seen.add(key)
                pooled.append(f)
                counts[engine] = counts.get(engine, 0) + 1

    parts = [f"{k} {v}" for k, v in counts.items() if v]
    note = f"Keyword search: {len(pooled)} ({', '.join(parts)})" if pooled else "Keyword search: 0 results"
    return KeywordSearchOutcome(findings=pooled, engine_counts=counts, note=note)
