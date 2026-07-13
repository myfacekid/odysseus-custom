"""DOI-aware deduplication and content richness for LDR ingest."""
from __future__ import annotations

from typing import Dict, List, Tuple

from src.research_evidence import doi_from_finding, normalize_doi
from src.research_finding_enrich import extract_doi


def _coerce_text(value, *, limit: int = 8000) -> str:
    """Normalize LDR field values that may be str or list."""
    if value is None:
        return ""
    if isinstance(value, list):
        parts = [_coerce_text(v, limit=limit) for v in value]
        text = "\n".join(p for p in parts if p)
    else:
        text = str(value)
    text = text.strip()
    if limit and len(text) > limit:
        return text[: limit - 3].rstrip() + "..."
    return text


def _text_len(*values) -> int:
    total = 0
    for value in values:
        text = _coerce_text(value, limit=0)
        total += len(text)
    return total


def raw_link_text_richness(raw: dict) -> int:
    """Score an LDR collector row by how much usable text it carries."""
    if not isinstance(raw, dict):
        return 0
    score = _text_len(
        raw.get("snippet"),
        raw.get("body"),
        raw.get("content"),
        raw.get("abstract"),
        raw.get("title"),
    )
    if raw.get("authors") or raw.get("author"):
        score += 40
    if raw.get("year") or raw.get("published_date"):
        score += 20
    if raw.get("doi") or raw.get("doi_or_id"):
        score += 30
    return score


def finding_text_richness(finding: dict) -> int:
    """Score a normalized finding dict by available text."""
    if not finding:
        return 0
    score = _text_len(
        finding.get("evidence"),
        finding.get("abstract"),
        finding.get("summary"),
        finding.get("content"),
        finding.get("title"),
    )
    if (finding.get("doi_or_id") or "").startswith("10."):
        score += 30
    if finding.get("pdf_extracted"):
        score += 200
    if finding.get("web_enriched"):
        score += 80
    return score


def doi_from_raw_link(raw: dict) -> str:
    """Extract a normalized DOI from an LDR collector row."""
    explicit = normalize_doi(_coerce_text(raw.get("doi") or raw.get("doi_or_id")))
    if explicit.startswith("10."):
        return explicit
    for field in ("link", "url", "snippet", "body", "content", "abstract"):
        inferred = normalize_doi(extract_doi(_coerce_text(raw.get(field))))
        if inferred.startswith("10."):
            return inferred
    return ""


def dedupe_raw_links_by_doi(links: List[dict]) -> Tuple[List[dict], int]:
    """Collapse duplicate DOIs, keeping the row with the richest text."""
    if not links:
        return [], 0
    best_by_doi: Dict[str, dict] = {}
    order: List[str] = []
    passthrough: List[dict] = []
    dropped = 0

    for raw in links:
        if not isinstance(raw, dict):
            continue
        doi = doi_from_raw_link(raw)
        if not doi.startswith("10."):
            passthrough.append(raw)
            continue
        if doi not in best_by_doi:
            best_by_doi[doi] = raw
            order.append(doi)
            continue
        dropped += 1
        if raw_link_text_richness(raw) > raw_link_text_richness(best_by_doi[doi]):
            best_by_doi[doi] = raw

    deduped = passthrough + [best_by_doi[doi] for doi in order]
    return deduped, dropped


def doi_from_finding_or_link(item: dict) -> str:
    """DOI from a finding dict or raw LDR link."""
    if not item:
        return ""
    doi = doi_from_finding(item)
    if doi.startswith("10."):
        return doi
    return doi_from_raw_link(item)
