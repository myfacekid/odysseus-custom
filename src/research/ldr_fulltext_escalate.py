"""LDR Phase L7 — full-text escalation when LDR Fetch Content and PMC alone fail."""
from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, List, Optional, Tuple

from src.research_paper_fetch import is_usable_paper_content, normalize_doi

logger = logging.getLogger(__name__)

_USER_AGENT = "Odysseus-DeepResearch/1.0 (mailto:support@example.com)"
_OPENALEX_BASE = "https://api.openalex.org"
_S2_BASE = "https://api.semanticscholar.org/graph/v1/paper"

_PREPRINT_DOI_PREFIXES = ("10.1101/", "10.64898/")


def _http_json(url: str, *, timeout: int = 20) -> Optional[dict]:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": _USER_AGENT, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
        logger.info("Fulltext escalate API failed (%s): %s", url[:80], exc)
        return None


def _http_bytes(url: str, *, timeout: int = 25) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": _USER_AGENT,
            "Accept": "application/pdf,*/*",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
        logger.info("Fulltext escalate fetch failed (%s): %s", url[:80], exc)
        return b""


def _openalex_abstract(work: dict) -> str:
    inv = work.get("abstract_inverted_index")
    if not isinstance(inv, dict) or not inv:
        return ""
    positions: List[Tuple[int, str]] = []
    for word, idxs in inv.items():
        if not isinstance(idxs, list):
            continue
        for idx in idxs:
            try:
                positions.append((int(idx), str(word)))
            except (TypeError, ValueError):
                continue
    if not positions:
        return ""
    positions.sort(key=lambda x: x[0])
    return " ".join(w for _, w in positions).strip()


def fetch_openalex_by_doi(doi: str) -> Dict[str, str]:
    """OpenAlex work metadata: abstract and OA PDF URL."""
    doi = normalize_doi(doi)
    if not doi.startswith("10."):
        return {}
    url = f"{_OPENALEX_BASE}/works/https://doi.org/{urllib.parse.quote(doi, safe='')}"
    work = _http_json(url)
    if not work:
        return {}
    out: Dict[str, str] = {}
    abstract = _openalex_abstract(work)
    if abstract and is_usable_paper_content(abstract):
        out["abstract"] = abstract[:15000]
        out["source"] = "openalex"
        out["source_url"] = work.get("id") or f"https://doi.org/{doi}"
    oa = work.get("open_access") or {}
    best = work.get("best_oa_location") or {}
    primary = work.get("primary_location") or {}
    pdf_url = (
        (best.get("pdf_url") or "").strip()
        or (primary.get("pdf_url") or "").strip()
        or (oa.get("oa_url") or "").strip()
    )
    if pdf_url.startswith("http"):
        out["pdf_url"] = pdf_url
    return out


def fetch_semantic_scholar_by_doi(doi: str) -> Dict[str, str]:
    """Semantic Scholar metadata: abstract and OA PDF URL."""
    doi = normalize_doi(doi)
    if not doi.startswith("10."):
        return {}
    q = urllib.parse.quote(f"DOI:{doi}", safe="")
    url = f"{_S2_BASE}/{q}?fields=title,abstract,openAccessPdf,isOpenAccess,externalIds"
    data = _http_json(url, timeout=25)
    if not data:
        return {}
    out: Dict[str, str] = {}
    abstract = (data.get("abstract") or "").strip()
    if abstract and is_usable_paper_content(abstract):
        out["abstract"] = abstract[:15000]
        out["source"] = "semantic_scholar"
        out["source_url"] = f"https://www.semanticscholar.org/paper/{data.get('paperId') or doi}"
    oa_pdf = data.get("openAccessPdf") or {}
    if isinstance(oa_pdf, dict):
        pdf_url = (oa_pdf.get("url") or "").strip()
        if pdf_url.startswith("http"):
            out["pdf_url"] = pdf_url
    return out


def _preprint_fulltext_urls(doi: str) -> List[str]:
    """Candidate bioRxiv / medRxiv full-text URLs for a DOI."""
    doi = normalize_doi(doi)
    if not doi.startswith("10."):
        return []
    if not any(doi.startswith(p) for p in _PREPRINT_DOI_PREFIXES):
        return []
    encoded = urllib.parse.quote(doi, safe="/")
    hosts = ("www.biorxiv.org", "www.medrxiv.org")
    urls: List[str] = []
    for host in hosts:
        base = f"https://{host}/content/{encoded}"
        urls.extend([f"{base}.full", f"{base}v1.full", base])
    return urls


