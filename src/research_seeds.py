"""Resolve user seed papers for Deep Research (Phase 2).

Accepts Zotero keys, ``paper:KEY`` refs, bare DOIs, or ``doi:…`` strings and
loads catalog rows + PDF text via the same path as Phase 1b.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

_ZOTERO_KEY_RE = re.compile(r"^[A-Z0-9]{8}$", re.I)
_DOI_RE = re.compile(r"^10\.\d{4,9}/\S+", re.I)


@dataclass
class SeedPaperOutcome:
    findings: List[dict]
    resolved_keys: List[str]
    missing: List[str]
    note: str = ""


def normalize_seed_ref(ref: str) -> str:
    """Normalize a user-provided seed reference string."""
    raw = (ref or "").strip()
    if not raw:
        return ""
    lower = raw.lower()
    if lower.startswith("paper:"):
        return raw.split(":", 1)[1].strip().upper()
    if lower.startswith("doi:"):
        raw = raw[4:].strip()
    for prefix in (
        "https://doi.org/",
        "http://doi.org/",
        "https://dx.doi.org/",
        "http://dx.doi.org/",
    ):
        if lower.startswith(prefix):
            raw = raw[len(prefix) :].strip()
            break
    if _ZOTERO_KEY_RE.match(raw):
        return raw.upper()
    return raw


_TIER_PREVIEW_LABELS = {
    "adequate": "Full text likely (PDF in library)",
    "abstract_only": "Abstract only",
    "metadata_only": "Metadata only",
    "retrieval_failed": "PDF not extracted",
    "unsourced": "Not sourced",
    "unknown": "Resolve at run time",
}


def _preview_from_catalog_row(row: dict, *, user_id: str = "") -> dict:
    from src.research_sourcing import annotate_finding_sourcing
    from src.research_zotero import catalog_row_to_finding

    finding = catalog_row_to_finding(row, user_id, pdf_text="", zotero_source="catalog")
    annotate_finding_sourcing(finding)
    tier = (finding.get("sourcing_tier") or "unknown").strip()
    # Preview does not extract PDFs. If the catalog says a PDF exists, forecast
    # full-text-likely at run time instead of grading the empty pdf_text as abstract-only.
    if row.get("has_pdf"):
        tier = "adequate"
    elif tier in ("retrieval_failed", "unsourced", "metadata_only"):
        tier = "abstract_only" if (row.get("abstract") or "").strip() else tier
    key = (row.get("zotero_key") or "").strip().upper()
    doi = (row.get("doi") or finding.get("doi_or_id") or "").strip()
    return {
        "ref": key or doi,
        "zotero_key": key,
        "title": (row.get("title") or "Untitled").strip(),
        "authors": (row.get("authors") or "").strip(),
        "year": str(row.get("year") or ""),
        "doi": doi,
        "has_pdf": bool(row.get("has_pdf")),
        "collection_paths": list(row.get("collection_paths") or []),
        "in_catalog": True,
        "sourcing_tier": tier,
        "sourcing_label": _TIER_PREVIEW_LABELS.get(tier, tier.replace("_", " ")),
        "catalog_has_pdf": bool(row.get("has_pdf")),
        "live_has_pdf": None,
        "catalog_stale": False,
    }


def _live_has_pdf_for_key(client, zotero_key: str) -> Optional[bool]:
    """Check Zotero Cloud for PDF attachments on an item (lightweight)."""
    from src.zotero_client import _pdf_attachment_keys_for_item

    key = (zotero_key or "").strip()
    if not key:
        return None
    try:
        return bool(_pdf_attachment_keys_for_item(client, key))
    except Exception as exc:
        logger.debug("Live PDF check failed for %s: %s", key, exc)
        return None


def _annotate_catalog_staleness(previews: List[dict], owner: str) -> None:
    """Compare catalog has_pdf flags to live Zotero when credentials exist."""
    from src.zotero_client import ZoteroClient, resolve_zotero_credentials

    creds = resolve_zotero_credentials(owner)
    if not creds:
        return
    client = ZoteroClient(creds["api_key"], creds["user_id"])
    for preview in previews:
        if not preview.get("in_catalog"):
            continue
        key = (preview.get("zotero_key") or "").strip()
        if not key:
            continue
        live = _live_has_pdf_for_key(client, key)
        if live is None:
            continue
        catalog_pdf = bool(preview.get("catalog_has_pdf", preview.get("has_pdf")))
        preview["live_has_pdf"] = live
        preview["catalog_stale"] = live != catalog_pdf
        if live and not catalog_pdf:
            preview["has_pdf"] = True
            preview["sourcing_tier"] = "adequate"
            preview["sourcing_label"] = _TIER_PREVIEW_LABELS["adequate"]
        elif not live and catalog_pdf:
            preview["has_pdf"] = False
            if (preview.get("sourcing_tier") or "") == "adequate":
                preview["sourcing_tier"] = "retrieval_failed"
                preview["sourcing_label"] = _TIER_PREVIEW_LABELS["retrieval_failed"]


def preview_seed_refs(owner: str, refs: List[str]) -> List[dict]:
    """Lightweight catalog-based preview for seed chips (no PDF extraction)."""
    from src.zotero_catalog import load_catalog
    from src.zotero_client import resolve_zotero_credentials

    owner = (owner or "").strip()
    refs = [r.strip() for r in (refs or []) if (r or "").strip()]
    if not owner or not refs:
        return []

    creds = resolve_zotero_credentials(owner)
    user_id = (creds or {}).get("user_id") or ""
    catalog = load_catalog(owner)
    previews: List[dict] = []
    seen_keys: set = set()

    for ref in refs:
        row = _catalog_row_for_ref(owner, ref, catalog)
        if row:
            key = (row.get("zotero_key") or "").upper()
            if key in seen_keys:
                continue
            seen_keys.add(key)
            previews.append(_preview_from_catalog_row(row, user_id=user_id))
            continue

        norm = normalize_seed_ref(ref)
        doi = norm if _DOI_RE.match(norm) else ""
        key = norm.upper() if _ZOTERO_KEY_RE.match(norm) else ""
        dedupe = key or doi.lower()
        if dedupe in seen_keys:
            continue
        seen_keys.add(dedupe)
        previews.append({
            "ref": ref,
            "zotero_key": key,
            "title": f"DOI {doi}" if doi else ref,
            "authors": "",
            "year": "",
            "doi": doi,
            "has_pdf": False,
            "collection_paths": [],
            "in_catalog": False,
            "sourcing_tier": "unknown",
            "sourcing_label": _TIER_PREVIEW_LABELS["unknown"],
            "catalog_has_pdf": False,
            "live_has_pdf": None,
            "catalog_stale": False,
        })
    _annotate_catalog_staleness(previews, owner)
    return previews


def seed_details_for_refs(owner: str, refs: List[str]) -> List[dict]:
    """Snapshot seed metadata for completed research JSON."""
    rows, _missing = resolve_seed_catalog_rows(owner, refs)
    out: List[dict] = []
    seen: set = set()
    for row in rows:
        key = (row.get("zotero_key") or "").upper()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append({
            "zotero_key": key,
            "title": (row.get("title") or "").strip(),
            "authors": (row.get("authors") or "").strip(),
            "year": str(row.get("year") or ""),
            "doi": (row.get("doi") or "").strip(),
            "has_pdf": bool(row.get("has_pdf")),
            "collection_paths": list(row.get("collection_paths") or []),
        })
    for ref in refs or []:
        norm = normalize_seed_ref(ref)
        if _ZOTERO_KEY_RE.match(norm) and norm.upper() not in seen:
            seen.add(norm.upper())
            out.append({"zotero_key": norm.upper(), "title": norm.upper(), "ref": ref})
        elif _DOI_RE.match(norm) and norm.lower() not in {d.get("doi", "").lower() for d in out}:
            out.append({"doi": norm, "title": f"DOI {norm}", "ref": ref})
    return out


def _catalog_row_for_ref(owner: str, ref: str, catalog: List[dict]) -> Optional[dict]:
    norm = normalize_seed_ref(ref)
    if not norm:
        return None
    if _ZOTERO_KEY_RE.match(norm):
        for row in catalog:
            if (row.get("zotero_key") or "").upper() == norm:
                return row
        return None
    for row in catalog:
        if (row.get("zotero_key") or "").upper() == norm.upper():
            return row
    doi_norm = norm.lower()
    for row in catalog:
        doi = (row.get("doi") or "").strip().lower()
        if doi and doi == doi_norm:
            return row
        if doi and doi_norm.endswith(doi):
            return row
    # Fuzzy title match as last resort (short refs only)
    if len(norm) >= 4 and not _DOI_RE.match(norm):
        q = norm.lower()
        for row in catalog:
            title = (row.get("title") or "").lower()
            if q in title or title in q:
                return row
    return None


def resolve_seed_catalog_rows(owner: str, refs: List[str]) -> Tuple[List[dict], List[str]]:
    """Map seed refs to catalog rows; return (rows, missing refs)."""
    from src.zotero_catalog import load_catalog

    catalog = load_catalog(owner)
    rows: List[dict] = []
    missing: List[str] = []
    seen_keys: set = set()

    for ref in refs or []:
        raw = (ref or "").strip()
        if not raw:
            continue
        row = _catalog_row_for_ref(owner, raw, catalog)
        if not row:
            missing.append(raw)
            continue
        key = (row.get("zotero_key") or "").upper()
        if key in seen_keys:
            continue
        seen_keys.add(key)
        rows.append(row)
    return rows, missing


def seed_findings_from_refs(
    owner: str,
    refs: List[str],
    *,
    extract_pdfs: bool = True,
    pdf_max_chars: int = 15000,
) -> SeedPaperOutcome:
    """Build marked seed findings from user-provided paper refs."""
    from src.research_zotero import findings_from_catalog_rows

    owner = (owner or "").strip()
    if not owner or not refs:
        return SeedPaperOutcome([], [], list(refs or []), "No seed papers provided")

    rows, missing = resolve_seed_catalog_rows(owner, refs)
    if not rows:
        return SeedPaperOutcome([], [], missing, "No seed papers matched in catalog")

    findings = findings_from_catalog_rows(
        owner,
        rows,
        extract_pdfs=extract_pdfs,
        pdf_max_chars=pdf_max_chars,
    )
    for f in findings:
        f["is_seed"] = True
        f["seed_source"] = "user"
        f["graph_source"] = "seed_paper"

    keys = [(f.get("paper_key") or f.get("zotero_key") or "").upper() for f in findings]
    note = f"Loaded {len(findings)} seed paper(s) from catalog"
    if missing:
        note += f"; {len(missing)} ref(s) not found"
    logger.info("Research seeds: %s", note)
    outcome = SeedPaperOutcome(findings, [k for k in keys if k], missing, note)
    return outcome


def refresh_seed_from_zotero_api(owner: str, finding: dict) -> dict:
    """Refresh DOI/abstract from live Zotero when the local catalog row is stale."""
    from src.research_paper_fetch import normalize_doi
    from src.zotero_client import ZoteroClient, resolve_zotero_credentials

    owner = (owner or "").strip()
    key = (finding.get("zotero_key") or finding.get("paper_key") or "").strip()
    if not owner or not key:
        return finding

    creds = resolve_zotero_credentials(owner)
    if not creds:
        return finding

    client = ZoteroClient(creds["api_key"], creds["user_id"])
    item = client.get_item(key)
    if not item:
        return finding

    data = item.get("data") or {}
    merged = dict(finding)
    abstract = (data.get("abstractNote") or "").strip()
    doi = ""
    for raw in (
        data.get("DOI"),
        data.get("url"),
        merged.get("url"),
        merged.get("doi_or_id"),
    ):
        doi = normalize_doi(raw or "")
        if doi:
            break
    key_like = (merged.get("zotero_key") or merged.get("paper_key") or "").strip()
    if doi and key_like and doi.upper() == key_like.upper():
        doi = normalize_doi(data.get("url") or merged.get("url") or "")
    if doi:
        merged["doi_or_id"] = doi
    url = (data.get("url") or merged.get("url") or "").strip()
    if url:
        merged["url"] = url
    if abstract:
        merged["abstract"] = abstract
        parts = []
        if abstract:
            parts.append(abstract)
        pdf_part = ""
        if merged.get("pdf_extracted") and merged.get("evidence"):
            ev = merged.get("evidence") or ""
            if len(ev) > len(abstract) + 50:
                pdf_part = ev[len(abstract):].lstrip()
        if pdf_part:
            parts.append(pdf_part)
        elif merged.get("evidence") and len(merged.get("evidence") or "") > len(abstract):
            parts = [merged["evidence"]]
        else:
            merged["summary"] = abstract[:2000]
        if parts:
            merged["evidence"] = "\n\n".join(parts)[:15000]
    return merged


def _merge_resolved_content(
    finding: dict,
    content: str,
    *,
    source_url: str,
    source: str,
    max_chars: int,
    fulltext: bool = False,
) -> dict:
    merged = dict(finding)
    body = (content or "").strip()
    if not body:
        return merged
    existing = (merged.get("evidence") or "").strip()
    if len(body) > len(existing):
        merged["evidence"] = body[:max_chars]
    if fulltext:
        merged["pdf_extracted"] = True
        merged["content_source"] = source
    else:
        merged["abstract"] = body[:8000]
        merged["content_source"] = source
    summary = (merged.get("summary") or merged.get("abstract") or "").strip()
    if not summary or len(summary) < 120:
        merged["summary"] = body[:800]
    merged["web_enriched"] = True
    merged["web_enrichment_url"] = source_url
    merged["pdf_fetch_failed"] = False
    return merged


def seed_needs_online_enrichment(finding: dict, *, min_evidence_chars: int = 500) -> bool:
    """True when a seed still needs DOI/PubMed/PDF resolution beyond catalog metadata."""
    if finding.get("pdf_extracted"):
        return False
    evidence = (finding.get("evidence") or "").strip()
    if finding.get("web_enriched") and len(evidence) >= min_evidence_chars:
        return False
    if len(evidence) >= max(min_evidence_chars, 900):
        return False
    if finding.get("pdf_fetch_failed"):
        return True
    if finding.get("has_pdf") and not finding.get("pdf_extracted"):
        return True
    doi = (finding.get("doi_or_id") or "").strip()
    if doi.startswith("10.") and len(evidence) < min_evidence_chars:
        return True
    abstract = (finding.get("abstract") or finding.get("summary") or "").strip()
    if len(abstract) >= 200 and len(evidence) >= min_evidence_chars:
        return False
    title = (finding.get("title") or "").strip()
    if not title or title.lower() == "untitled":
        return True
    return len(evidence) < min_evidence_chars


def _fetch_zotero_pdf_text(owner: str, key: str, max_chars: int) -> Tuple[str, str]:
    from src.zotero_client import fetch_paper_pdf_text

    return fetch_paper_pdf_text(owner, key, max_chars=max_chars)


def enrich_seed_finding_from_web(
    finding: dict,
    *,
    owner: str = "",
    max_chars: int = 15000,
) -> dict:
    """Resolve paper text via Zotero PDF retry, PubMed, Europe PMC, then web."""
    from src.research_paper_fetch import (
        is_usable_paper_content,
        normalize_doi,
        resolve_paper_content_by_doi,
    )

    merged = refresh_seed_from_zotero_api(owner, finding)

    if not merged.get("pdf_extracted"):
        key = (merged.get("zotero_key") or merged.get("paper_key") or "").strip()
        if owner and key:
            pdf_text, pdf_note = _fetch_zotero_pdf_text(owner, key, max_chars)
            if pdf_text:
                merged = _merge_resolved_content(
                    merged,
                    pdf_text,
                    source_url=merged.get("url") or "",
                    source="zotero_pdf",
                    max_chars=max_chars,
                    fulltext=True,
                )
            elif pdf_note:
                merged["pdf_fetch_note"] = pdf_note

    if not seed_needs_online_enrichment(merged, min_evidence_chars=min(500, max_chars // 10)):
        from src.research_sourcing import annotate_finding_sourcing
        annotate_finding_sourcing(merged)
        return merged

    doi = normalize_doi(merged.get("doi_or_id") or merged.get("doi") or "")
    title = (merged.get("title") or "").strip()
    resolved = resolve_paper_content_by_doi(doi, title=title, fetch_fulltext=True) if doi else {}
    if resolved.get("fulltext"):
        merged = _merge_resolved_content(
            merged,
            resolved["fulltext"],
            source_url=resolved.get("source_url") or f"https://doi.org/{doi}",
            source=resolved.get("source") or "doi_fulltext",
            max_chars=max_chars,
            fulltext=True,
        )
    elif resolved.get("abstract"):
        merged = _merge_resolved_content(
            merged,
            resolved["abstract"],
            source_url=resolved.get("source_url") or f"https://doi.org/{doi}",
            source=resolved.get("source") or "pubmed_abstract",
            max_chars=max_chars,
            fulltext=False,
        )

    if not seed_needs_online_enrichment(merged, min_evidence_chars=min(500, max_chars // 10)):
        from src.research_sourcing import annotate_finding_sourcing
        annotate_finding_sourcing(merged)
        return merged

    from src.research_web_search import (
        is_paper_landing_url,
        is_scholar_author_profile_url,
        paper_lookup_queries_for_finding,
        research_web_search,
    )
    from src.search import fetch_webpage_content

    best_content = (merged.get("evidence") or "").strip()
    best_url = (merged.get("web_enrichment_url") or merged.get("url") or "").strip()

    if not merged.get("pdf_extracted") and doi.startswith("10."):
        doi_url = f"https://doi.org/{doi}"
        try:
            page = fetch_webpage_content(doi_url, include_og_image=False)
        except Exception as exc:
            logger.info("Seed DOI fetch failed for %s: %s", doi_url, exc)
            page = {}
        if page.get("success") and is_usable_paper_content(page.get("content") or "", title=title):
            merged = _merge_resolved_content(
                merged,
                page["content"],
                source_url=doi_url,
                source="doi_landing",
                max_chars=max_chars,
                fulltext=len(page["content"]) >= 900,
            )
            best_content = (merged.get("evidence") or "").strip()

    if len(best_content) < max(400, max_chars // 20):
        for query in paper_lookup_queries_for_finding(merged)[:4]:
            outcome = research_web_search(query, search_kind="discovery", count=6)
            for row in outcome.results or []:
                url = (row.get("url") or "").strip()
                if not url or is_scholar_author_profile_url(url) or not is_paper_landing_url(url):
                    continue
                try:
                    page = fetch_webpage_content(url, include_og_image=False)
                except Exception as exc:
                    logger.info("Seed lookup fetch failed for %s: %s", url[:80], exc)
                    continue
                if page.get("success") and is_usable_paper_content(page.get("content") or "", title=title):
                    merged = _merge_resolved_content(
                        merged,
                        page["content"],
                        source_url=url,
                        source="web_lookup",
                        max_chars=max_chars,
                        fulltext=len(page["content"]) >= 900,
                    )
                    break
            if len((merged.get("evidence") or "")) >= max(400, max_chars // 20):
                break

    if seed_needs_online_enrichment(merged, min_evidence_chars=min(500, max_chars // 10)):
        merged["sourcing_tier"] = "retrieval_failed"
        merged["sourcing_note"] = (
            "Full text could not be retrieved from Zotero, PubMed, Europe PMC, or online fallback. "
            "Do NOT infer paper content from the title or author names."
        )
        merged["allow_substantive_claims"] = False
        note = merged.get("pdf_fetch_note") or ""
        if note:
            merged["sourcing_note"] += f" Zotero PDF: {note[:200]}"
    else:
        logger.info(
            "Seed enriched: %s (%d chars via %s)",
            title[:60],
            len(merged.get("evidence") or ""),
            merged.get("content_source") or merged.get("web_enrichment_url") or "zotero",
        )

    from src.research_sourcing import annotate_finding_sourcing
    annotate_finding_sourcing(merged)
    return merged


def enrich_seed_findings_from_web(
    findings: List[dict],
    *,
    owner: str = "",
    max_chars: int = 15000,
) -> List[dict]:
    """Online fallback for seed papers Zotero could not fully load."""
    out: List[dict] = []
    for finding in findings or []:
        out.append(enrich_seed_finding_from_web(finding, owner=owner, max_chars=max_chars))
    return out
