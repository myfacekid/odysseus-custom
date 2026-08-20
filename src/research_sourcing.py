"""Assess whether findings contain enough text to support substantive claims."""
from __future__ import annotations

import re
from typing import Dict, Iterable, List, Optional, Tuple

# Tiers where substantive claims must be blocked in synthesis.
SOURCING_TIER_UNSOURCED = "unsourced"
SOURCING_TIER_RETRIEVAL_FAILED = "retrieval_failed"
SOURCING_TIER_METADATA_ONLY = "metadata_only"
SOURCING_TIER_ABSTRACT_ONLY = "abstract_only"
SOURCING_TIER_ADEQUATE = "adequate"

# Failed retrieval — must disclose and block inference.
_DISCLOSURE_REQUIRED_TIERS = frozenset({
    SOURCING_TIER_UNSOURCED,
    SOURCING_TIER_RETRIEVAL_FAILED,
    SOURCING_TIER_METADATA_ONLY,
})

# Abstract-only — usable with caveat, not a hard retrieval failure.
_CAVEAT_TIERS = frozenset({SOURCING_TIER_ABSTRACT_ONLY})

_THIN_TIERS = _DISCLOSURE_REQUIRED_TIERS | _CAVEAT_TIERS

_MIN_BODY_CHARS = 80
_MIN_ABSTRACT_CHARS = 220
_MIN_FULL_TEXT_CHARS = 900

_TIER_NOTES = {
    SOURCING_TIER_UNSOURCED: (
        "No abstract or full text retrieved — bibliographic metadata only. "
        "Do NOT infer methods, results, or conclusions from the title."
    ),
    SOURCING_TIER_RETRIEVAL_FAILED: (
        "Full text could not be retrieved from Zotero or online fallback. "
        "Do NOT infer paper content from the title or author names."
    ),
    SOURCING_TIER_METADATA_ONLY: (
        "Only title/catalog metadata available — do NOT infer substantive claims "
        "from the title alone."
    ),
    SOURCING_TIER_ABSTRACT_ONLY: (
        "Abstract or short snippet only — treat specific numeric results as unverified "
        "unless quoted verbatim below."
    ),
    SOURCING_TIER_ADEQUATE: "",
}


def _token_len(text: str) -> int:
    return len(re.findall(r"[a-z0-9]+", (text or "").lower()))


def _content_mostly_title(title: str, body: str) -> bool:
    title = (title or "").strip()
    body = (body or "").strip()
    if not title:
        return False
    if not body:
        return True
    if body.lower() == title.lower():
        return True
    if title.lower() in body.lower() and len(body) < max(len(title) + 120, 220):
        remainder = body.lower().replace(title.lower(), "").strip(" .-|,")
        if _token_len(remainder) < 12:
            return True
    if body.lower().startswith("zotero paper:"):
        return True
    return False


def collapse_prompt_body_text(text: str) -> str:
    """Collapse visual PDF line breaks while keeping paragraph gaps."""
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return ""
    paragraphs = re.split(r"\n\s*\n", text)
    collapsed = []
    for para in paragraphs:
        line = re.sub(r"[ \t]*\n[ \t]*", " ", para)
        line = re.sub(r" {2,}", " ", line).strip()
        if line:
            collapsed.append(line)
    return "\n\n".join(collapsed)


def _is_title_page_summary_stub(summary: str, evidence: str) -> bool:
    """True when summary is a short prefix of PDF/extracted evidence, not an abstract."""
    summary = (summary or "").strip()
    evidence = (evidence or "").strip()
    if not summary or not evidence:
        return False
    if evidence.startswith(summary) and len(evidence) > len(summary) + 80:
        return True
    if summary == evidence[: len(summary)] and len(summary) <= 800 and len(evidence) > 900:
        return True
    return False


def _best_body_text(finding: dict) -> str:
    for key in ("evidence", "abstract", "summary"):
        text = (finding.get(key) or "").strip()
        if text:
            return text
    return ""


