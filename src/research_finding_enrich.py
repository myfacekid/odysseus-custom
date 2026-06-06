"""Normalize and enrich Deep Research finding dicts (Phase 3a)."""
from __future__ import annotations

import re
from typing import Optional
from urllib.parse import unquote

_PREPRINT_HOST_FRAGMENTS = (
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

_DOI_RE = re.compile(
    r"(?:doi:\s*|https?://(?:dx\.)?doi\.org/|/doi/)(10\.\d{4,9}/[^\s\]>\"\'\),]+)",
    re.I,
)
_QUANT_FIELDS = ("sample_size", "effect_size", "outcome", "quality_notes")


def _is_preprint_url(url: str) -> bool:
    lower = (url or "").lower()
    return any(h in lower for h in _PREPRINT_HOST_FRAGMENTS)


def extract_doi(text: str) -> str:
    """Pull a DOI from URL or page text."""
    raw = unquote((text or "").strip())
    if not raw:
        return ""
    match = _DOI_RE.search(raw)
    if match:
        return match.group(1).rstrip(".,;)")
    if raw.lower().startswith("10.") and "/" in raw:
        return raw.split()[0].rstrip(".,;)")
    return ""


def infer_peer_review_status(url: str, current: str = "") -> str:
    """Infer peer-review vs preprint from URL when extractor did not set status."""
    status = (current or "").strip().lower()
    if status in ("peer_reviewed", "peer-reviewed", "preprint"):
        return "preprint" if status == "preprint" else "peer-reviewed"
    if _is_preprint_url(url):
        return "preprint"
    if url and any(m in url.lower() for m in ("doi.org", "pubmed", "ncbi.nlm.nih.gov", "jstor")):
        return "peer-reviewed"
    return current or "unknown"


def normalize_quantitative_field(value) -> str:
    """Keep quantitative metadata as a short string or empty."""
    if value is None:
        return ""
    text = str(value).strip()
    if not text or text.lower() in ("unknown", "n/a", "na", "none", "null"):
        return ""
    return text[:500]


def normalize_finding_fields(finding: dict) -> dict:
    """Normalize structured extraction fields on a finding dict."""
    if not finding:
        return finding
    for key in _QUANT_FIELDS:
        if key in finding:
            finding[key] = normalize_quantitative_field(finding.get(key))
    if not finding.get("peer_review_status"):
        finding["peer_review_status"] = infer_peer_review_status(
            finding.get("url") or "",
            finding.get("peer_review_status") or "",
        )
    doi = (finding.get("doi_or_id") or "").strip()
    if not doi or not doi.startswith("10."):
        inferred = extract_doi(finding.get("url") or "") or extract_doi(finding.get("evidence") or "")
        if inferred:
            finding["doi_or_id"] = inferred
    from src.research_sourcing import annotate_finding_sourcing
    annotate_finding_sourcing(finding)
    return finding


def enrich_web_finding(finding: dict, *, url: str, content: str = "") -> dict:
    """Apply URL/content heuristics after web extraction."""
    finding = normalize_finding_fields(finding)
    finding["peer_review_status"] = infer_peer_review_status(
        url,
        finding.get("peer_review_status") or "",
    )
    if not finding.get("doi_or_id"):
        doi = extract_doi(url) or extract_doi(content)
        if doi:
            finding["doi_or_id"] = doi
    return finding
