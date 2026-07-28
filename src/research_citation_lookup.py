"""Forward-citation ("papers that cite/use X") discovery for Deep Research.

The default retrieval pipeline does lexical web search + relevance gating, which
cannot answer bibliometric queries like *"find the most cited papers that use the
3Di alphabet from the Foldseek paper"* — the downstream papers rarely repeat the
seed paper's name, so lexical gating rejects them and only the seed survives.

This module detects that intent, resolves the referenced paper in OpenAlex, and
pulls the works that CITE it (ranked by citation count) via the OpenAlex
``cites:`` filter. The returned findings are authoritative answers to the query,
so callers inject them directly and flag them ``always_include`` so synthesis
never drops them for weak lexical overlap.
"""
from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import List, Optional

logger = logging.getLogger(__name__)

_USER_AGENT = "Nobody-DeepResearch/1.0 (mailto:support@example.com)"
_OPENALEX_BASE = "https://api.openalex.org"

# Verbs that signal the user wants derivative/citing work, not the paper itself.
_CITATION_VERB_RE = re.compile(
    r"\b(cite[sd]?|citing|citation|citations|references?|referenced|"
    r"uses?|using|utili[sz]e[sd]?|appl(?:y|ies|ied)|adopt(?:s|ed|ing)?|"
    r"build(?:s|ing)?\s+on|based\s+on|building\s+upon|extend(?:s|ed|ing)?|"
    r"derived\s+from|that\s+employ)\b",
    re.I,
)

# "the Foldseek paper", "the 3Di method", "the AlphaFold model", etc.
_TARGET_PAPER_RE = re.compile(
    r"\b(?:the\s+)?([A-Za-z][\w.+\-]{1,40})\s+"
    r"(?:paper|method|model|algorithm|framework|tool|approach|alphabet|"
    r"architecture|dataset|benchmark|technique|pipeline)\b",
    re.I,
)

# "papers that cite Foldseek", "works citing AlphaFold"
_CITES_NAME_RE = re.compile(
    r"\bcit(?:e|es|ing|ed)\b(?:\s+by)?\s+(?:the\s+)?"
    r"([A-Z][A-Za-z0-9][A-Za-z0-9.\-]{1,40})",
)

_STOP_TARGETS = {
    "this", "that", "these", "those", "each", "same", "other", "such",
    "original", "source", "seed", "given", "above", "cited", "most", "their",
    "research", "review", "recent", "current", "following", "present",
}


def has_citation_intent(question: str) -> bool:
    """True when the query asks for work that cites/uses/builds on something."""
    return bool(_CITATION_VERB_RE.search(question or ""))


def detect_citation_target(question: str) -> Optional[str]:
    """Return the referenced paper/method name when the query asks for citing work.

    Returns ``None`` when the query is not a forward-citation ("papers that
    cite/use X") request.
    """
    q = (question or "").strip()
    if not q:
        return None
    if not _CITATION_VERB_RE.search(q):
        return None

    candidates: List[str] = []
    for m in _TARGET_PAPER_RE.finditer(q):
        candidates.append(m.group(1))
    for m in _CITES_NAME_RE.finditer(q):
        candidates.append(m.group(1))

    for raw in candidates:
        name = (raw or "").strip().strip(".,;:")
        if len(name) < 3:
            continue
        if name.lower() in _STOP_TARGETS:
            continue
        return name
    return None


def _http_json(url: str, *, timeout: int = 20) -> Optional[dict]:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": _USER_AGENT, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as e:
        logger.info("OpenAlex citation lookup failed (%s): %s", url[:80], e)
        return None


_WORK_SELECT = "id,title,display_name,doi,publication_year,cited_by_count"


def _normalize_doi_for_lookup(value: str) -> str:
    raw = (value or "").strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if raw.startswith(prefix):
            raw = raw[len(prefix):].strip()
            break
    return raw.rstrip(".,;)/") if raw.startswith("10.") else ""


def resolve_openalex_work(name: str, *, doi: str = "", email: str = "") -> Optional[dict]:
    """Resolve a paper by DOI (preferred) or name to its OpenAlex work."""
    clean_doi = _normalize_doi_for_lookup(doi) or _normalize_doi_for_lookup(name)
    if clean_doi:
        params = {"select": _WORK_SELECT + ",referenced_works"}
        if email:
            params["mailto"] = email
        url = f"{_OPENALEX_BASE}/works/doi:{clean_doi}?{urllib.parse.urlencode(params)}"
        work = _http_json(url)
        if work and work.get("id"):
            return work

    q = (name or "").strip()
    if not q:
        return None
    params = {
        "search": q,
        "per_page": 5,
        "select": _WORK_SELECT + ",referenced_works",
    }
    if email:
        params["mailto"] = email
    url = f"{_OPENALEX_BASE}/works?{urllib.parse.urlencode(params)}"
    data = _http_json(url)
    results = (data or {}).get("results") or []
    if not results:
        return None
    # OpenAlex returns results ranked by relevance; prefer the top hit but, when
    # several closely match the name, favour the most-cited (the seminal paper).
    name_l = q.lower()
    named = [
        w for w in results
        if name_l in ((w.get("title") or w.get("display_name") or "").lower())
    ]
    pool = named or results
    pool.sort(key=lambda w: int(w.get("cited_by_count") or 0), reverse=True)
    return pool[0]


def _openalex_work_id(work: dict) -> str:
    raw = (work.get("id") or "").strip()
    return raw.rsplit("/", 1)[-1] if raw else ""


_CITING_SELECT = (
    "id,title,display_name,doi,publication_year,authorships,type,"
    "abstract_inverted_index,cited_by_count"
)