def _adequate_prompt_body(finding: dict) -> str:
    """Prefer abstract/full evidence over a title-page summary stub."""
    abstract = (finding.get("abstract") or "").strip()
    evidence = collapse_prompt_body_text((finding.get("evidence") or "").strip())
    summary = collapse_prompt_body_text((finding.get("summary") or "").strip())
    candidates = [t for t in (abstract, evidence) if t]
    body = max(candidates, key=len) if candidates else ""
    if not body:
        return summary or "(no content)"
    if summary and not _is_title_page_summary_stub(summary, evidence or body):
        if len(summary) > len(body):
            body = summary
    return body or "(no content)"


def assess_finding_sourcing(finding: dict) -> Tuple[str, str, bool]:
    """Return (tier, note, allow_substantive_claims)."""
    if not finding:
        return SOURCING_TIER_UNSOURCED, _TIER_NOTES[SOURCING_TIER_UNSOURCED], False

    title = (finding.get("title") or "").strip()
    body = _best_body_text(finding)
    pdf_extracted = bool(finding.get("pdf_extracted"))
    web_enriched = bool(finding.get("web_enriched"))
    pdf_fetch_failed = bool(finding.get("pdf_fetch_failed"))
    has_pdf = bool(finding.get("has_pdf"))

    if pdf_fetch_failed and not web_enriched and len(body) < _MIN_ABSTRACT_CHARS:
        return (
            SOURCING_TIER_RETRIEVAL_FAILED,
            _TIER_NOTES[SOURCING_TIER_RETRIEVAL_FAILED],
            False,
        )

    if _content_mostly_title(title, body):
        return SOURCING_TIER_METADATA_ONLY, _TIER_NOTES[SOURCING_TIER_METADATA_ONLY], False

    if not body or len(body) < _MIN_BODY_CHARS:
        return SOURCING_TIER_UNSOURCED, _TIER_NOTES[SOURCING_TIER_UNSOURCED], False

    if len(body) < _MIN_ABSTRACT_CHARS:
        return SOURCING_TIER_METADATA_ONLY, _TIER_NOTES[SOURCING_TIER_METADATA_ONLY], False

    if len(body) < _MIN_FULL_TEXT_CHARS and not pdf_extracted and not web_enriched:
        abstract = (finding.get("abstract") or "").strip()
        if len(body) >= _MIN_ABSTRACT_CHARS:
            return SOURCING_TIER_ABSTRACT_ONLY, _TIER_NOTES[SOURCING_TIER_ABSTRACT_ONLY], True
        if has_pdf and not pdf_extracted:
            return (
                SOURCING_TIER_RETRIEVAL_FAILED,
                _TIER_NOTES[SOURCING_TIER_RETRIEVAL_FAILED],
                False,
            )
        return SOURCING_TIER_METADATA_ONLY, _TIER_NOTES[SOURCING_TIER_METADATA_ONLY], False

    return SOURCING_TIER_ADEQUATE, "", True


def _finding_sourcing_view(finding: dict) -> Tuple[str, str, bool]:
    """Use stored tier when present; otherwise assess from finding body."""
    preset = (finding.get("sourcing_tier") or "").strip()
    if preset:
        note = (finding.get("sourcing_note") or _TIER_NOTES.get(preset, "")).strip()
        allow = finding.get("allow_substantive_claims")
        if allow is None:
            allow = preset in (SOURCING_TIER_ADEQUATE, SOURCING_TIER_ABSTRACT_ONLY)
        return preset, note, bool(allow)
    return assess_finding_sourcing(finding)


def annotate_finding_sourcing(finding: dict) -> dict:
    """Attach sourcing tier metadata to a finding dict."""
    if not finding:
        return finding
    tier, note, allow = assess_finding_sourcing(finding)
    finding["sourcing_tier"] = tier
    finding["sourcing_note"] = note
    finding["allow_substantive_claims"] = allow
    return finding


def is_thin_sourcing(tier: str) -> bool:
    """True when source text is too thin for substantive claims."""
    return (tier or "") in _DISCLOSURE_REQUIRED_TIERS


def is_caveat_sourcing(tier: str) -> bool:
    return (tier or "") in _CAVEAT_TIERS


def best_finding_body_text(finding: dict) -> str:
    """Return the longest usable text body from a finding dict."""
    return _best_body_text(finding or {})


