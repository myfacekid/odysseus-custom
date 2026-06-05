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
    if raw.lower().startswith("https://doi.org/"):
        raw = raw[len("https://doi.org/") :].strip()
    elif raw.lower().startswith("http://doi.org/"):
        raw = raw[len("http://doi.org/") :].strip()
    if _ZOTERO_KEY_RE.match(raw):
        return raw.upper()
    return raw


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
    return SeedPaperOutcome(findings, [k for k in keys if k], missing, note)