def _fetch_works_by_ids(ids: List[str], *, email: str = "") -> List[dict]:
    """Batch-fetch OpenAlex works by id (used for backward references)."""
    short = [i.rsplit("/", 1)[-1] for i in ids if i]
    out: List[dict] = []
    chunk = 40
    for k in range(0, len(short), chunk):
        batch = short[k:k + chunk]
        params = {
            "filter": f"openalex_id:{'|'.join(batch)}",
            "per_page": len(batch),
            "select": _CITING_SELECT,
        }
        if email:
            params["mailto"] = email
        url = f"{_OPENALEX_BASE}/works?{urllib.parse.urlencode(params)}"
        data = _http_json(url)
        out.extend((data or {}).get("results") or [])
    return out


def fetch_citing_works(
    name: str,
    *,
    doi: str = "",
    limit: int = 25,
    email: str = "",
    include_preprints: bool = True,
) -> List[dict]:
    """Return findings for works that cite the named paper, most-cited first."""
    from src.research_similar_papers import _finding_from_openalex_work

    work = resolve_openalex_work(name, doi=doi, email=email)
    if not work:
        logger.info("Citation lookup: could not resolve '%s' in OpenAlex", name)
        return []
    work_id = _openalex_work_id(work)
    if not work_id:
        return []

    seed_title = (work.get("title") or work.get("display_name") or name).strip()
    params = {
        "filter": f"cites:{work_id}",
        "sort": "cited_by_count:desc",
        "per_page": min(max(int(limit), 1), 50),
        "select": _CITING_SELECT,
    }
    if email:
        params["mailto"] = email
    url = f"{_OPENALEX_BASE}/works?{urllib.parse.urlencode(params)}"
    data = _http_json(url)
    results = (data or {}).get("results") or []

    findings: List[dict] = []
    for work_item in results:
        finding = _finding_from_openalex_work(work_item)
        if not finding:
            continue
        if not include_preprints and (finding.get("peer_review_status") == "preprint"):
            continue
        cited_by = int(work_item.get("cited_by_count") or 0)
        finding["source_type"] = "citing_paper"
        finding["similar_source"] = "openalex_cited_by"
        finding["citation_count"] = cited_by
        finding["rational"] = (
            f"Cites \u201c{seed_title}\u201d (cited by {cited_by} works per OpenAlex)"
        )
        # Authoritative answer to the query — never gate/drop for lexical overlap.
        finding["always_include"] = True
        findings.append(finding)
        if len(findings) >= limit:
            break

    logger.info(
        "Citation lookup: '%s' -> OpenAlex %s -> %d citing work(s)",
        name, work_id, len(findings),
    )
    return findings


def fetch_referenced_works(
    name: str,
    *,
    doi: str = "",
    limit: int = 20,
    email: str = "",
    include_preprints: bool = True,
) -> List[dict]:
    """Return findings for the works a paper cites (backward citation), most-cited first."""
    from src.research_similar_papers import _finding_from_openalex_work

    work = resolve_openalex_work(name, doi=doi, email=email)
    if not work:
        return []
    refs = work.get("referenced_works") or []
    if not refs:
        return []
    seed_title = (work.get("title") or work.get("display_name") or name).strip()
    works = _fetch_works_by_ids(refs[: min(limit * 3, 120)], email=email)
    works.sort(key=lambda w: int(w.get("cited_by_count") or 0), reverse=True)

    findings: List[dict] = []
    for w in works:
        finding = _finding_from_openalex_work(w)
        if not finding:
            continue
        if not include_preprints and finding.get("peer_review_status") == "preprint":
            continue
        cited_by = int(w.get("cited_by_count") or 0)
        finding["source_type"] = "referenced_paper"
        finding["similar_source"] = "openalex_references"
        finding["citation_count"] = cited_by
        finding["rational"] = (
            f"Referenced by \u201c{seed_title}\u201d (cited by {cited_by} works per OpenAlex)"
        )
        finding["always_include"] = True
        findings.append(finding)
        if len(findings) >= limit:
            break
    logger.info(
        "Backward-citation: '%s' -> %d referenced work(s)", seed_title, len(findings),
    )
    return findings


def _dedupe_findings(findings: List[dict]) -> List[dict]:
    seen: set = set()
    out: List[dict] = []
    for f in findings:
        doi = (f.get("doi_or_id") or "").strip().lower()
        url = (f.get("url") or "").strip().lower().rstrip("/")
        key = f"doi:{doi}" if doi.startswith("10.") else (
            f"url:{url}" if url else f"title:{(f.get('title') or '').lower()}"
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(f)
    return out


def snowball_seed(
    seed_finding: dict,
    *,
    limit_each: int = 15,
    email: str = "",
    include_preprints: bool = True,
) -> List[dict]:
    """One-hop citation-graph expansion of a seed paper: forward + backward.

    Returns citing works (who built on this seed) plus the seed's own key
    references (what it built on), deduped and ranked by citation count.
    """
    title = (seed_finding.get("title") or "").strip()
    doi = (seed_finding.get("doi_or_id") or "").strip()
    if not title and not doi.startswith("10."):
        return []

    combined: List[dict] = []
    try:
        combined += fetch_citing_works(
            title or doi, doi=doi, limit=limit_each,
            email=email, include_preprints=include_preprints,
        )
    except Exception as exc:
        logger.info("snowball forward-citation failed: %s", exc)
    try:
        combined += fetch_referenced_works(
            title, doi=doi, limit=limit_each,
            email=email, include_preprints=include_preprints,
        )
    except Exception as exc:
        logger.info("snowball backward-citation failed: %s", exc)

    deduped = _dedupe_findings(combined)
    deduped.sort(key=lambda f: int(f.get("citation_count") or 0), reverse=True)
    return deduped