def fetch_preprint_fulltext(doi: str, *, title: str = "", max_chars: int = 50000) -> Dict[str, str]:
    """Fetch bioRxiv/medRxiv full-text HTML when available."""
    for url in _preprint_fulltext_urls(doi):
        try:
            from src.search.content import fetch_webpage_content

            page = fetch_webpage_content(url, timeout=15, include_og_image=False)
        except Exception as exc:
            logger.info("Preprint fetch failed (%s): %s", url[:80], exc)
            continue
        content = (page.get("content") or "").strip()
        if page.get("success") and is_usable_paper_content(content, title=title):
            return {
                "fulltext": content[:max_chars],
                "source": "biorxiv_full",
                "source_url": url,
            }
    return {}


def fetch_pdf_text_from_url(url: str, *, max_chars: int = 50000) -> str:
    """Download a PDF URL and extract text."""
    if not url or not url.startswith("http"):
        return ""
    try:
        raw = _http_bytes(url)
        if not raw:
            return ""
        from src.search.content import _extract_pdf_bytes

        text = _extract_pdf_bytes(raw, max_chars=max_chars)
        return text.strip()
    except Exception as exc:
        logger.info("PDF text extract failed (%s): %s", url[:80], exc)
        return ""


def escalate_fulltext_by_doi(
    doi: str,
    *,
    title: str = "",
    max_chars: int = 50000,
    fetch_fulltext: bool = True,
) -> Dict[str, str]:
    """Best-effort abstract + full text via OpenAlex, S2, OA PDF, and preprint pages."""
    doi = normalize_doi(doi)
    if not doi.startswith("10."):
        return {}

    from src.research_paper_fetch import resolve_paper_content_by_doi

    try:
        best: Dict[str, str] = dict(
            resolve_paper_content_by_doi(doi, title=title, fetch_fulltext=fetch_fulltext)
        )
    except Exception as exc:
        logger.warning("PMC/PubMed resolve failed for %s: %s", doi, exc)
        best = {}

    for fetcher in (fetch_openalex_by_doi, fetch_semantic_scholar_by_doi):
        try:
            meta = fetcher(doi)
        except Exception as exc:
            logger.warning("Fulltext metadata fetcher failed for %s: %s", doi, exc)
            continue
        if meta.get("abstract") and len(meta["abstract"]) > len(best.get("abstract", "")):
            best["abstract"] = meta["abstract"]
            best["source"] = meta.get("source") or best.get("source", "")
            if meta.get("source_url"):
                best["source_url"] = meta["source_url"]
        if fetch_fulltext and not best.get("fulltext") and meta.get("pdf_url"):
            pdf_text = fetch_pdf_text_from_url(meta["pdf_url"], max_chars=max_chars)
            if is_usable_paper_content(pdf_text, title=title):
                best["fulltext"] = pdf_text[:max_chars]
                best["source"] = f"{meta.get('source', 'oa')}_pdf"
                best["source_url"] = meta["pdf_url"]

    if fetch_fulltext and not best.get("fulltext"):
        try:
            preprint = fetch_preprint_fulltext(doi, title=title, max_chars=max_chars)
        except Exception as exc:
            logger.warning("Preprint fulltext failed for %s: %s", doi, exc)
            preprint = {}
        if preprint.get("fulltext"):
            best.update(preprint)

    return best


def sourcing_tier_counts(registry, findings: Optional[List[dict]] = None) -> Dict[str, int]:
    """Histogram of sourcing tiers across registry sources (for smoke / E2E)."""
    from src.research.ldr_content_enrich import _finding_for_source
    from src.research_sourcing import assess_finding_sourcing

    counts: Dict[str, int] = {}
    for src in registry.sources():
        f = _finding_for_source(registry, findings or [], src.citation_num) or {}
        tier, _, _ = assess_finding_sourcing(f if f else {"title": src.title, "content": src.content_excerpt})
        counts[tier] = counts.get(tier, 0) + 1
    return counts


def format_sourcing_summary(registry, findings: Optional[List[dict]] = None) -> str:
    """Human-readable sourcing breakdown for logs."""
    counts = sourcing_tier_counts(registry, findings)
    total = sum(counts.values()) or 1
    from src.research_sourcing import SOURCING_TIER_ABSTRACT_ONLY, SOURCING_TIER_ADEQUATE

    usable = counts.get(SOURCING_TIER_ADEQUATE, 0) + counts.get(SOURCING_TIER_ABSTRACT_ONLY, 0)
    parts = [f"{tier}={n}" for tier, n in sorted(counts.items(), key=lambda x: -x[1])]
    return f"sourcing: {usable}/{total} abstract+ ({usable * 100 // total}%) — " + ", ".join(parts)
