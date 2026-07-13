"""Shared graph edge proposal coercion (L3 anti-sprawl).

Single parser for pending queue rows and merge preview batches.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from src.edge_taxonomy import EDGE_OPTIONAL_FIELDS, PIPELINE_EDGE_KINDS, normalize_semantic_kind

PROPOSAL_EXTRA_FIELDS = (
    "evidence",
    "section_ref",
    "project_id",
    "from_title",
    "to_title",
    "source_session",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def normalize_proposal_kind(kind: Optional[str], *, default: str = "relates") -> str:
    k = (kind or "").strip().lower()
    if k in PIPELINE_EDGE_KINDS:
        return k
    return normalize_semantic_kind(kind, default=default)


def _proposal_id(index: int, fr: str, to: str, kind: str) -> str:
    return f"p{index}-{fr}|{to}|{kind}"


def coerce_graph_proposal(
    raw: Any,
    *,
    source: str = "agent",
    index: Optional[int] = None,
) -> Optional[dict]:
    """Normalize a proposal dict for merge preview or pending enqueue."""
    if not isinstance(raw, dict):
        return None
    fr = (raw.get("from") or raw.get("from_id") or raw.get("source") or "").strip()
    to = (raw.get("to") or raw.get("to_id") or raw.get("target") or "").strip()
    if not fr or not to or fr == to:
        return None
    kind = normalize_proposal_kind(raw.get("kind") or "relates")
    reason = (raw.get("reason") or raw.get("why") or "").strip()[:280]
    try:
        confidence = float(raw.get("confidence")) if raw.get("confidence") is not None else None
    except (TypeError, ValueError):
        confidence = None
    pid = (raw.get("proposal_id") or raw.get("id") or "").strip()
    if not pid and index is not None:
        pid = _proposal_id(index, fr, to, kind)
    row: Dict[str, Any] = {
        "from": fr,
        "to": to,
        "kind": kind,
        "reason": reason,
        "confidence": confidence,
        "source": (raw.get("source") or source or "agent").strip() or "agent",
        "source_session": (raw.get("source_session") or raw.get("session_id") or "").strip(),
        "from_title": (raw.get("from_title") or "").strip(),
        "to_title": (raw.get("to_title") or "").strip(),
    }
    if pid:
        row["proposal_id"] = pid
        row["id"] = pid
    skip_meta = {"reason", "confidence"}
    for key in EDGE_OPTIONAL_FIELDS:
        if key in skip_meta:
            continue
        val = raw.get(key)
        if val is not None and val != "":
            row[key] = val
    for key in PROPOSAL_EXTRA_FIELDS:
        if key in row:
            continue
        val = raw.get(key)
        if val is not None and val != "":
            row[key] = val
    return row


def coerce_pending_proposal(raw: Any, source: str = "agent") -> Optional[dict]:
    """Pending inbox row with id, status, and timestamps."""
    row = coerce_graph_proposal(raw, source=source)
    if not row:
        return None
    row["id"] = (raw.get("id") or raw.get("proposal_id") or row.get("id") or str(uuid.uuid4())).strip()
    row["status"] = raw.get("status") or "pending"
    row["created_at"] = raw.get("created_at") or _utc_now()
    return row
