"""Multi-paper comparison tool (Paper Token Retrieval R3).

Side-by-side section extracts reusing R1 sections and R2 summaries.
See docs/paper-token-retrieval-roadmap_v1.md.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from src.edge_taxonomy import edge_kind_label, infer_stance_from_text
from src.paper_retrieval import PAPER_SECTION_DEFAULT_MAX_CHARS
from src.paper_sections import normalize_section_slug, section_display_label

COMPARE_SYNC_MAX_PAPERS = 3
COMPARE_SLICE_MAX_CHARS = 2500
COMPARE_TOTAL_MAX_CHARS = 12000

# Map focus slug → heading prefix in cached DR summary markdown (R2)
_FOCUS_SUMMARY_HEADERS: Dict[str, str] = {
    "methods": "## Method",
    "results": "## Key results",
    "introduction": "## Focus / claim",
    "limitations": "## Assumptions",
    "discussion": "## Key results",
}

# Lightweight keyword buckets for tension hints (not LLM-generated)
_METHOD_CONTRASTS: Tuple[Tuple[str, str], ...] = (
    ("supervised", "unsupervised"),
    ("randomized", "observational"),
    ("in vitro", "in vivo"),
    ("cross-sectional", "longitudinal"),
    ("deep learning", "classical"),
    ("transformer", "cnn"),
    ("language model", "structure-based"),
)


def normalize_paper_keys(raw_keys: List[str]) -> List[str]:
    """Normalize paper:KEY refs and bare Zotero keys; dedupe preserving order."""
    out: List[str] = []
    seen: set[str] = set()
    for raw in raw_keys or []:
        key = (raw or "").strip()
        if not key:
            continue
        if key.lower().startswith("paper:"):
            key = key.split(":", 1)[1].strip()
        key = key.upper()
        if len(key) != 8 or key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def resolve_focus_section(focus: str) -> Optional[str]:
    """Map compare focus to a section slug; None means summary/abstract tier."""
    f = (focus or "").strip().lower()
    if not f or f in ("overview", "general", "summary", "abstract"):
        return None
    return normalize_section_slug(f)


def _catalog_row(owner: str, zotero_key: str) -> Optional[dict]:
    from src.zotero_catalog import load_catalog

    key = (zotero_key or "").strip()
    for row in load_catalog(owner):
        if (row.get("zotero_key") or "").upper() == key.upper():
            return row
    return None


def _extract_markdown_section(body: str, header_prefix: str) -> str:
    """Return text under the first markdown heading matching header_prefix."""
    if not body or not header_prefix:
        return ""
    lines = body.splitlines()
    collecting = False
    chunks: List[str] = []
    header_lower = header_prefix.lower()
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#"):
            if collecting:
                break
            if stripped.lower().startswith(header_lower.lower()):
                collecting = True
            continue
        if collecting:
            chunks.append(line)
    return "\n".join(chunks).strip()


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n… [truncated]"


def _paper_header(row: Optional[dict], key: str) -> str:
    title = (row or {}).get("title") or "Untitled"
    authors = (row or {}).get("authors") or "Unknown"
    year = (row or {}).get("year") or "n/a"
    return f"**{title}** (`{key}`)\n{authors} ({year})"


def gather_paper_slice(
    owner: str,
    zotero_key: str,
    *,
    focus: str = "methods",
    max_chars: int = COMPARE_SLICE_MAX_CHARS,
) -> dict:
    """Collect one paper's comparison slice with source tier metadata."""
    key = (zotero_key or "").strip().upper()
    row = _catalog_row(owner, key)
    section_slug = resolve_focus_section(focus)
    result: dict = {
        "zotero_key": key,
        "title": (row or {}).get("title") or "Untitled",
        "authors": (row or {}).get("authors") or "",
        "year": (row or {}).get("year") or "",
        "source_tier": "missing",
        "source_label": "",
        "content": "",
        "note": "",
    }

    if section_slug:
        from src.zotero_client import fetch_paper_section_text

        body, err, meta = fetch_paper_section_text(
            owner,
            key,
            section_slug,
            max_chars=min(max_chars, PAPER_SECTION_DEFAULT_MAX_CHARS),
        )
        if body:
            result.update({
                "source_tier": "section",
                "source_label": section_display_label(section_slug),
                "content": body,
            })
            return result
        result["note"] = err or "Section extract unavailable."

        cached_header = _FOCUS_SUMMARY_HEADERS.get(section_slug)
        if cached_header:
            from src.paper_summaries import load_cached_paper_summary_body

            cached = load_cached_paper_summary_body(owner, key)
            if cached and cached.get("body"):
                excerpt = _extract_markdown_section(cached["body"], cached_header)
                if excerpt:
                    result.update({
                        "source_tier": "summary_section",
                        "source_label": f"DR summary — {cached_header.lstrip('#').strip()}",
                        "content": _truncate(excerpt, max_chars),
                        "note": result["note"],
                    })
                    return result

    from src.paper_summaries import load_cached_paper_summary_body

    cached = load_cached_paper_summary_body(owner, key)
    if cached and cached.get("body"):
        body = cached["body"]
        if section_slug and _FOCUS_SUMMARY_HEADERS.get(section_slug):
            excerpt = _extract_markdown_section(body, _FOCUS_SUMMARY_HEADERS[section_slug])
            if excerpt:
                body = excerpt
        result.update({
            "source_tier": "summary",
            "source_label": "Deep Research summary",
            "content": _truncate(body.strip(), max_chars),
        })
        return result

    if row:
        parts = []
        if row.get("abstract"):
            parts.append(row["abstract"].strip())
        elif row.get("title"):
            parts.append(row["title"])
        if parts:
            result.update({
                "source_tier": "abstract",
                "source_label": "Catalog abstract",
                "content": _truncate("\n".join(parts), max_chars),
            })
            if result["note"]:
                result["note"] += " Fell back to abstract."
            return result

    if not row:
        result["note"] = (result["note"] or "") + " Paper not in local Zotero catalog — sync catalog first."
    return result


