"""Typed graph edges from completed Deep Research sessions (T3).

Replaces flat research→paper ``related`` stars with stance-aware edges when the
report text supports inference. See docs/knowledge-graph-edge-taxonomy-roadmap_v3.md.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from src.edge_taxonomy import infer_stance_from_text, normalize_semantic_kind
from src.research_graph import RESEARCH_EDGE_SOURCE, collect_research_link_targets


def _report_text(data: dict) -> str:
    for key in ("raw_report", "report", "result", "synthesis"):
        val = (data or {}).get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


def _seed_title_map(data: dict) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for row in (data or {}).get("seed_paper_details") or []:
        if not isinstance(row, dict):
            continue
        key = (row.get("zotero_key") or "").strip().upper()
        if key:
            out[key] = (row.get("title") or key).strip()
    return out


def _paper_node_id(key: str) -> str:
    from src.knowledge_graph import node_id

    return node_id("paper", key.upper())


def _research_node_id(session_id: str) -> str:
    from src.knowledge_graph import node_id

    return node_id("research", session_id)


def _stance_for_paper_target(data: dict, paper_node: str, title_map: Dict[str, str]) -> Tuple[str, str]:
    report = _report_text(data)
    key = paper_node.split(":", 1)[-1].upper()
    anchor = title_map.get(key) or key
    mode = ((data or {}).get("research_mode") or "literature_review").strip().lower()
    kind, reason = infer_stance_from_text(report, anchor=anchor)
    if mode == "compare" and kind == "relates":
        reason = f"Compare-mode research linked to «{anchor[:80]}»"
    elif mode == "gap_analysis" and kind == "relates":
        kind, reason = "supports", f"Gap-analysis source: {anchor[:80]}"
    query = ((data or {}).get("query") or "").strip()
    if query and kind == "relates" and not report:
        reason = f"Research «{query[:120]}»"
    return kind, reason


def _compare_paper_pair_edges(data: dict, paper_nodes: List[str]) -> List[dict]:
    """Paper→paper edges for compare-mode sessions (seed pairs)."""
    if ((data or {}).get("research_mode") or "").strip().lower() != "compare":
        return []
    if len(paper_nodes) < 2:
        return []

    report = _report_text(data).lower()
    title_map = _seed_title_map(data)
    edges: List[dict] = []
    seen: set[Tuple[str, str, str]] = set()

    for i, fr in enumerate(paper_nodes):
        for to in paper_nodes[i + 1:]:
            key_a = fr.split(":", 1)[-1].upper()
            key_b = to.split(":", 1)[-1].upper()
            title_a = title_map.get(key_a, key_a)
            title_b = title_map.get(key_b, key_b)
            window = report
            for token in (title_a.lower()[:24], title_b.lower()[:24], key_a.lower(), key_b.lower()):
                if token and token in report:
                    idx = report.find(token)
                    window = report[max(0, idx - 80): idx + 120]
                    break

            kind, reason = infer_stance_from_text(window, anchor=title_a)
            if kind == "relates" and ("contrast" in window or "trade-off" in window or " differ" in window):
                reason = f"Compare contrast: «{title_a[:60]}» vs «{title_b[:60]}»"
            elif kind == "relates":
                reason = f"Compared in Deep Research: «{title_a[:60]}» ↔ «{title_b[:60]}»"

            for direction in ((fr, to), (to, fr)):
                a, b = direction
                dedupe = (a, b, kind)
                if dedupe in seen:
                    continue
                seen.add(dedupe)
                edges.append({
                    "from": a,
                    "to": b,
                    "kind": kind,
                    "reason": reason[:280],
                    "source": RESEARCH_EDGE_SOURCE,
                    "confidence": 0.75,
                })
    return edges


def build_research_graph_edges(session_id: str, data: dict, *, cap: int = 20) -> List[dict]:
    """Return manual edge rows for a completed research session."""
    sid = (session_id or "").strip()
    if not sid:
        return []

    rid = _research_node_id(sid)
    title_map = _seed_title_map(data)
    targets = collect_research_link_targets(data, cap=cap)
    edges: List[dict] = []
    seen: set[Tuple[str, str, str]] = set()

    for to in targets:
        kind, reason = _stance_for_paper_target(data, to, title_map)
        kind = normalize_semantic_kind(kind)
        key = (rid, to, kind)
        if key in seen:
            continue
        seen.add(key)
        edges.append({
            "from": rid,
            "to": to,
            "kind": kind,
            "reason": reason[:280],
            "source": RESEARCH_EDGE_SOURCE,
            "confidence": 0.8 if kind != "relates" else 0.6,
        })

    for row in _compare_paper_pair_edges(data, targets[:8]):
        key = (row["from"], row["to"], row["kind"])
        if key in seen:
            continue
        seen.add(key)
        edges.append(row)

    return edges
