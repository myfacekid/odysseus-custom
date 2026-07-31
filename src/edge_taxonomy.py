"""Knowledge graph semantic edge taxonomy (T0/T3).

Five cognitive edge types plus legacy aliases.
"""

from __future__ import annotations

from typing import Dict, Optional, Tuple

SEMANTIC_EDGE_KINDS = frozenset({
    "derives_from",
    "refutes",
    "supports",
    "relates",
    "depends_on",
})
LEGACY_MANUAL_KINDS = frozenset({"link", "related"})
MANUAL_EDGE_KINDS = SEMANTIC_EDGE_KINDS | LEGACY_MANUAL_KINDS
PIPELINE_EDGE_KINDS = frozenset({"summarizes"})
INFERRED_EDGE_KINDS = frozenset({"parent", "wikilink", "in_collection"})
ALL_EDGE_KINDS = SEMANTIC_EDGE_KINDS | LEGACY_MANUAL_KINDS | PIPELINE_EDGE_KINDS | INFERRED_EDGE_KINDS

EDGE_OPTIONAL_FIELDS = (
    "generated_at",
    "research_session_id",
    "zotero_key",
    "reason",
    "confidence",
    "created_at",
    "updated_at",
)

EDGE_KIND_LABELS: Dict[str, str] = {
    "derives_from": "Derives from",
    "refutes": "Refutes",
    "supports": "Supports",
    "relates": "Relates",
    "depends_on": "Depends on",
    "link": "Link",
    "related": "Related",
    "parent": "Parent",
    "wikilink": "Wikilink",
    "in_collection": "Collection",
    "summarizes": "Summarizes",
}

COMPARISON_LABEL_TO_KIND: Dict[str, str] = {
    "builds on": "derives_from",
    "extends": "derives_from",
    "derives from": "derives_from",
    "challenges": "refutes",
    "contradicts": "refutes",
    "refutes": "refutes",
    "aligns with": "relates",
    "similar to": "relates",
    "confirms": "supports",
    "corroborates": "supports",
    "supports": "supports",
    "requires": "depends_on",
    "depends on": "depends_on",
}

_STANCE_PATTERNS: Tuple[Tuple[str, str], ...] = (
    ("refutes", "contradict|disprove|invalidate|refute|challenge|unlike|however|in contrast|whereas"),
    ("supports", "confirm|corroborate|support|consistent with|aligns with|validates"),
    ("derives_from", "build[s]? on|extend[s]?|adapt[s]?|implement[s]?|inspired by|follow[s]? from|based on"),
    ("depends_on", "require[s]?|depend[s]? on|prerequisite|must read|cannot understand without"),
)


def normalize_semantic_kind(kind: Optional[str], *, default: str = "relates") -> str:
    k = (kind or "").strip().lower()
    if k in LEGACY_MANUAL_KINDS:
        return "relates"
    if k in SEMANTIC_EDGE_KINDS:
        return k
    return default


def edge_kind_label(kind: Optional[str]) -> str:
    k = normalize_semantic_kind(kind, default=(kind or "relates"))
    if k in EDGE_KIND_LABELS:
        return EDGE_KIND_LABELS[k]
    raw = (kind or "relates").strip()
    return EDGE_KIND_LABELS.get(raw, raw.replace("_", " ").title())


def is_inhibitory_kind(kind: Optional[str]) -> bool:
    return normalize_semantic_kind(kind) == "refutes"


def is_symmetric_display_kind(kind: Optional[str]) -> bool:
    return normalize_semantic_kind(kind) == "relates"


def format_edge_for_agent(
    kind: Optional[str],
    *,
    reason: str = "",
    direction: str = "out",
) -> str:
    """Format an edge kind for agent neighbor output (T3 activation hints)."""
    label = edge_kind_label(kind)
    prefix = "INHIBITORY — " if is_inhibitory_kind(kind) else ""
    arrow = "↔" if is_symmetric_display_kind(kind) and direction == "both" else "→"
    reason_t = (reason or "").strip()
    base = f"{prefix}{label} {arrow}".strip()
    if reason_t:
        return f"{base} — {reason_t[:240]}"
    return base


def infer_stance_from_text(text: str, *, anchor: str = "") -> Tuple[str, str]:
    """Rule-based stance inference from report or excerpt text."""
    import re

    blob = (text or "").lower()
    anchor_l = (anchor or "").lower()
    window = blob
    if anchor_l and anchor_l in blob:
        idx = blob.find(anchor_l)
        window = blob[max(0, idx - 120): idx + len(anchor_l) + 160]

    for kind, pattern in _STANCE_PATTERNS:
        if re.search(pattern, window, re.I):
            reason = f"Inferred {edge_kind_label(kind).lower()} from research report"
            if anchor:
                reason += f" near «{anchor[:80]}»"
            return kind, reason
    return "relates", "Linked from Deep Research session"


def map_comparison_label(label: str) -> str:
    key = (label or "").strip().lower()
    return COMPARISON_LABEL_TO_KIND.get(key, "relates")
