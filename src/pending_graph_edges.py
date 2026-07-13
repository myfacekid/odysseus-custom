"""Learned graph connection proposals — draft until user accepts (Brain inbox).

Mirrors the skills draft/publish pattern: proposals queue on disk, user
accepts/rejects/deferrals from conversation pop-ups or Brain → Connections.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from src.edge_taxonomy import EDGE_OPTIONAL_FIELDS, PIPELINE_EDGE_KINDS
from src.graph_proposals import (
    coerce_pending_proposal,
    normalize_proposal_kind,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _pending_path(owner: str):
    from src.knowledge_graph import _owner_dir

    return _owner_dir(owner) / "pending_edges.jsonl"


def _rejected_path(owner: str):
    from src.knowledge_graph import _owner_dir

    return _owner_dir(owner) / "rejected_edge_keys.jsonl"


def _normalize_proposal_kind(kind: Optional[str], *, default: str = "relates") -> str:
    return normalize_proposal_kind(kind, default=default)


def _edge_key(fr: str, to: str, kind: str) -> Tuple[str, str, str]:
    return (fr, to, _normalize_proposal_kind(kind))


def _read_rows(path) -> List[dict]:
    from src.knowledge_graph import _read_jsonl

    return _read_jsonl(path)


def _write_rows(path, rows: List[dict]) -> None:
    from src.knowledge_graph import _write_jsonl

    _write_jsonl(path, rows)


def load_rejected_keys(owner: str) -> Set[Tuple[str, str, str]]:
    rows = _read_rows(_rejected_path(owner))
    out: Set[Tuple[str, str, str]] = set()
    for row in rows:
        key = _edge_key(row.get("from") or "", row.get("to") or "", row.get("kind") or "relates")
        if key[0] and key[1]:
            out.add(key)
    return out


def load_pending_edges(owner: str, *, status: str = "pending") -> List[dict]:
    rows = _read_rows(_pending_path(owner))
    if status:
        rows = [r for r in rows if (r.get("status") or "pending") == status]
    rows.sort(key=lambda r: r.get("created_at") or "", reverse=True)
    return rows


def save_pending_edges(owner: str, rows: List[dict]) -> None:
    """Persist pending rows (used by link audit and admin tools)."""
    _write_rows(_pending_path(owner), rows)


def _coerce_proposal(raw: Any, source: str = "agent") -> Optional[dict]:
    return coerce_pending_proposal(raw, source=source)


def filter_pending_for_project(
    owner: str,
    project_id: str,
    rows: Optional[List[dict]] = None,
) -> List[dict]:
    """Pending rows touching a project's link neighborhood or tagged project_id."""
    from src.project_graph import get_project_graph_links, project_node_id

    project_id = (project_id or "").strip()
    if not owner or not project_id:
        return []
    pending = rows if rows is not None else load_pending_edges(owner)
    try:
        links = get_project_graph_links(owner, project_id)
    except Exception:
        links = {}
    touch = {project_node_id(project_id)}
    for bucket in ("outgoing", "incoming"):
        for row in links.get(bucket) or []:
            node = row.get("node") if isinstance(row, dict) else None
            nid = (node or {}).get("id") if isinstance(node, dict) else None
            if nid:
                touch.add(nid)
    out: List[dict] = []
    for row in pending:
        if (row.get("project_id") or "").strip() == project_id:
            out.append(row)
            continue
        fr = row.get("from") or ""
        to = row.get("to") or ""
        if fr in touch or to in touch:
            out.append(row)
    return out


def enqueue_proposals(
    owner: str,
    proposals: List[Any],
    *,
    source: str = "agent",
    skip_rejected: bool = True,
    skip_existing_manual: bool = True,
    user_initiated: bool = False,
) -> Dict[str, Any]:
    """Add proposals to Brain inbox; skip duplicates already pending/rejected/graph."""
    from src.knowledge_graph import load_manual_edges
    from src.learned_link_prefs import producer_enqueue_allowed

    owner = (owner or "").strip()
    if not owner:
        return {"ok": False, "error": "owner required", "added": 0, "rows": []}
    if not isinstance(proposals, list):
        return {"ok": False, "error": "proposals must be a list", "added": 0, "rows": []}
    if not producer_enqueue_allowed(owner, user_initiated=user_initiated):
        return {
            "ok": True,
            "added": 0,
            "skipped": len(proposals),
            "total_pending": len(load_pending_edges(owner)),
            "rows": [],
            "gated": True,
        }

    pending = load_pending_edges(owner)
    pending_keys = {_edge_key(r.get("from", ""), r.get("to", ""), r.get("kind", "")) for r in pending}
    rejected = load_rejected_keys(owner) if skip_rejected else set()
    manual_keys: Set[Tuple[str, str, str]] = set()
    if skip_existing_manual:
        manual_keys = {
            _edge_key(e.get("from", ""), e.get("to", ""), e.get("kind", ""))
            for e in load_manual_edges(owner)
        }

    added = 0
    skipped = 0
    added_rows: List[dict] = []
    for raw in proposals:
        row = _coerce_proposal(raw, source=source)
        if not row:
            skipped += 1
            continue
        key = _edge_key(row["from"], row["to"], row["kind"])
        if key in pending_keys or key in rejected or key in manual_keys:
            skipped += 1
            continue
        pending.append(row)
        pending_keys.add(key)
        added_rows.append(row)
        added += 1

    _write_rows(_pending_path(owner), pending)
    if added > 0:
        try:
            from src.event_bus import fire_event

            fire_event("link_proposed", owner, count=added)
        except Exception:
            pass
    return {
        "ok": True,
        "added": added,
        "skipped": skipped,
        "total_pending": len(pending),
        "rows": added_rows,
    }


