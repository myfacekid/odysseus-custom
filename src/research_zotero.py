"""Deep Research Zotero integration — local catalog first (Phase 1b).

Uses ``search_catalog()`` + ``fetch_paper_pdf_text()`` (same path as
``read_knowledge_content(paper:KEY)``) before falling back to the live
Zotero Web API when the catalog is empty, stale, or has no matches.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ResearchZoteroOutcome:
    findings: List[dict]
    query: str
    source: str  # catalog | live_api | none
    catalog_synced: bool
    note: str = ""


def seed_catalog_rows(owner: str, limit: int) -> List[dict]:
    """Recent catalog papers for library seeding — prefer items with PDFs."""
    from src.zotero_catalog import load_catalog

    rows = list(load_catalog(owner))
    if not rows:
        return []

    def _sort_key(row: dict) -> tuple:
        return (
            row.get("date_modified") or "",
            row.get("date_added") or "",
        )

    rows.sort(key=_sort_key, reverse=True)
    with_pdf = [r for r in rows if r.get("has_pdf")]
    without_pdf = [r for r in rows if not r.get("has_pdf")]
    pool = with_pdf + without_pdf
    return pool[: max(limit, 1)]


def catalog_row_to_finding(
    row: dict,
    user_id: str,
    *,
    pdf_text: str = "",
    zotero_source: str = "catalog",
) -> dict:
    """Convert a catalog row into a Deep Research finding dict."""
    from src.zotero_client import _item_type_label, _peer_status

    key = (row.get("zotero_key") or "").strip()
    title = row.get("title") or "Untitled"
    authors = row.get("authors") or ""
    year = str(row.get("year") or "")
    doi = (row.get("doi") or "").strip()
    if not doi:
        from src.research_finding_enrich import extract_doi
        doi = extract_doi(row.get("url") or "")
    abstract = (row.get("abstract") or "").strip()
    item_type = row.get("item_type") or "journalArticle"
    url = (row.get("url") or "").strip()
    if not url:
        url = (
            doi if doi.startswith("http")
            else (f"https://doi.org/{doi}" if doi else f"https://www.zotero.org/users/{user_id}/items/{key}")
        )

    evidence_parts: List[str] = []
    if abstract:
        evidence_parts.append(abstract)
    if pdf_text:
        evidence_parts.append(pdf_text)
    if not evidence_parts:
        extra = (row.get("url") or "").strip()
        if extra:
            evidence_parts.append(extra)
    evidence = "\n\n".join(evidence_parts)[:15000]

    summary = abstract[:2000] if abstract else ""
    if not summary and not (evidence and len(evidence) >= 220):
        summary = f"Bibliographic record: {title}"
    rational = (
        "Matched from local Zotero catalog"
        if zotero_source == "catalog"
        else "Matched via live Zotero API (catalog had no match)"
    )

    finding = {
        "url": url,
        "title": title,
        "rational": rational,
        "evidence": evidence,
        "summary": summary,
        "authors": authors,
        "year": year,
        "doi_or_id": doi or key,
        "study_type": _item_type_label(item_type),
        "peer_review_status": _peer_status(item_type),
        "source_type": "zotero",
        "zotero_key": key,
        "paper_key": key,
        "zotero_source": zotero_source,
        "has_pdf": bool(row.get("has_pdf")),
        "collection_paths": list(row.get("collection_paths") or []),
    }
    if abstract:
        finding["abstract"] = abstract
    if pdf_text:
        finding["pdf_extracted"] = True
    return finding


def findings_from_catalog_rows(
    owner: str,
    rows: List[dict],
    *,
    extract_pdfs: bool = True,
    pdf_max_chars: int = 15000,
) -> List[dict]:
    """Build findings from catalog rows, extracting PDFs via fetch_paper_pdf_text."""
    from src.zotero_client import fetch_paper_pdf_text, resolve_zotero_credentials

    creds = resolve_zotero_credentials(owner)
    if not creds or not rows:
        return []

    findings: List[dict] = []
    for row in rows:
        key = (row.get("zotero_key") or "").strip()
        if not key:
            continue
        pdf_text = ""
        pdf_note = ""
        if extract_pdfs:
            pdf_text, pdf_note = fetch_paper_pdf_text(owner, key, max_chars=pdf_max_chars)
            if pdf_note and not pdf_text:
                logger.info("Zotero PDF for %s: %s", key, pdf_note)
        finding = catalog_row_to_finding(
            row, creds["user_id"], pdf_text=pdf_text, zotero_source="catalog",
        )
        if extract_pdfs and not pdf_text and pdf_note:
            finding["pdf_fetch_failed"] = True
            finding["pdf_fetch_note"] = pdf_note
        elif pdf_note and not pdf_text and row.get("has_pdf"):
            finding["pdf_fetch_failed"] = True
            finding["pdf_fetch_note"] = pdf_note
        findings.append(finding)
    return findings


def _catalog_search_rows(
    owner: str,
    query: str,
    *,
    limit: int,
    seed_library: bool,
) -> List[dict]:
    from src.zotero_catalog import search_catalog

    q = (query or "").strip()
    limit = max(limit, 1)

    if seed_library and not q:
        return seed_catalog_rows(owner, limit)

    if q:
        hits = search_catalog(owner, q, limit=limit)
        return hits

    if seed_library:
        return seed_catalog_rows(owner, limit)
    return []


def research_zotero_findings(
    query: str,
    owner: str = "",
    *,
    limit: int = 5,
    extract_pdfs: bool = False,
    seed_library: bool = False,
    pdf_max_chars: int = 15000,
) -> ResearchZoteroOutcome:
    """Search the user's Zotero library for Deep Research (catalog first)."""
    from src.zotero_catalog import catalog_stats, load_catalog
    from src.zotero_client import (
        ZoteroClient,
        findings_from_items,
        resolve_zotero_credentials,
    )

    owner = (owner or "").strip()
    if not owner:
        return ResearchZoteroOutcome([], query, "none", False, "No research owner")

    creds = resolve_zotero_credentials(owner)
    if not creds:
        return ResearchZoteroOutcome([], query, "none", False, "Zotero not configured")

    stats = catalog_stats(owner)
    catalog_synced = bool(stats.get("synced"))

    if catalog_synced:
        rows = _catalog_search_rows(owner, query, limit=limit, seed_library=seed_library)
        if rows:
            findings = findings_from_catalog_rows(
                owner,
                rows,
                extract_pdfs=extract_pdfs,
                pdf_max_chars=pdf_max_chars,
            )
            logger.info(
                "Research Zotero (catalog): %d finding(s) for %r (seed=%s)",
                len(findings), query, seed_library,
            )
            return ResearchZoteroOutcome(
                findings,
                query,
                "catalog",
                True,
                f"Local catalog ({len(findings)} paper(s), synced {stats.get('synced_at') or 'unknown'})",
            )

    # Live API fallback — catalog missing, empty, or no matches.
    client = ZoteroClient(creds["api_key"], creds["user_id"])
    items = client.search_items(query, limit=limit, seed_library=seed_library)
    catalog_rows = load_catalog(owner)
    findings = findings_from_items(
        client,
        creds["user_id"],
        items,
        extract_pdfs=extract_pdfs,
        catalog_rows=catalog_rows,
    )
    for finding in findings:
        finding["zotero_source"] = "live_api"
        finding["paper_key"] = finding.get("zotero_key") or ""

    note = (
        "Used live Zotero API — sync catalog in Settings → Search → Zotero for faster local search."
        if not catalog_synced
        else "Catalog had no matches; used live Zotero API."
    )
    logger.info(
        "Research Zotero (live API): %d finding(s) for %r (seed=%s)",
        len(findings), query, seed_library,
    )
    return ResearchZoteroOutcome(
        findings,
        query,
        "live_api",
        catalog_synced,
        note if findings else f"{note} No items matched.",
    )
