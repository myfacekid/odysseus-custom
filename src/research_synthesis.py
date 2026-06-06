"""Thematic clustering and evidence tables for Deep Research final reports (Phase 3c)."""
from __future__ import annotations

import re
from typing import Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from src.research_evidence import EvidenceRegistry, EvidenceSource

THEMATIC_MIN_SOURCES = 5
EVIDENCE_TABLE_MIN_SOURCES = 3
_MAX_SUMMARY_CHARS = 400
_MISSING = "—"


def _cell(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return _MISSING
    return text.replace("|", "\\|").replace("\n", " ")


def _study_label(src: "EvidenceSource") -> str:
    if src.authors:
        year = f" ({src.year})" if src.year else ""
        return f"{src.authors}{year}"
    title = (src.title or "Untitled").strip()
    return title[:80] + ("…" if len(title) > 80 else "")


def sources_with_table_metadata(registry: "EvidenceRegistry") -> List["EvidenceSource"]:
    """Sources that have enough metadata for an evidence table row."""
    rows: List["EvidenceSource"] = []
    for src in registry.sources():
        if (src.study_type or src.authors or src.title).strip():
            rows.append(src)
    return rows


def should_include_evidence_table(registry: "EvidenceRegistry") -> bool:
    return len(sources_with_table_metadata(registry)) >= EVIDENCE_TABLE_MIN_SOURCES


def should_cluster_thematically(registry: "EvidenceRegistry") -> bool:
    return len(registry) >= THEMATIC_MIN_SOURCES


def build_evidence_table(registry: "EvidenceRegistry") -> str:
    """Markdown evidence table from registry structured fields."""
    sources = sources_with_table_metadata(registry)
    if len(sources) < EVIDENCE_TABLE_MIN_SOURCES:
        return ""

    lines = [
        "**Evidence table (use in Key Findings; cite with [N]):**",
        "",
        "| Study | Design | N | Outcome | Ref |",
        "| --- | --- | --- | --- | --- |",
    ]
    for src in sources:
        outcome = src.outcome or src.effect_size
        lines.append(
            "| "
            + " | ".join(
                [
                    _cell(_study_label(src)),
                    _cell(src.study_type),
                    _cell(src.sample_size),
                    _cell(outcome),
                    f"[{src.citation_num}]",
                ]
            )
            + " |"
        )
    return "\n".join(lines)


def _index_findings_by_citation(findings: List[dict]) -> Dict[int, dict]:
    by_num: Dict[int, dict] = {}
    for finding in findings or []:
        num = finding.get("citation_num")
        if num is None:
            continue
        try:
            key = int(num)
        except (TypeError, ValueError):
            continue
        prev = by_num.get(key)
        if not prev or len(str(finding.get("summary") or "")) > len(
            str(prev.get("summary") or "")
        ):
            by_num[key] = finding
    return by_num


def _summary_for_source(src: "EvidenceSource", findings_by_num: Dict[int, dict]) -> str:
    finding = findings_by_num.get(src.citation_num) or {}
    text = (
        (finding.get("summary") or "")
        or (finding.get("evidence") or "")
        or (src.quality_notes or "")
    ).strip()
    if len(text) > _MAX_SUMMARY_CHARS:
        text = text[: _MAX_SUMMARY_CHARS - 1] + "…"
    return text or "(no summary available)"


def build_source_catalog_block(
    registry: "EvidenceRegistry",
    findings: Optional[List[dict]] = None,
) -> str:
    """Compact source list for the thematic clustering LLM pass."""
    findings_by_num = _index_findings_by_citation(findings or [])
    parts: List[str] = []
    for src in registry.sources():
        summary = _summary_for_source(src, findings_by_num)
        seed_note = " [seed]" if src.is_seed else ""
        parts.append(f"[{src.citation_num}] {src.title or 'Untitled'}{seed_note}\n{summary}")
    return "\n\n".join(parts)


THEMATIC_OUTLINE_PROMPT = """\
You are organizing academic sources into themes for a literature synthesis.

**Research question:** {question}

**Sources (each tagged [N]):**
{source_catalog}

Assign EVERY source [N] to exactly one theme. Output ONLY markdown in this format:

## Thematic outline
### Theme: <short substantive name>
- [N] — one-line rationale linking the source to this theme

Rules:
- Use 3–8 themes
- Every [N] must appear exactly once
- Prefer substantive theme names over generic buckets like "Other"
- Do not write the full report — outline only
"""


def build_thematic_outline_prompt(
    question: str,
    registry: "EvidenceRegistry",
    findings: Optional[List[dict]] = None,
) -> str:
    return THEMATIC_OUTLINE_PROMPT.format(
        question=(question or "").strip(),
        source_catalog=build_source_catalog_block(registry, findings),
    )


_OUTLINE_HEADING_RE = re.compile(r"^##\s+Thematic\s+outline\s*$", re.I | re.M)


def format_thematic_outline(raw: str) -> str:
    """Normalize LLM thematic outline output."""
    text = (raw or "").strip()
    if not text:
        return ""
    match = _OUTLINE_HEADING_RE.search(text)
    if match:
        text = text[match.start() :].strip()
    elif "### Theme:" not in text and "### Theme " not in text:
        text = "## Thematic outline\n" + text
    return (
        "**Thematic outline (organize Key Findings using these themes; cite [N] inline):**\n\n"
        + text
    )


def heuristic_thematic_outline(
    registry: "EvidenceRegistry",
    findings: Optional[List[dict]] = None,
) -> str:
    """Fallback grouping when the LLM thematic pass fails."""
    findings_by_num = _index_findings_by_citation(findings or [])
    buckets: Dict[str, List["EvidenceSource"]] = {}
    for src in registry.sources():
        key = (src.study_type or "").strip()
        if not key:
            finding = findings_by_num.get(src.citation_num) or {}
            summary = (finding.get("summary") or "").lower()
            if "method" in summary or "trial" in summary or "cohort" in summary:
                key = "Methods and study designs"
            elif "review" in summary or "meta" in summary:
                key = "Reviews and syntheses"
            else:
                key = "Primary findings"
        buckets.setdefault(key, []).append(src)

    lines = ["## Thematic outline"]
    for theme, sources in buckets.items():
        lines.append(f"### Theme: {theme}")
        for src in sources:
            lines.append(f"- [{src.citation_num}] — {src.title or 'Untitled'}")
    return format_thematic_outline("\n".join(lines))


def combine_final_context_blocks(
    thematic_outline: str = "",
    evidence_table: str = "",
) -> str:
    """Merge optional pre-final blocks for injection into the report prompt."""
    parts = [block.strip() for block in (thematic_outline, evidence_table) if block and block.strip()]
    return "\n\n".join(parts)