def reject_proposal(owner: str, proposal: dict) -> Dict[str, Any]:
    """Remove matching pending row and record key so it is not re-suggested."""
    row = _coerce_proposal(proposal)
    if not row:
        return {"ok": False, "error": "invalid proposal"}
    key = _edge_key(row["from"], row["to"], row["kind"])
    pending = load_pending_edges(owner)
    pending = [p for p in pending if _edge_key(p.get("from", ""), p.get("to", ""), p.get("kind", "")) != key]
    _write_rows(_pending_path(owner), pending)

    rejected = _read_rows(_rejected_path(owner))
    if not any(_edge_key(r.get("from", ""), r.get("to", ""), r.get("kind", "")) == key for r in rejected):
        rejected.append({
            "from": row["from"],
            "to": row["to"],
            "kind": row["kind"],
            "rejected_at": _utc_now(),
        })
        _write_rows(_rejected_path(owner), rejected)
    return {"ok": True, "removed_pending": True}


def reject_proposals(owner: str, proposals: List[Any]) -> Dict[str, Any]:
    count = 0
    for raw in proposals or []:
        out = reject_proposal(owner, raw if isinstance(raw, dict) else {})
        if out.get("ok"):
            count += 1
    return {"ok": True, "rejected": count}


def _apply_pending_row(owner: str, row: dict) -> Dict[str, Any]:
    kind = _normalize_proposal_kind(row.get("kind") or "relates")
    if kind in PIPELINE_EDGE_KINDS:
        from src.knowledge_graph import add_pipeline_edge

        metadata = {
            key: row[key]
            for key in EDGE_OPTIONAL_FIELDS
            if key in row and row[key] not in (None, "")
        }
        edge_source = (row.get("source") or "pipeline").strip() or "pipeline"
        return add_pipeline_edge(
            owner,
            row["from"],
            row["to"],
            kind=kind,
            source=edge_source,
            **metadata,
        )

    from src.knowledge_graph import add_graph_link

    return add_graph_link(
        owner,
        row["from"],
        row["to"],
        kind=kind,
        reason=row.get("reason") or "",
        source="user",
        confidence=row.get("confidence"),
    )


def accept_pending_edge(owner: str, proposal_id: str) -> Dict[str, Any]:
    pending = load_pending_edges(owner)
    match = next((p for p in pending if p.get("id") == proposal_id), None)
    if not match:
        return {"ok": False, "error": "Proposal not found"}

    out = _apply_pending_row(owner, match)
    if not out.get("ok") and not out.get("duplicate"):
        return out

    remaining = [p for p in pending if p.get("id") != proposal_id]
    _write_rows(_pending_path(owner), remaining)
    return {"ok": True, "link": out, "remaining": len(remaining)}


def _resolve_accept_rows(
    owner: str,
    proposals: List[Any],
    pending_by_id: Dict[str, dict],
) -> Tuple[List[dict], int]:
    resolved: List[dict] = []
    skipped = 0
    for raw in proposals or []:
        if not isinstance(raw, dict):
            skipped += 1
            continue
        pid = (raw.get("id") or raw.get("proposal_id") or "").strip()
        row = pending_by_id.get(pid) if pid else _coerce_proposal(raw)
        if not row:
            skipped += 1
            continue
        resolved.append(row)
    return resolved, skipped