_TIER_DISPLAY_LABELS = {
    SOURCING_TIER_ADEQUATE: "Full text",
    SOURCING_TIER_ABSTRACT_ONLY: "Abstract only",
    SOURCING_TIER_METADATA_ONLY: "Metadata only",
    SOURCING_TIER_RETRIEVAL_FAILED: "Retrieval failed",
    SOURCING_TIER_UNSOURCED: "Limited text",
}


def tier_display_label(tier: str) -> str:
    """Human-readable sourcing tier for UI badges."""
    key = (tier or "").strip().lower()
    if not key:
        return "Unknown"
    return _TIER_DISPLAY_LABELS.get(key, key.replace("_", " ").title())


def tier_badge_class(tier: str) -> str:
    """CSS class suffix for a sourcing tier badge."""
    key = (tier or "").strip().lower()
    if key == SOURCING_TIER_ADEQUATE:
        return "adequate"
    if key == SOURCING_TIER_ABSTRACT_ONLY:
        return "abstract"
    if key in _DISCLOSURE_REQUIRED_TIERS:
        return "thin"
    return "unknown"


def compute_sourcing_tier_counts(sources: Iterable[dict]) -> Dict[str, int]:
    """Count registry rows by coarse retrieval tier for report headers."""
    counts = {
        "adequate": 0,
        "abstract_only": 0,
        "thin": 0,
        "total": 0,
    }
    for src in sources or []:
        if not isinstance(src, dict):
            continue
        counts["total"] += 1
        tier = (src.get("sourcing_tier") or "").strip().lower()
        if tier == SOURCING_TIER_ADEQUATE:
            counts["adequate"] += 1
        elif tier == SOURCING_TIER_ABSTRACT_ONLY:
            counts["abstract_only"] += 1
        elif is_thin_sourcing(tier):
            counts["thin"] += 1
    return counts


def format_finding_content_for_prompt(finding: dict) -> str:
    """Return prompt-safe content — never imply full paper text when only metadata exists."""
    finding = annotate_finding_sourcing(dict(finding or {}))
    tier = finding.get("sourcing_tier") or SOURCING_TIER_UNSOURCED
    title = (finding.get("title") or "Untitled").strip()
    doi = (finding.get("doi_or_id") or "").strip()
    authors = (finding.get("authors") or "").strip()
    year = (finding.get("year") or "").strip()

    if tier == SOURCING_TIER_ADEQUATE:
        body = _adequate_prompt_body(finding)
        return body[:2500] if body else "(no content)"

    if tier == SOURCING_TIER_ABSTRACT_ONLY:
        body = _best_body_text(finding)
        header = [
            f"Title: {title}",
            "Sourcing status: abstract only (full PDF not retrieved — discuss methods/results cautiously and quote the abstract below).",
        ]
        if doi:
            header.append(f"DOI/ID: {doi}")
        if body and not _content_mostly_title(title, body):
            header.append(f"Abstract/excerpt:\n{body[:4000]}")
        return "\n".join(header)

    meta_bits = [f"Title: {title}"]
    if authors:
        meta_bits.append(f"Authors: {authors}")
    if year:
        meta_bits.append(f"Year: {year}")
    if doi:
        meta_bits.append(f"DOI/ID: {doi}")
    meta_bits.append(f"Sourcing status: {tier.replace('_', ' ')}")
    meta_bits.append(f"Instruction: {finding.get('sourcing_note') or _TIER_NOTES.get(tier, '')}")
    meta_bits.append(
        "No reliable abstract or full text was available for synthesis. "
        "You may cite this source in References but must NOT describe its methods, "
        "results, or conclusions except to state that the full text was unavailable."
    )
    return "\n".join(meta_bits)


