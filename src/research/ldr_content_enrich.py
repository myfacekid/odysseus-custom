"""LDR Phase L6 — DOI metadata enrichment and selective full-text loading."""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Callable, Dict, List, Optional, Set

from src.research.ldr_doi import finding_text_richness
from src.research_evidence import EvidenceRegistry, doi_from_finding
from src.research_sourcing import (
    SOURCING_TIER_ABSTRACT_ONLY,
    SOURCING_TIER_ADEQUATE,
    SOURCING_TIER_UNSOURCED,
    annotate_finding_sourcing,
    assess_finding_sourcing,
    format_finding_content_for_prompt,
    is_thin_sourcing,
)
from src.research_utils import strip_thinking

logger = logging.getLogger(__name__)

MAX_DOI_ABSTRACT_LOOKUPS = 40
MAX_URL_ENRICH_LOOKUPS = 20
MAX_DEEP_READ_SOURCES = 6
_MIN_RICHNESS_FOR_SKIP_LOOKUP = 900


def _finding_for_source(registry: EvidenceRegistry, findings: List[dict], citation_num: int) -> Optional[dict]:
    for f in findings or []:
        if f.get("citation_num") == citation_num:
            return f
    for f in findings or []:
        if f.get("source_id"):
            src = registry.get(f["source_id"])
            if src and src.citation_num == citation_num:
                return f
    for src in registry.sources():
        if src.citation_num == citation_num:
            return {
                "citation_num": src.citation_num,
                "source_id": src.source_id,
                "title": src.title,
                "url": src.url,
                "doi_or_id": src.doi_or_id,
                "content": src.content_excerpt,
            }
    return None


def _apply_resolved_text(
    finding: dict,
    text: str,
    *,
    source: str,
    source_url: str = "",
    max_chars: int,
    as_fulltext: bool,
) -> dict:
    text = (text or "").strip()
    if not text:
        return finding
    if len(text) > max_chars:
        text = text[: max_chars - 20].rstrip() + "\n… [truncated]"
    if as_fulltext:
        finding["evidence"] = text
        finding["deep_read_loaded"] = True
        finding["content_source"] = source
        if source_url:
            finding["web_enrichment_url"] = source_url
            finding["web_enriched"] = True
        if len(text) >= 900:
            finding["pdf_extracted"] = source.endswith("pdf") or source.endswith("fulltext")
    else:
        finding["abstract"] = text
        if len(text) > len((finding.get("content") or "").strip()):
            finding["content"] = text[:480]
    annotate_finding_sourcing(finding)
    return finding


def enrich_metadata_from_doi(
    finding: dict,
    *,
    max_chars: int = 8000,
    fetch_fulltext: bool = False,
) -> bool:
    """Resolve abstract/full text for a DOI via PMC, OpenAlex, and Semantic Scholar."""
    from src.research.ldr_fulltext_escalate import escalate_fulltext_by_doi

    doi = doi_from_finding(finding)
    if not doi.startswith("10."):
        return False
    if finding_text_richness(finding) >= _MIN_RICHNESS_FOR_SKIP_LOOKUP and finding.get("abstract"):
        return False

    resolved = escalate_fulltext_by_doi(
        doi,
        title=(finding.get("title") or "").strip(),
        max_chars=max_chars,
        fetch_fulltext=fetch_fulltext,
    )
    if resolved.get("fulltext") and fetch_fulltext:
        _apply_resolved_text(
            finding,
            resolved["fulltext"],
            source=resolved.get("source") or "doi_fulltext",
            source_url=resolved.get("source_url") or f"https://doi.org/{doi}",
            max_chars=max_chars,
            as_fulltext=True,
        )
        return True
    if resolved.get("abstract"):
        _apply_resolved_text(
            finding,
            resolved["abstract"],
            source=resolved.get("source") or "pubmed_abstract",
            source_url=resolved.get("source_url") or f"https://doi.org/{doi}",
            max_chars=max_chars,
            as_fulltext=False,
        )
        return True
    return False