def _accept_proposals_via_merge(owner: str, rows: List[dict], pending: List[dict]) -> Dict[str, Any]:
    from src.graph_merge import apply_merge_proposals, preview_merge_proposals

    pipeline_rows: List[dict] = []
    semantic_rows: List[dict] = []
    for row in rows:
        if _normalize_proposal_kind(row.get("kind") or "relates") in PIPELINE_EDGE_KINDS:
            pipeline_rows.append(row)
        else:
            semantic_rows.append(row)

    applied = 0
    updated = 0
    skipped = 0
    results: List[dict] = []
    accepted_ids: Set[str] = set()

    if semantic_rows:
        preview = preview_merge_proposals(owner, semantic_rows)
        if not preview.get("ok"):
            return preview
        accepted: List[dict] = []
        for row in preview.get("rows") or []:
            status = row.get("status")
            if status == "ready":
                accepted.append({**row, "selected": True, "action": "add"})
            elif status == "duplicate" and row.get("can_update_reason"):
                accepted.append({**row, "selected": True, "action": "update_reason"})
            else:
                skipped += 1
        merge_out = apply_merge_proposals(owner, accepted)
        applied += merge_out.get("applied", 0)
        updated += merge_out.get("updated", 0)
        skipped += merge_out.get("skipped", 0)
        results.extend(merge_out.get("results") or [])
        preview_rows = preview.get("rows") or []
        for idx, src in enumerate(semantic_rows):
            dst = preview_rows[idx] if idx < len(preview_rows) else {}
            if dst.get("status") == "ready" or (
                dst.get("status") == "duplicate" and dst.get("can_update_reason")
            ):
                pid = src.get("id")
                if pid:
                    accepted_ids.add(pid)

    for row in pipeline_rows:
        out = _apply_pending_row(owner, row)
        results.append(out)
        if out.get("ok") or out.get("duplicate"):
            applied += 1
            pid = row.get("id")
            if pid:
                accepted_ids.add(pid)
        else:
            skipped += 1

    if accepted_ids:
        pending = [p for p in pending if p.get("id") not in accepted_ids]
        _write_rows(_pending_path(owner), pending)

    return {
        "ok": True,
        "applied": applied,
        "updated": updated,
        "skipped": skipped,
        "results": results,
        "remaining": len(pending),
    }


def accept_proposals(owner: str, proposals: List[Any]) -> Dict[str, Any]:
    """Accept proposals via merge preview when batch size > 1."""
    pending = load_pending_edges(owner)
    pending_by_id = {p.get("id"): p for p in pending}
    resolved, skipped = _resolve_accept_rows(owner, proposals, pending_by_id)
    if not resolved:
        return {"ok": True, "applied": 0, "skipped": skipped, "results": []}

    if len(resolved) >= 2:
        out = _accept_proposals_via_merge(owner, resolved, pending)
        out["skipped"] = out.get("skipped", 0) + skipped
        return out

    row = resolved[0]
    out = _apply_pending_row(owner, row)
    results = [out]
    applied = 1 if out.get("ok") or out.get("duplicate") else 0
    if not (out.get("ok") or out.get("duplicate")):
        skipped += 1
        applied = 0
    pid = row.get("id")
    if pid and (out.get("ok") or out.get("duplicate")):
        pending = [p for p in pending if p.get("id") != pid]
        _write_rows(_pending_path(owner), pending)
    return {"ok": True, "applied": applied, "skipped": skipped, "results": results}


def delete_pending_edge(owner: str, proposal_id: str) -> Dict[str, Any]:
    pending = load_pending_edges(owner)
    before = len(pending)
    pending = [p for p in pending if p.get("id") != proposal_id]
    if len(pending) == before:
        return {"ok": False, "error": "Proposal not found"}
    _write_rows(_pending_path(owner), pending)
    return {"ok": True, "remaining": len(pending)}


def pending_count(owner: str) -> int:
    return len(load_pending_edges(owner))


def get_pending_neighbors(owner: str, full_id: str) -> Dict[str, List[dict]]:
    """Pending proposals touching *full_id* (not yet in the merged graph)."""
    fid = (full_id or "").strip()
    if not owner or not fid:
        return {"outgoing": [], "incoming": []}
    outgoing: List[dict] = []
    incoming: List[dict] = []
    for row in load_pending_edges(owner):
        fr = row.get("from") or ""
        to = row.get("to") or ""
        if fr == fid:
            outgoing.append({"edge": row, "proposal": row})
        elif to == fid:
            incoming.append({"edge": row, "proposal": row})
    return {"outgoing": outgoing, "incoming": incoming}


def format_pending_rows_for_agent(rows: List[dict], *, prefix: str = "[PROPOSED]") -> List[str]:
    from src.edge_taxonomy import edge_kind_label

    lines: List[str] = []
    for row in rows:
        fr = row.get("from_title") or row.get("from") or "?"
        to = row.get("to_title") or row.get("to") or "?"
        kind = edge_kind_label(row.get("kind"))
        reason = (row.get("reason") or "").strip()
        src = (row.get("source") or "").strip()
        line = f"- {prefix} **{fr}** → **{to}** · _{kind}_"
        if reason:
            line += f" — {reason[:200]}"
        if src:
            line += f" _(source: {src})_"
        lines.append(line)
    return lines