def build_sourcing_limitations_block(findings: Iterable[dict]) -> str:
    """Prompt block listing sources that must not be discussed substantively."""
    rows: List[str] = []
    for finding in findings or []:
        tier, note, _ = _finding_sourcing_view(dict(finding))
        if not is_thin_sourcing(tier):
            continue
        num = finding.get("citation_num")
        prefix = f"[{num}] " if num else ""
        title = (finding.get("title") or "Untitled").strip()
        rows.append(f"- {prefix}**{title}** — {note}")
    if not rows:
        caveat_rows: List[str] = []
        for finding in findings or []:
            tier, _, _ = _finding_sourcing_view(dict(finding))
            if is_caveat_sourcing(tier):
                num = finding.get("citation_num")
                prefix = f"[{num}] " if num else ""
                title = (finding.get("title") or "Untitled").strip()
                caveat_rows.append(
                    f"- {prefix}**{title}** — abstract only; full PDF not retrieved"
                )
        if caveat_rows:
            return (
                "**Source retrieval status:** All registered sources had adequate text for "
                "substantive discussion, except where noted below.\n\n"
                "**Abstract-only sources (usable with caution, not retrieval failures):**\n"
                + "\n".join(caveat_rows)
            )
        return (
            "**Source retrieval status:** All registered sources had adequate text for "
            "substantive discussion."
        )
    caveat_rows: List[str] = []
    for finding in findings or []:
        tier, _, _ = _finding_sourcing_view(dict(finding))
        if is_caveat_sourcing(tier):
            num = finding.get("citation_num")
            prefix = f"[{num}] " if num else ""
            title = (finding.get("title") or "Untitled").strip()
            caveat_rows.append(
                f"- {prefix}**{title}** — abstract only; full PDF not retrieved"
            )
    caveat_block = ""
    if caveat_rows:
        caveat_block = (
            "\n\n**Abstract-only sources (usable with caution, not retrieval failures):**\n"
            + "\n".join(caveat_rows)
        )
    return (
        "**Sources NOT adequately retrieved — mandatory disclosure required:**\n"
        "The following sources lack abstract and full text. "
        "Do NOT infer their methods, findings, or conclusions from the title. "
        "You MUST state in **Limitations of This Report** that these papers could not "
        "be sourced properly and that any comparison involving them is incomplete:\n"
        + "\n".join(rows)
        + caveat_block
    )


def build_sourcing_disclosure_section(registry_sources: Iterable[dict]) -> str:
    """Markdown section appended when the model omits sourcing caveats."""
    lines = ["## Source retrieval limitations", ""]
    any_thin = False
    for src in registry_sources or []:
        tier = (src.get("sourcing_tier") if isinstance(src, dict) else getattr(src, "sourcing_tier", "")) or ""
        if not is_thin_sourcing(tier):
            continue
        any_thin = True
        if isinstance(src, dict):
            num = src.get("citation_num")
            title = src.get("title") or "Untitled"
            note = src.get("sourcing_note") or _TIER_NOTES.get(tier, "")
        else:
            num = src.citation_num
            title = src.title or "Untitled"
            note = src.sourcing_note or _TIER_NOTES.get(tier, "")
        cite = f"[{num}] " if num else ""
        lines.append(
            f"- {cite}**{title}** — {note} "
            "This report does not state substantive claims about this paper beyond bibliographic metadata."
        )
    if not any_thin:
        return ""
    lines.append("")
    lines.append(
        "_Where a seed or compared paper appears above, any contrast of methods or findings "
        "for that paper is incomplete until the full text is added to your library or retrieved online._"
    )
    return "\n".join(lines)


def ensure_sourcing_disclosure(report: str, registry_sources: Iterable[dict]) -> str:
    """Append a sourcing disclosure section if thin sources exist and report omits them."""
    from src.research_evidence import split_references_section

    disclosure = build_sourcing_disclosure_section(registry_sources)
    if not disclosure:
        return report
    lower = (report or "").lower()
    if any(
        phrase in lower
        for phrase in (
            "could not be sourced",
            "could not be retrieved",
            "not adequately retrieved",
            "metadata only",
            "full text was unavailable",
            "source retrieval limitations",
            "title alone",
        )
    ):
        return report

    body, refs = split_references_section(report)
    if body.strip():
        return f"{body.rstrip()}\n\n{disclosure}\n\n{refs}".strip() if refs else f"{body.rstrip()}\n\n{disclosure}".strip()
    return disclosure