def _collect_method_terms(text: str) -> set[str]:
    lower = (text or "").lower()
    found: set[str] = set()
    for a, b in _METHOD_CONTRASTS:
        if a in lower:
            found.add(a)
        if b in lower:
            found.add(b)
    return found


def _tension_notes(slices: List[dict], focus: str) -> List[str]:
    notes: List[str] = []
    slug = resolve_focus_section(focus)

    missing = [s["zotero_key"] for s in slices if not (s.get("content") or "").strip()]
    if missing:
        notes.append(
            f"No extractable content for: {', '.join(missing)} — try syncing Zotero or running Deep Research on these papers."
        )

    tier_counts: Dict[str, int] = {}
    for s in slices:
        tier = s.get("source_tier") or "unknown"
        tier_counts[tier] = tier_counts.get(tier, 0) + 1
    mixed = [t for t, n in tier_counts.items() if t not in ("missing",) and n < len(slices)]
    if mixed and len(tier_counts) > 1:
        notes.append(
            "Sources mixed across tiers (section vs summary vs abstract) — interpret differences cautiously."
        )

    if slug == "methods" or (focus or "").lower() in ("methods", "methodology", "method"):
        terms_by_paper = {
            s["zotero_key"]: _collect_method_terms(s.get("content") or "")
            for s in slices
        }
        for a, b in _METHOD_CONTRASTS:
            has_a = [k for k, t in terms_by_paper.items() if a in t]
            has_b = [k for k, t in terms_by_paper.items() if b in t]
            if has_a and has_b and set(has_a) != set(has_b):
                notes.append(
                    f"Method contrast: {a!r} emphasized in {', '.join(has_a)}; "
                    f"{b!r} in {', '.join(has_b)}."
                )

    # Simple directional contrast in results-focused slices
    if slug == "results" or (focus or "").lower() == "results":
        direction_re = re.compile(r"\b(increase[ds]?|decrease[ds]?|improve[ds]?|worse[n]?|lower[s]?|higher[s]?)\b", re.I)
        dirs: Dict[str, set[str]] = {}
        for s in slices:
            hits = {m.group(0).lower() for m in direction_re.finditer(s.get("content") or "")}
            if hits:
                dirs[s["zotero_key"]] = hits
        if len(dirs) >= 2:
            upish = {"increases", "increased", "increase", "improves", "improved", "improve", "higher", "highers"}
            downish = {"decreases", "decreased", "decrease", "worse", "worsen", "lower", "lowers"}
            ups = [k for k, h in dirs.items() if h & upish]
            downs = [k for k, h in dirs.items() if h & downish]
            if ups and downs and set(ups) != set(downs):
                notes.append(
                    f"Directional language differs: positive trend terms in {', '.join(ups)}; "
                    f"negative trend terms in {', '.join(downs)}."
                )

    return notes


