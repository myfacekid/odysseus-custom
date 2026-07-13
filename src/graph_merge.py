"""Batch merge of proposed graph edges (Edge Taxonomy T2).

Preview validates proposals and detects conflicts; apply writes accepted rows only.
See docs/knowledge-graph-edge-taxonomy-roadmap_v3.md.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from src.edge_taxonomy import SEMANTIC_EDGE_KINDS, edge_kind_label, PIPELINE_EDGE_KINDS
from src.graph_proposals import coerce_graph_proposal, normalize_proposal_kind

MAX_MERGE_PROPOSALS = 20

_STANCE_OPPOSITES: Tuple[Tuple[str, str], ...] = (
    ("supports", "refutes"),
)


def _proposal_id(index: int, fr: str, to: str, kind: str) -> str:
    return f"p{index}-{fr}|{to}|{kind}"


def _coerce_proposal(raw: Any, index: int) -> Optional[dict]:
    row = coerce_graph_proposal(raw, source="merge_batch", index=index)
    if not row:
        return None
    kind = row["kind"]
    if kind not in SEMANTIC_EDGE_KINDS and kind not in PIPELINE_EDGE_KINDS:
        kind = normalize_proposal_kind(kind)
        row["kind"] = kind if kind in SEMANTIC_EDGE_KINDS else "relates"
    return {
        "proposal_id": row.get("proposal_id") or row.get("id"),
        "from": row["from"],
        "to": row["to"],
        "kind": row["kind"],
        "reason": row.get("reason") or "",
        "confidence": row.get("confidence"),
        "source": row.get("source") or "merge_batch",
    }


def _existing_manual_index(owner: str) -> Tuple[List[dict], Dict[Tuple[str, str, str], dict]]:
    from src.knowledge_graph import load_manual_edges

    manual = load_manual_edges(owner)
    by_key: Dict[Tuple[str, str, str], dict] = {}
    for row in manual:
        key = (
            row.get("from") or "",
            row.get("to") or "",
            normalize_proposal_kind(row.get("kind")),
        )
        if key[0] and key[1]:
            by_key[key] = row
    return manual, by_key


def _stance_conflict(existing_kind: str, proposed_kind: str) -> Optional[str]:
    ek = normalize_proposal_kind(existing_kind)
    pk = normalize_proposal_kind(proposed_kind)
    for a, b in _STANCE_OPPOSITES:
        if (ek == a and pk == b) or (ek == b and pk == a):
            return f"Opposing stance: existing {edge_kind_label(ek)} vs proposed {edge_kind_label(pk)}"
    return None


def preview_merge_proposals(owner: str, proposals: List[Any]) -> Dict[str, Any]:
    """Validate batch edge proposals — does not write."""
    from src.knowledge_graph import get_node, normalize_node_id

    owner = (owner or "").strip()
    if not isinstance(proposals, list):
        return {"ok": False, "error": "proposals must be a list", "rows": []}
    if len(proposals) > MAX_MERGE_PROPOSALS:
        return {
            "ok": False,
            "error": f"At most {MAX_MERGE_PROPOSALS} proposals per batch",
            "rows": [],
        }

    _, existing_by_key = _existing_manual_index(owner)
    rows: List[dict] = []
    seen_keys: Set[Tuple[str, str, str]] = set()

    for index, raw in enumerate(proposals):
        prop = _coerce_proposal(raw, index)
        if not prop:
            rows.append({
                "proposal_id": f"invalid-{index}",
                "status": "invalid",
                "errors": ["Missing from/to or invalid row"],
                "selected": False,
            })
            continue

        fr = normalize_node_id(owner, prop["from"]) or prop["from"]
        to = normalize_node_id(owner, prop["to"]) or prop["to"]
        kind = prop["kind"]
        key = (fr, to, kind)

        errors: List[str] = []
        warnings: List[str] = []
        status = "ready"

        if fr == to:
            status = "invalid"
            errors.append("Cannot link a node to itself")
        if key in seen_keys:
            status = "invalid"
            errors.append("Duplicate proposal in this batch")
        seen_keys.add(key)

        from_node = get_node(owner, fr)
        to_node = get_node(owner, to)
        if not from_node:
            status = "missing_node"
            errors.append(f"Source node not in graph: {fr}")
        if not to_node:
            status = "missing_node"
            errors.append(f"Target node not in graph: {to}")

        existing = existing_by_key.get(key)
        can_update_reason = False
        if existing:
            status = "duplicate"
            if prop["reason"] and prop["reason"] != (existing.get("reason") or "").strip():
                can_update_reason = True
                warnings.append("Same kind exists — can update reason on apply")
            else:
                warnings.append("Identical edge already exists")

        for ex_key, ex_row in existing_by_key.items():
            if ex_key[0] != fr or ex_key[1] != to:
                continue
            if ex_key[2] == kind:
                continue
            conflict = _stance_conflict(ex_row.get("kind") or "", kind)
            if conflict:
                status = "conflict"
                errors.append(conflict)

        rows.append({
            "proposal_id": prop["proposal_id"],
            "from": fr,
            "to": to,
            "from_title": (from_node or {}).get("title") or fr,
            "to_title": (to_node or {}).get("title") or to,
            "kind": kind,
            "kind_label": edge_kind_label(kind),
            "reason": prop["reason"],
            "status": status,
            "errors": errors,
            "warnings": warnings,
            "can_update_reason": can_update_reason,
            "selected": status == "ready" or (status == "duplicate" and can_update_reason),
        })

    ready = sum(1 for r in rows if r.get("status") == "ready")
    conflicts = sum(1 for r in rows if r.get("status") == "conflict")
    return {
        "ok": True,
        "rows": rows,
        "summary": {
            "total": len(rows),
            "ready": ready,
            "conflicts": conflicts,
            "duplicates": sum(1 for r in rows if r.get("status") == "duplicate"),
            "invalid": sum(1 for r in rows if r.get("status") == "invalid"),
            "missing_node": sum(1 for r in rows if r.get("status") == "missing_node"),
        },
        "merge_session_id": str(uuid.uuid4()),
    }


def apply_merge_proposals(owner: str, accepted: List[Any]) -> Dict[str, Any]:
    """Write accepted merge rows (partial accept supported)."""
    from src.knowledge_graph import add_graph_link, update_graph_link

    if not isinstance(accepted, list):
        return {"ok": False, "error": "accepted must be a list", "results": []}
    if len(accepted) > MAX_MERGE_PROPOSALS:
        return {"ok": False, "error": f"At most {MAX_MERGE_PROPOSALS} rows per apply", "results": []}

    results: List[dict] = []
    applied = 0
    skipped = 0
    updated = 0

    for index, raw in enumerate(accepted):
        if not isinstance(raw, dict):
            skipped += 1
            results.append({"ok": False, "action": "skip", "error": "Invalid row"})
            continue
        if raw.get("skip") or raw.get("action") == "skip" or raw.get("selected") is False:
            skipped += 1
            results.append({"ok": True, "action": "skip", "proposal_id": raw.get("proposal_id")})
            continue

        prop = _coerce_proposal(raw, index)
        if not prop:
            skipped += 1
            results.append({"ok": False, "action": "skip", "error": "Invalid proposal"})
            continue

        action = (raw.get("action") or "").strip().lower()
        update_reason = action == "update_reason" or raw.get("update_reason") is True

        preview = preview_merge_proposals(owner, [prop])
        row = (preview.get("rows") or [{}])[0]
        status = row.get("status")

        if status == "conflict":
            skipped += 1
            results.append({
                "ok": False,
                "action": "skip",
                "proposal_id": prop["proposal_id"],
                "error": "; ".join(row.get("errors") or ["Conflict"]),
            })
            continue

        if status in ("invalid", "missing_node"):
            skipped += 1
            results.append({
                "ok": False,
                "action": "skip",
                "proposal_id": prop["proposal_id"],
                "error": "; ".join(row.get("errors") or [status]),
            })
            continue

        if status == "duplicate" or update_reason:
            if not prop["reason"]:
                skipped += 1
                results.append({
                    "ok": False,
                    "action": "skip",
                    "proposal_id": prop["proposal_id"],
                    "error": "No new reason to apply",
                })
                continue
            out = update_graph_link(
                owner,
                prop["from"],
                prop["to"],
                kind=prop["kind"],
                reason=prop["reason"],
            )
            if out.get("ok"):
                updated += 1
            results.append({**out, "action": "update_reason", "proposal_id": prop["proposal_id"]})
            continue

        out = add_graph_link(
            owner,
            prop["from"],
            prop["to"],
            kind=prop["kind"],
            reason=prop["reason"],
            source=prop.get("source") or "merge_batch",
        )
        if out.get("ok") and not out.get("duplicate"):
            applied += 1
        elif out.get("duplicate"):
            skipped += 1
        results.append({**out, "action": "add", "proposal_id": prop["proposal_id"]})

    return {
        "ok": True,
        "applied": applied,
        "updated": updated,
        "skipped": skipped,
        "results": results,
    }


def format_merge_preview_for_agent(payload: dict) -> str:
    """Compact text summary for agent tool output."""
    if not payload.get("ok"):
        return payload.get("error") or "Merge preview failed"
    summary = payload.get("summary") or {}
    lines = [
        f"Merge preview — {summary.get('total', 0)} proposal(s): "
        f"{summary.get('ready', 0)} ready, {summary.get('conflicts', 0)} conflict(s), "
        f"{summary.get('duplicates', 0)} duplicate(s).",
        "Review in Links → Batch merge, or apply with merge_subgraph phase=apply.",
        "",
    ]
    for row in payload.get("rows") or []:
        flag = row.get("status") or "?"
        lines.append(
            f"- [{flag}] {row.get('from_title') or row.get('from')} → "
            f"{row.get('to_title') or row.get('to')} ({row.get('kind_label') or row.get('kind')})"
        )
        if row.get("reason"):
            lines.append(f"  reason: {row['reason']}")
        for err in row.get("errors") or []:
            lines.append(f"  ! {err}")
    return "\n".join(lines)
