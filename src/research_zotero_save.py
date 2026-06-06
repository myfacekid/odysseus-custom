"""Save Deep Research evidence sources to Zotero (Phase 5b)."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from src.research_evidence import EvidenceRegistry, EvidenceSource, extract_citation_nums
from src.research_export import _load_registry, _parse_csl_authors, select_export_sources
from src.zotero_client import sources_to_zotero_items


def is_in_library(src: EvidenceSource) -> bool:
    """True when the source already maps to a Zotero or catalog paper."""
    sid = (src.source_id or "").strip()
    return sid.startswith("src:zotero:") or sid.startswith("src:paper:")


def is_saveable(src: EvidenceSource) -> bool:
    """Web (or unknown) sources with enough metadata to create a Zotero item."""
    if is_in_library(src):
        return False
    return bool((src.title or "").strip() or (src.url or "").strip() or (src.doi_or_id or "").strip())


def _zotero_item_type(src: EvidenceSource) -> str:
    if src.peer_review_status == "preprint" or "arxiv" in (src.url or "").lower():
        return "preprint"
    if (src.doi_or_id or "").startswith("10."):
        return "journalArticle"
    if (src.url or "").strip() and not (src.authors or "").strip() and not (src.doi_or_id or "").strip():
        return "webpage"
    return "journalArticle"


def _parse_zotero_creators(authors: str) -> List[dict]:
    out: List[dict] = []
    for author in _parse_csl_authors(authors):
        if author.get("literal"):
            out.append({"creatorType": "author", "name": author["literal"]})
            continue
        creator: Dict[str, str] = {"creatorType": "author", "lastName": author.get("family") or ""}
        given = (author.get("given") or "").strip()
        if given:
            creator["firstName"] = given
        if creator["lastName"] or creator.get("firstName"):
            out.append(creator)
    return out


def _abstract_note(src: EvidenceSource) -> str:
    bits: List[str] = []
    excerpt = (src.content_excerpt or "").strip()
    if excerpt:
        bits.append(excerpt[:2000])
    note = (src.sourcing_note or "").strip()
    if note and note not in excerpt:
        bits.append(note[:500])
    if src.study_type:
        bits.append(src.study_type)
    return "\n\n".join(bits).strip()


def source_to_zotero_item(src: EvidenceSource) -> dict:
    """Build one Zotero write API item payload from a registry source."""
    title = (src.title or src.url or "Untitled source").strip()
    item: Dict[str, Any] = {
        "itemType": _zotero_item_type(src),
        "title": title[:500],
    }
    creators = _parse_zotero_creators(src.authors)
    if creators:
        item["creators"] = creators
    year_match = re.search(r"\d{4}", src.year or "")
    if year_match:
        item["date"] = year_match.group()
    doi = (src.doi_or_id or "").strip()
    if doi.startswith("10."):
        item["DOI"] = doi
    elif doi and not doi.startswith("src:"):
        item["extra"] = doi[:500]
    url = (src.url or "").strip()
    if url:
        item["url"] = url
    abstract = _abstract_note(src)
    if abstract:
        item["abstractNote"] = abstract[:8000]
    if src.peer_review_status == "preprint":
        item["libraryCatalog"] = "arXiv"
    return item


def select_save_sources(
    registry: EvidenceRegistry,
    report_md: str,
    *,
    scope: str = "cited",
    citation_nums: Optional[Sequence[int]] = None,
) -> List[EvidenceSource]:
    """Registry sources eligible for Zotero batch save."""
    if citation_nums:
        nums = {int(n) for n in citation_nums if int(n) > 0}
        pool = [src for src in registry.sources() if src.citation_num in nums]
    else:
        pool = select_export_sources(registry, report_md, scope=scope)
    return [src for src in pool if is_saveable(src)]


def preview_save_sources(data: dict, *, scope: str = "cited") -> dict:
    """Summarize which registry sources can be saved vs skipped."""
    registry = _load_registry(data)
    report = (data.get("raw_report") or data.get("result") or "").strip()
    cited = extract_citation_nums(report)
    saveable: List[dict] = []
    in_library: List[dict] = []
    for src in registry.sources():
        row = {
            "citation_num": src.citation_num,
            "title": src.title or src.url or "Untitled",
            "source_id": src.source_id,
            "in_library": is_in_library(src),
            "cited": src.citation_num in cited,
        }
        if is_in_library(src):
            in_library.append(row)
        elif is_saveable(src):
            saveable.append(row)
    default_nums = [
        src.citation_num
        for src in select_save_sources(registry, report, scope=scope)
    ]
    return {
        "saveable": saveable,
        "in_library": in_library,
        "default_citation_nums": default_nums,
        "cited": sorted(cited),
    }


def _create_items_batched(client, payloads: List[dict]) -> Tuple[int, Optional[str]]:
    created = 0
    for offset in range(0, len(payloads), 50):
        batch = payloads[offset : offset + 50]
        count, err = client.create_items(batch)
        if err:
            return created, err
        created += count
    return created, None


def save_research_sources_to_zotero(
    data: dict,
    client,
    *,
    scope: str = "cited",
    citation_nums: Optional[Sequence[int]] = None,
) -> dict:
    """Create Zotero items for selected research sources."""
    registry = _load_registry(data)
    report = (data.get("raw_report") or data.get("result") or "").strip()

    if registry.sources():
        selected = select_save_sources(
            registry,
            report,
            scope=scope,
            citation_nums=citation_nums,
        )
        skipped_in_library = len([
            src for src in registry.sources()
            if is_in_library(src)
            and (
                not citation_nums
                or src.citation_num in {int(n) for n in citation_nums}
            )
        ])
        payloads = [source_to_zotero_item(src) for src in selected]
    else:
        legacy = data.get("sources") or []
        payloads = sources_to_zotero_items(legacy)
        selected = []
        skipped_in_library = 0

    if not payloads:
        return {
            "ok": True,
            "created": 0,
            "attempted": 0,
            "skipped_in_library": skipped_in_library,
            "saved_citation_nums": [],
        }

    created, err = _create_items_batched(client, payloads)
    if err:
        return {
            "ok": False,
            "created": created,
            "attempted": len(payloads),
            "skipped_in_library": skipped_in_library,
            "saved_citation_nums": [src.citation_num for src in selected[:created]],
            "error": err,
        }

    return {
        "ok": True,
        "created": created,
        "attempted": len(payloads),
        "skipped_in_library": skipped_in_library,
        "saved_citation_nums": [src.citation_num for src in selected],
    }
