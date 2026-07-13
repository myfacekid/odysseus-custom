"""Periodic quality pass for learned connection proposals (L5).

Re-runs merge preview on pending rows — flags conflicts and missing nodes.
Does not auto-accept or reject; audit metadata is stored on pending rows.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from src.graph_merge import MAX_MERGE_PROPOSALS, preview_merge_proposals

_FLAGGED_STATUSES = frozenset({"conflict", "missing_node", "invalid"})


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _audit_status_from_preview(status: str) -> str:
    st = (status or "ready").strip().lower()
    if st == "ready":
        return "ok"
    if st in _FLAGGED_STATUSES or st == "duplicate":
        return st
    return "ok"


def audit_pending_links(owner: str) -> Dict[str, Any]:
    """Validate all pending proposals via preview_merge_proposals; persist flags."""
    from src.pending_graph_edges import load_pending_edges, save_pending_edges

    owner = (owner or "").strip()
    if not owner:
        return {"ok": False, "error": "owner required", "audited": 0, "flagged": 0}

    pending = load_pending_edges(owner)
    if not pending:
        return {
            "ok": True,
            "audited": 0,
            "flagged": 0,
            "summary": {},
            "message": "No pending connections to audit",
        }

    updates: Dict[str, dict] = {}
    summary = {
        "ok": 0,
        "conflict": 0,
        "missing_node": 0,
        "invalid": 0,
        "duplicate": 0,
    }
    flagged = 0
    audited_at = _utc_now()

    for offset in range(0, len(pending), MAX_MERGE_PROPOSALS):
        batch = pending[offset: offset + MAX_MERGE_PROPOSALS]
        preview = preview_merge_proposals(owner, batch)
        preview_rows = preview.get("rows") or []
        for index, row in enumerate(batch):
            pid = row.get("id")
            if not pid:
                continue
            preview_row = preview_rows[index] if index < len(preview_rows) else {}
            audit_status = _audit_status_from_preview(preview_row.get("status"))
            errors = list(preview_row.get("errors") or [])
            warnings = list(preview_row.get("warnings") or [])
            summary[audit_status] = summary.get(audit_status, 0) + 1
            if audit_status in _FLAGGED_STATUSES:
                flagged += 1
            updates[pid] = {
                "audit_status": audit_status,
                "audit_errors": errors,
                "audit_warnings": warnings,
                "audited_at": audited_at,
                "audit_flagged": audit_status in _FLAGGED_STATUSES,
            }

    changed = False
    for row in pending:
        pid = row.get("id")
        if pid not in updates:
            continue
        upd = updates[pid]
        row["audit_status"] = upd["audit_status"]
        row["audit_errors"] = upd["audit_errors"]
        row["audit_warnings"] = upd["audit_warnings"]
        row["audited_at"] = upd["audited_at"]
        if upd["audit_flagged"]:
            row["audit_flagged"] = True
        else:
            row.pop("audit_flagged", None)
        changed = True

    if changed:
        save_pending_edges(owner, pending)

    parts = [f"audited {len(pending)} pending connection(s)"]
    if flagged:
        parts.append(f"{flagged} need attention")
    else:
        parts.append("no conflicts or missing nodes")

    return {
        "ok": True,
        "audited": len(pending),
        "flagged": flagged,
        "summary": summary,
        "message": "; ".join(parts).capitalize(),
    }