def _suggested_graph_edges(slices: List[dict], focus: str, tensions: List[str]) -> List[dict]:
    """Draft typed edge proposals grouped for agent/user confirmation (T3)."""
    if len(slices) < 2:
        return []

    proposals: List[dict] = []
    focus_l = (focus or "").lower()

    for i, a in enumerate(slices):
        for b in slices[i + 1:]:
            key_a, key_b = a["zotero_key"], b["zotero_key"]
            title_a = a.get("title") or key_a
            title_b = b.get("title") or key_b
            combined = f"{a.get('content') or ''}\n{b.get('content') or ''}"
            kind, reason = infer_stance_from_text(combined, anchor=title_a)

            if kind == "relates" and focus_l in ("methods", "methodology", "method"):
                terms_a = _collect_method_terms(a.get("content") or "")
                terms_b = _collect_method_terms(b.get("content") or "")
                if terms_a & terms_b:
                    kind = "derives_from"
                    reason = f"Shared method lineage between «{title_a[:60]}» and «{title_b[:60]}»"
                elif terms_a and terms_b and terms_a != terms_b:
                    kind = "relates"
                    reason = f"Contrasting methods: «{title_a[:60]}» vs «{title_b[:60]}»"

            if tensions and kind == "relates":
                for note in tensions:
                    if "contrast" in note.lower() or "differs" in note.lower():
                        kind = "refutes"
                        reason = note[:240]
                        break

            proposals.append({
                "from": f"paper:{key_a}",
                "to": f"paper:{key_b}",
                "kind": kind,
                "label": edge_kind_label(kind),
                "comparison_label": {
                    "derives_from": "Builds on",
                    "refutes": "Challenges",
                    "supports": "Aligns with (evidence)",
                    "relates": "Aligns with (topic)",
                    "depends_on": "Requires",
                }.get(kind, "Relates"),
                "reason": reason[:240],
                "from_title": title_a,
                "to_title": title_b,
                "section_ref": (focus or "overview").strip() or "overview",
                "evidence": (combined or reason)[:240].strip(),
            })
    return proposals


def _relationship_hints(slices: List[dict], focus: str, tensions: List[str]) -> List[str]:
    """Draft edge-taxonomy hints — use suggest_link to persist after user confirms."""
    hints: List[str] = []
    for prop in _suggested_graph_edges(slices, focus, tensions):
        hints.append(
            f"**{prop['comparison_label']}** (`{prop['kind']}`): "
            f"`search_knowledge` suggest_link from `{prop['from']}` → `{prop['to']}` "
            f"with reason: {prop['reason']}"
        )
    if not hints and len(slices) >= 2:
        hints.append(
            "Use `search_knowledge` `suggest_link` with kind `relates`, `derives_from`, "
            "`refutes`, `supports`, or `depends_on` plus a one-line reason."
        )
    return hints


