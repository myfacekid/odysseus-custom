"""Search-coverage transparency for Deep Research reports.

Adds a lightweight "Search coverage" section so a scientist can see what was
actually searched, how many records were screened vs. included, and where the
run is likely to be incomplete. This is the pragmatic cousin of a PRISMA flow —
it is explicitly *not* a systematic review and says so.
"""
from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Tuple


def _year_range(sources: Iterable) -> Optional[Tuple[int, int]]:
    years: List[int] = []
    for src in sources or []:
        raw = src.get("year") if isinstance(src, dict) else getattr(src, "year", "")
        try:
            y = int(str(raw)[:4])
        except (TypeError, ValueError):
            continue
        if 1500 < y < 2100:
            years.append(y)
    if not years:
        return None
    return min(years), max(years)


def build_search_coverage_section(
    *,
    databases: Iterable[str],
    queries_count: int,
    screened: int,
    included: int,
    excluded_reasons: Optional[Dict[str, int]] = None,
    sources: Optional[Iterable] = None,
    extra_gaps: Optional[Iterable[str]] = None,
) -> str:
    """Render the '## Search coverage' markdown section."""
    dbs = [d for d in dict.fromkeys(databases or []) if d]
    lines = ["## Search coverage", ""]
    if dbs:
        lines.append(f"- **Databases / engines:** {', '.join(dbs)}")
    if queries_count:
        lines.append(f"- **Queries issued:** {queries_count}")

    screen_bits = []
    if screened:
        screen_bits.append(f"screened {screened}")
    if included:
        screen_bits.append(f"included {included}")
    excluded_total = sum((excluded_reasons or {}).values())
    if excluded_total:
        screen_bits.append(f"excluded {excluded_total}")
    if screen_bits:
        lines.append(f"- **Records:** {' · '.join(screen_bits)}")

    if excluded_reasons:
        top = sorted(excluded_reasons.items(), key=lambda kv: kv[1], reverse=True)
        reasons = ", ".join(f"{name} ({count})" for name, count in top if count)
        if reasons:
            lines.append(f"- **Excluded (reasons):** {reasons}")

    yr = _year_range(sources or [])
    if yr:
        lines.append(
            f"- **Publication years covered:** {yr[0]}"
            + (f"\u2013{yr[1]}" if yr[1] != yr[0] else "")
        )

    gaps = list(extra_gaps or [])
    gap_note = (
        "Coverage is best-effort, not a systematic review: paywalled full text, "
        "non-English publications, and works missing from the queried indexes may "
        "be underrepresented."
    )
    if gaps:
        gap_note += " Additional gaps: " + "; ".join(gaps) + "."
    lines.append("")
    lines.append(f"_{gap_note}_")
    return "\n".join(lines)


def insert_section_before_references(report: str, section: str) -> str:
    """Insert a markdown section just before the ## References block."""
    if not section or not (section or "").strip():
        return report
    from src.research_evidence import split_references_section

    body, refs = split_references_section(report or "")
    if refs:
        return f"{body.rstrip()}\n\n{section.rstrip()}\n\n{refs}".strip()
    return f"{(report or '').rstrip()}\n\n{section.rstrip()}".strip()