def _sync_registry_from_finding(registry: EvidenceRegistry, finding: dict) -> None:
    sid = (finding.get("source_id") or "").strip()
    if not sid:
        return
    src = registry.get(sid)
    if not src:
        return
    from src.research_evidence import _excerpt_from_finding, _merge_quantitative_fields

    _merge_quantitative_fields(src, finding)
    tier = (finding.get("sourcing_tier") or "").strip()
    if tier:
        src.sourcing_tier = tier
        src.sourcing_note = (finding.get("sourcing_note") or "").strip()
    excerpt = _excerpt_from_finding(finding)
    if excerpt and len(excerpt) > len(src.content_excerpt or ""):
        src.content_excerpt = excerpt


async def enrich_ldr_metadata(
    registry: EvidenceRegistry,
    findings: List[dict],
    *,
    max_lookups: int = MAX_DOI_ABSTRACT_LOOKUPS,
    max_content_chars: int = 8000,
    progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> int:
    """Lightweight DOI abstract pass — no full PDF unless already in finding."""
    enriched = 0
    candidates = []
    for f in findings:
        tier, _, _ = assess_finding_sourcing(f)
        if tier in (SOURCING_TIER_ADEQUATE,):
            continue
        if not doi_from_finding(f).startswith("10."):
            continue
        candidates.append(f)
    candidates.sort(key=finding_text_richness)

    for finding in candidates[:max_lookups]:
        if progress_callback:
            title = (finding.get("title") or "Untitled")[:72]
            progress_callback({"phase": "reading", "message": f"DOI abstract: {title}", "source": "doi"})
        ok = await asyncio.to_thread(
            enrich_metadata_from_doi,
            finding,
            max_chars=max_content_chars,
            fetch_fulltext=False,
        )
        if ok:
            enriched += 1
            _sync_registry_from_finding(registry, finding)
    return enriched


async def enrich_ldr_url_metadata(
    registry: EvidenceRegistry,
    findings: List[dict],
    *,
    max_lookups: int = MAX_URL_ENRICH_LOOKUPS,
    max_content_chars: int = 8000,
    progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> int:
    """Lightweight HTML/PDF pass for thin sources with scholarly URLs but no DOI."""
    from src.research.ldr_url_enrich import enrich_finding_from_url
    from src.research_evidence import doi_from_finding

    enriched = 0
    candidates = []
    for f in findings:
        tier, _, _ = assess_finding_sourcing(f)
        if tier == SOURCING_TIER_ADEQUATE:
            continue
        if doi_from_finding(f).startswith("10."):
            continue
        if not (f.get("url") or "").strip().startswith("http"):
            continue
        candidates.append(f)
    candidates.sort(key=finding_text_richness)

    for finding in candidates[:max_lookups]:
        if progress_callback:
            title = (finding.get("title") or "Untitled")[:72]
            progress_callback({"phase": "reading", "message": f"URL extract: {title}", "source": "url"})
        ok = await asyncio.to_thread(
            enrich_finding_from_url,
            finding,
            max_chars=max_content_chars,
            as_fulltext=False,
        )
        if ok:
            enriched += 1
            _sync_registry_from_finding(registry, finding)
    return enriched


def build_deep_read_picker_prompt(question: str, registry: EvidenceRegistry, findings: List[dict]) -> str:
    """Ask the model which sources need full-text retrieval."""
    lines = [
        "You are selecting scholarly sources that require full-text retrieval for a literature synthesis.",
        f"Research question: {question}",
        "",
        "For each source below you see citation number, title, DOI, and what text is already available.",
        f"Return ONLY a JSON array of citation numbers (integers) that need full PDF/article text "
        f"to answer the question well. Pick at most {MAX_DEEP_READ_SOURCES}.",
        "Prefer sources central to the question with only metadata or short snippets.",
        "Skip sources that already have adequate text or are peripheral.",
        "",
        "Sources:",
    ]
    for src in registry.sources():
        f = _finding_for_source(registry, findings, src.citation_num) or {}
        tier = (f.get("sourcing_tier") or src.sourcing_tier or "").strip()
        doi = doi_from_finding(f) or src.doi_or_id
        preview = (f.get("abstract") or f.get("content") or src.content_excerpt or "")[:220].replace("\n", " ")
        lines.append(
            f"[{src.citation_num}] {src.title} | DOI: {doi or 'n/a'} | tier: {tier or 'unknown'} | preview: {preview or '(none)'}"
        )
    lines.append("")
    lines.append('Respond with JSON only, e.g. [1, 4, 7] or [] if none need full text.')
    return "\n".join(lines)


def parse_citation_picker_response(raw: str, *, max_num: int) -> List[int]:
    """Parse LLM JSON array of citation numbers."""
    text = strip_thinking(raw or "") or ""
    match = re.search(r"\[[\s\d,]*\]", text)
    if not match:
        return []
    try:
        nums = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    out: List[int] = []
    for item in nums:
        try:
            n = int(item)
        except (TypeError, ValueError):
            continue
        if 1 <= n <= max_num and n not in out:
            out.append(n)
    return out[:MAX_DEEP_READ_SOURCES]


def heuristic_deep_read_candidates(
    registry: EvidenceRegistry,
    findings: List[dict],
    *,
    limit: int = MAX_DEEP_READ_SOURCES,
) -> List[int]:
    """Fallback picker: thin sources (DOI or scholarly URL) with highest richness gap."""
    from src.research.ldr_url_enrich import is_enrichable_scholarly_url

    scored: List[tuple] = []
    for src in registry.sources():
        f = _finding_for_source(registry, findings, src.citation_num) or {}
        tier = (f.get("sourcing_tier") or src.sourcing_tier or "").strip()
        if tier == SOURCING_TIER_ADEQUATE:
            continue
        if f.get("deep_read_loaded"):
            continue
        has_doi = doi_from_finding(f).startswith("10.")
        has_url = is_enrichable_scholarly_url(f.get("url") or src.url or "")
        if not has_doi and not has_url:
            continue
        priority = 0
        if is_thin_sourcing(tier):
            priority += 3
        elif tier == SOURCING_TIER_ABSTRACT_ONLY:
            priority += 1
        if src.is_seed:
            priority += 2
        if has_doi:
            priority += 1
        scored.append((priority, -finding_text_richness(f), src.citation_num))
    scored.sort(reverse=True)
    return [n for _, _, n in scored[:limit]]


async def pick_sources_for_deep_read(
    question: str,
    registry: EvidenceRegistry,
    findings: List[dict],
    *,
    llm_endpoint: str,
    llm_model: str,
    llm_headers: Optional[dict] = None,
) -> List[int]:
    """LLM chooses citation numbers needing full text; heuristic fallback on failure."""
    if not registry.sources():
        return []
    from src.llm_core import llm_call_async

    prompt = build_deep_read_picker_prompt(question, registry, findings)
    try:
        raw = await llm_call_async(
            url=llm_endpoint,
            model=llm_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=256,
            headers=llm_headers,
            timeout=60,
        )
        picked = parse_citation_picker_response(raw or "", max_num=len(registry))
        if picked:
            return picked
    except Exception as exc:
        logger.warning("Deep-read picker LLM failed: %s", exc)
    return heuristic_deep_read_candidates(registry, findings)


async def fetch_deep_read_for_finding(
    finding: dict,
    *,
    owner: str = "",
    max_content_chars: int = 15000,
) -> bool:
    """Fetch full text for one finding (DOI → PMC / PDF; Zotero PDF when keyed)."""
    if finding.get("deep_read_loaded"):
        return False

    key = (finding.get("zotero_key") or finding.get("paper_key") or "").strip()
    if owner and key:
        from src.zotero_client import fetch_paper_pdf_text

        pdf_text, note = await asyncio.to_thread(
            fetch_paper_pdf_text,
            owner,
            key,
            max_chars=max_content_chars,
        )
        if pdf_text:
            _apply_resolved_text(
                finding,
                pdf_text,
                source="zotero_pdf",
                source_url=finding.get("url") or "",
                max_chars=max_content_chars,
                as_fulltext=True,
            )
            return True
        if note:
            finding["pdf_fetch_note"] = note

    ok = await asyncio.to_thread(
        enrich_metadata_from_doi,
        finding,
        max_chars=max_content_chars,
        fetch_fulltext=True,
    )
    if ok and (finding.get("sourcing_tier") == SOURCING_TIER_ADEQUATE or finding.get("deep_read_loaded")):
        return True

    doi = doi_from_finding(finding)
    if doi.startswith("10."):
        from src.research_paper_fetch import fetch_doi_article_html, fetch_doi_pdf_text

        title = (finding.get("title") or "").strip()
        for fetcher, source_key in (
            (fetch_doi_pdf_text, "doi_pdf"),
            (fetch_doi_article_html, "doi_article_html"),
        ):
            try:
                hit = await asyncio.to_thread(fetcher, doi, title=title, max_chars=max_content_chars)
            except Exception:
                hit = {}
            content = (hit.get("fulltext") or "").strip()
            if content:
                _apply_resolved_text(
                    finding,
                    content,
                    source=hit.get("source") or source_key,
                    source_url=hit.get("source_url") or f"https://doi.org/{doi}",
                    max_chars=max_content_chars,
                    as_fulltext=len(content) >= 900,
                )
                return bool(finding.get("deep_read_loaded") or finding.get("evidence"))

    url = (finding.get("url") or "").strip()
    if url.startswith("http"):
        from src.research.ldr_url_enrich import enrich_finding_from_url

        try:
            ok = await asyncio.to_thread(
                enrich_finding_from_url,
                finding,
                max_chars=max_content_chars,
                as_fulltext=True,
            )
        except Exception:
            ok = False
        if ok:
            return bool(finding.get("deep_read_loaded") or finding.get("evidence"))
    return False


def build_deep_read_context_block(
    registry: EvidenceRegistry,
    findings: List[dict],
    citation_nums: Set[int],
) -> str:
    """Format full-text excerpts only for sources selected for deep read."""
    if not citation_nums:
        return ""
    parts = [
        "**Full-text excerpts (selected sources only — cite using registry numbers):**",
    ]
    for num in sorted(citation_nums):
        f = _finding_for_source(registry, findings, num)
        if not f:
            continue
        if not f.get("deep_read_loaded") and not f.get("evidence"):
            continue
        parts.append(f"\n### [{num}] {f.get('title') or 'Untitled'}\n")
        parts.append(format_finding_content_for_prompt(f))
    return "\n".join(parts).strip()


async def run_ldr_content_enrichment(
    *,
    question: str,
    registry: EvidenceRegistry,
    findings: List[dict],
    owner: str = "",
    llm_endpoint: str,
    llm_model: str,
    llm_headers: Optional[dict] = None,
    max_content_chars: int = 15000,
    progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> str:
    """DOI abstracts for thin sources, then model-selected full-text fetch."""
    if progress_callback:
        progress_callback({"phase": "reading", "message": "Resolving DOI abstracts…"})

    await enrich_ldr_metadata(
        registry,
        findings,
        max_content_chars=max_content_chars,
        progress_callback=progress_callback,
    )

    if progress_callback:
        progress_callback({"phase": "reading", "message": "Extracting scholarly page text (non-DOI URLs)…"})

    await enrich_ldr_url_metadata(
        registry,
        findings,
        max_content_chars=max_content_chars,
        progress_callback=progress_callback,
    )

    if progress_callback:
        progress_callback({"phase": "reading", "message": "Selecting sources for full-text read…"})

    picked = await pick_sources_for_deep_read(
        question,
        registry,
        findings,
        llm_endpoint=llm_endpoint,
        llm_model=llm_model,
        llm_headers=llm_headers,
    )

    loaded: Set[int] = set()
    for num in picked:
        finding = _finding_for_source(registry, findings, num)
        if not finding:
            continue
        if progress_callback:
            title = (finding.get("title") or "Untitled")[:72]
            progress_callback(
                {"phase": "reading", "message": f"Full text: {title}", "source": "deep_read"}
            )
        ok = await fetch_deep_read_for_finding(
            finding,
            owner=owner,
            max_content_chars=max_content_chars,
        )
        if ok:
            loaded.add(num)
            _sync_registry_from_finding(registry, finding)

    if progress_callback and loaded:
        progress_callback(
            {
                "phase": "reading",
                "message": f"Loaded full text for {len(loaded)} source(s)",
                "source": "deep_read",
            }
        )

    from src.research.ldr_fulltext_escalate import format_sourcing_summary

    summary = format_sourcing_summary(registry, findings)
    logger.info("LDR content enrichment complete — %s", summary)
    if progress_callback:
        progress_callback({"phase": "reading", "message": summary, "source": "sourcing_stats"})

    return build_deep_read_context_block(registry, findings, loaded)