def format_compare_output(
    slices: List[dict],
    *,
    focus: str,
    question: str = "",
) -> str:
    focus_label = section_display_label(resolve_focus_section(focus) or "overview")
    lines = [
        f"# Paper comparison — focus: {focus_label}",
    ]
    if question.strip():
        lines.extend(["", f"**Question:** {question.strip()}"])

    lines.extend(["", "## Side-by-side"])
    for idx, s in enumerate(slices, 1):
        header = _paper_header(
            {"title": s.get("title"), "authors": s.get("authors"), "year": s.get("year")},
            s["zotero_key"],
        )
        tier = s.get("source_label") or s.get("source_tier") or "unknown"
        lines.extend([
            "",
            f"### {idx}. {s.get('title') or s['zotero_key']}",
            header,
            f"_Source: {tier}_",
        ])
        if s.get("note"):
            lines.append(f"_Note: {s['note']}_")
        content = (s.get("content") or "").strip()
        lines.append(content if content else "_(no content extracted)_")

    table_lines = [
        "",
        "## At a glance",
        "",
        "| Paper | Key | Source |",
        "| --- | --- | --- |",
    ]
    for s in slices:
        table_lines.append(
            f"| {s.get('title') or 'Untitled'} | `{s['zotero_key']}` | {s.get('source_label') or s.get('source_tier')} |"
        )
    lines.extend(table_lines)

    tensions = _tension_notes(slices, focus)
    if tensions:
        lines.extend(["", "## Possible tensions"])
        for note in tensions:
            lines.append(f"- {note}")

    proposals = _suggested_graph_edges(slices, focus, tensions)
    if proposals:
        lines.extend(["", "## Suggested graph edges (by taxonomy — confirm via suggest_link)"])
        by_kind: Dict[str, List[dict]] = {}
        for prop in proposals:
            by_kind.setdefault(prop["kind"], []).append(prop)
        for kind in ("derives_from", "refutes", "supports", "depends_on", "relates"):
            rows = by_kind.get(kind) or []
            if not rows:
                continue
            lines.append(f"### {edge_kind_label(kind)} (`{kind}`)")
            for prop in rows:
                lines.append(
                    f"- **{prop['comparison_label']}:** `{prop['from']}` → `{prop['to']}` — {prop['reason']}"
                )

    hints = _relationship_hints(slices, focus, tensions)
    if hints:
        lines.extend(["", "## Relationship hints (draft — not auto-linked)"])
        for hint in hints:
            lines.append(f"- {hint}")

    text = "\n".join(lines)
    if len(text) > COMPARE_TOTAL_MAX_CHARS:
        text = text[:COMPARE_TOTAL_MAX_CHARS] + "\n… [comparison truncated]"
    return text


def execute_compare_papers(args: dict, owner: str = "") -> Dict[str, Any]:
    """Sync compare for ≤3 papers; defer payload for >3 (handled by async wrapper)."""
    if not isinstance(args, dict):
        args = {}

    owner = (owner or "").strip()
    raw_keys = args.get("paper_keys") or args.get("papers") or []
    if isinstance(raw_keys, str):
        raw_keys = [k.strip() for k in raw_keys.split(",") if k.strip()]

    keys = normalize_paper_keys(list(raw_keys))
    focus = (args.get("focus") or "methods").strip()
    question = (args.get("question") or args.get("query") or "").strip()

    if len(keys) < 2:
        return {
            "error": "At least two distinct paper_keys are required (8-char Zotero keys or paper:KEY).",
            "exit_code": 1,
        }

    if len(keys) > COMPARE_SYNC_MAX_PAPERS:
        return {
            "defer_to_research": True,
            "paper_keys": keys,
            "focus": focus,
            "question": question,
            "output": (
                f"More than {COMPARE_SYNC_MAX_PAPERS} papers ({len(keys)}) — "
                "use Deep Research compare mode for a full async report."
            ),
            "exit_code": 0,
        }

    slices = [gather_paper_slice(owner, k, focus=focus) for k in keys]
    output = format_compare_output(slices, focus=focus, question=question)

    return {
        "output": output,
        "paper_keys": keys,
        "focus": focus,
        "suggested_edges": _suggested_graph_edges(slices, focus, _tension_notes(slices, focus)),
        "slices": [
            {
                "zotero_key": s["zotero_key"],
                "source_tier": s.get("source_tier"),
                "source_label": s.get("source_label"),
                "has_content": bool((s.get("content") or "").strip()),
            }
            for s in slices
        ],
        "exit_code": 0,
    }
