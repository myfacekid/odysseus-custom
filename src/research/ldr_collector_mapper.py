"""Map Local Deep Research collector results to Nobody evidence findings."""
from __future__ import annotations

import logging
from typing import Callable, Dict, Iterable, List, Optional, Set
from urllib.parse import urlparse

from src.research.ldr_doi import (
    _coerce_text,
    dedupe_raw_links_by_doi,
    finding_text_richness,
)
from src.research_evidence import doi_from_finding
from src.research_finding_enrich import enrich_web_finding, normalize_finding_fields
from src.research_relevance import matches_avoid_topics

logger = logging.getLogger(__name__)


PREPRINT_HOST_FRAGMENTS = (
    "arxiv.org",
    "biorxiv.org",
    "medrxiv.org",
    "chemrxiv.org",
    "ssrn.com",
    "researchsquare.com",
    "preprints.org",
    "asapbio.org",
    "osf.io/preprints",
)


def is_preprint_url(url: str) -> bool:
    host = (urlparse((url or "").strip()).netloc or "").lower()
    if not host:
        return False
    return any(fragment in host for fragment in PREPRINT_HOST_FRAGMENTS)


def ldr_link_to_finding(
    raw: dict,
    *,
    search_query: str = "",
    engine_name: str = "",
) -> dict:
    """Convert one LDR collector / all_links entry to an Nobody finding dict."""
    url = _coerce_text(raw.get("link") or raw.get("url"))
    title = _coerce_text(raw.get("title") or "Untitled") or "Untitled"
    snippet = _coerce_text(
        raw.get("snippet")
        or raw.get("body")
        or raw.get("content")
        or raw.get("abstract")
        or ""
    )
    finding = {
        "title": title,
        "url": url,
        "content": snippet,
        "search_query": search_query,
        "search_provider": engine_name or raw.get("source_engine", "ldr"),
        "search_kind": "ldr",
        "similar_source": engine_name or raw.get("source_engine", "ldr"),
        "peer_review_status": "preprint" if is_preprint_url(url) else "",
        "study_type": _coerce_text(raw.get("study_type")),
        "authors": _coerce_text(raw.get("authors") or raw.get("author")),
        "year": _coerce_text(raw.get("year") or raw.get("published_date")),
        "doi_or_id": _coerce_text(raw.get("doi") or raw.get("doi_or_id")),
    }
    if raw.get("zotero_key"):
        finding["zotero_key"] = raw["zotero_key"]
    if raw.get("paper_key"):
        finding["paper_key"] = raw["paper_key"]
    normalize_finding_fields(finding)
    enrich_web_finding(finding, url=url, content=snippet)
    if not (finding.get("doi_or_id") or "").startswith("10.") and "doi.org/" in url.lower():
        from src.research_evidence import normalize_doi

        finding["doi_or_id"] = normalize_doi(url.rsplit("doi.org/", 1)[-1])
    return finding


def ingest_rejection_reason(
    finding: dict,
    *,
    include_preprints: bool,
    avoid_topics: Optional[Iterable[str]] = None,
    seen_urls: Optional[Set[str]] = None,
    seen_dois: Optional[Set[str]] = None,
    registry=None,
) -> Optional[str]:
    """Return a machine-readable rejection reason, or None if the finding may be ingested."""
    url = (finding.get("url") or "").strip()
    if seen_urls is not None and url and url in seen_urls:
        return "duplicate_url"
    doi = doi_from_finding(finding)
    if doi:
        if seen_dois is not None and doi in seen_dois:
            return "duplicate_doi"
        if registry is not None and getattr(registry, "has_doi", None) and registry.has_doi(doi):
            return "duplicate_doi"
    if not include_preprints and is_preprint_url(url):
        return "preprint_excluded"
    if avoid_topics:
        check = dict(finding)
        if finding.get("content") and not check.get("abstract"):
            check["abstract"] = finding.get("content")
        if matches_avoid_topics(check, list(avoid_topics)):
            return "avoid_topic"
    return None


def finding_passes_ingest_policy(
    finding: dict,
    *,
    include_preprints: bool,
    avoid_topics: Optional[Iterable[str]] = None,
    seen_urls: Optional[Set[str]] = None,
    seen_dois: Optional[Set[str]] = None,
    registry=None,
) -> bool:
    """Apply panel preprint toggle and plan avoid_topics before registry ingest."""
    return ingest_rejection_reason(
        finding,
        include_preprints=include_preprints,
        avoid_topics=avoid_topics,
        seen_urls=seen_urls,
        seen_dois=seen_dois,
        registry=registry,
    ) is None


def ingest_ldr_links(
    registry,
    links: List[dict],
    *,
    include_preprints: bool = True,
    avoid_topics: Optional[Iterable[str]] = None,
    seen_urls: Optional[Set[str]] = None,
    seen_dois: Optional[Set[str]] = None,
    is_seed: bool = False,
    on_reject: Optional[Callable[[dict, str], None]] = None,
) -> List[dict]:
    """Register LDR collector links; return newly accepted finding dicts."""
    accepted: List[dict] = []
    links, doi_dropped = dedupe_raw_links_by_doi(links or [])
    if doi_dropped:
        logger.info("LDR ingest: collapsed %d duplicate DOI row(s) before register", doi_dropped)

    if seen_dois is None:
        seen_dois = set()

    for raw in links:
        if not isinstance(raw, dict):
            continue
        engine = (raw.get("source_engine") or "ldr").strip()
        finding = ldr_link_to_finding(raw, engine_name=engine)
        reason = ingest_rejection_reason(
            finding,
            include_preprints=include_preprints,
            avoid_topics=avoid_topics,
            seen_urls=seen_urls,
            seen_dois=seen_dois,
            registry=registry,
        )
        if reason:
            if on_reject:
                on_reject(finding, reason)
            continue
        url = (finding.get("url") or "").strip()
        doi = doi_from_finding(finding)
        before = len(registry)
        registry.register(finding, is_seed=is_seed)
        if len(registry) > before:
            accepted.append(finding)
            if seen_urls is not None and url:
                seen_urls.add(url)
            if doi:
                seen_dois.add(doi)
        elif doi:
            # Merged into an existing registry row — prefer richer text on the canonical finding.
            existing = next(
                (f for f in accepted if doi_from_finding(f) == doi),
                None,
            )
            if existing and finding_text_richness(finding) > finding_text_richness(existing):
                existing.update(
                    {k: v for k, v in finding.items() if v and k not in ("source_id", "citation_num")}
                )
            if on_reject:
                on_reject(finding, "duplicate_doi")
    return accepted


def compile_gathering_draft(registry, *, max_excerpt: int = 400) -> str:
    """Build source-note lines from registry sources for the final report prompt."""
    lines: List[str] = []
    for src in registry.sources():
        excerpt = (src.content_excerpt or "").strip()
        if len(excerpt) > max_excerpt:
            excerpt = excerpt[: max_excerpt - 3].rstrip() + "..."
        lines.append(f"[{src.citation_num}] {src.title or 'Untitled'}: {excerpt or '(metadata only)'}")
    return "\n".join(lines) if lines else "(No gathered sources yet.)"
