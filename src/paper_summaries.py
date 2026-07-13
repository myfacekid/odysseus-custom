"""Paper summary notes from Deep Research (Paper Token Retrieval R2).

Creates Library documents linked to papers via ``summarizes`` pipeline edges.
See docs/paper-token-retrieval-roadmap_v1.md.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.paper_retrieval import PAPER_READ_DEFAULT_MAX_CHARS
from src.research_graph import _paper_id_from_registry_source

logger = logging.getLogger(__name__)

PAPER_SUMMARY_EDGE_KIND = "summarizes"
PAPER_SUMMARY_EDGE_SOURCE = "paper_summary_pipeline"
MAX_SUMMARY_PAPERS = 12
SUMMARY_BODY_MAX_CHARS = 2800


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _registry_by_paper_key(data: dict) -> Dict[str, dict]:
    registry = (data or {}).get("evidence_registry") or {}
    out: Dict[str, dict] = {}
    for src in registry.get("sources") or []:
        if not isinstance(src, dict):
            continue
        pid = _paper_id_from_registry_source(src)
        if not pid:
            continue
        key = pid.split(":", 1)[-1].upper()
        if key and key not in out:
            out[key] = src
    return out


def collect_papers_for_summary(data: dict, *, limit: int = MAX_SUMMARY_PAPERS) -> List[dict]:
    """Seed papers first, then other Zotero/graph papers from the evidence registry."""
    registry_map = _registry_by_paper_key(data)
    ordered: List[dict] = []
    seen: set[str] = set()

    def add(key: str, seed_meta: Optional[dict] = None) -> None:
        k = (key or "").strip().upper()
        if not k or k in seen:
            return
        seen.add(k)
        reg = registry_map.get(k) or {}
        seed = seed_meta or {}
        ordered.append({
            "zotero_key": k,
            "title": (seed.get("title") or reg.get("title") or "Untitled").strip(),
            "authors": (seed.get("authors") or reg.get("authors") or "").strip(),
            "year": str(seed.get("year") or reg.get("year") or "").strip(),
            "registry": reg,
            "is_seed": bool(seed_meta or reg.get("is_seed")),
        })

    for row in (data or {}).get("seed_paper_details") or []:
        if not isinstance(row, dict):
            continue
        add(row.get("zotero_key") or "", row)

    for ref in (data or {}).get("seed_papers") or []:
        raw = (ref or "").strip()
        if raw.lower().startswith("paper:"):
            add(raw.split(":", 1)[1])
        elif raw:
            add(raw)

    for key in registry_map:
        add(key)

    return ordered[: max(1, limit)]


def build_summary_markdown(
    paper: dict,
    *,
    session_id: str,
    research_query: str,
    generated_at: str,
) -> str:
    """Structured ~300-token summary for agent reads (markdown)."""
    key = paper.get("zotero_key") or "?"
    title = paper.get("title") or "Untitled"
    authors = paper.get("authors") or "Unknown"
    year = paper.get("year") or "n/a"
    reg = paper.get("registry") or {}

    claim = (reg.get("content_excerpt") or "").strip()
    method_bits = []
    if reg.get("study_type") and reg.get("study_type") != "unknown":
        method_bits.append(f"Study type: {reg['study_type']}")
    if reg.get("sample_size"):
        method_bits.append(f"Sample: {reg['sample_size']}")
    method = ". ".join(method_bits) if method_bits else "See excerpt below."

    results_bits = []
    if reg.get("effect_size"):
        results_bits.append(f"Effect: {reg['effect_size']}")
    if reg.get("outcome"):
        results_bits.append(f"Outcome: {reg['outcome']}")
    results = ". ".join(results_bits) if results_bits else (claim[:400] if claim else "Not extracted in this research pass.")

    assumptions = (reg.get("quality_notes") or reg.get("sourcing_note") or "").strip()
    if not assumptions and reg.get("sourcing_tier"):
        assumptions = f"Sourcing tier: {reg['sourcing_tier']}."

    query_line = (research_query or "").strip()
    lines = [
        f"# Paper summary — {title}",
        "",
        f"**Authors:** {authors} ({year})  ",
        f"**Zotero key:** `{key}`  ",
        f"**From research:** `{session_id}`  ",
        f"**Generated:** {generated_at}",
        "",
        "## Focus / claim",
        claim or f"Covered in research: {query_line[:400]}" if query_line else "_(No excerpt in evidence registry.)_",
        "",
        "## Method",
        method,
        "",
        "## Key results",
        results,
        "",
        "## Assumptions & limitations",
        assumptions or "Review original paper before high-stakes claims.",
    ]
    body = "\n".join(lines).strip()
    if len(body) > SUMMARY_BODY_MAX_CHARS:
        body = body[:SUMMARY_BODY_MAX_CHARS] + "\n… [summary truncated]"
    return body


def _summary_doc_title(paper_title: str) -> str:
    base = (paper_title or "Untitled").strip()
    return f"Summary — {base[:120]}"


def _upsert_summary_document(
    owner: str,
    *,
    document_id: Optional[str],
    title: str,
    body: str,
) -> str:
    from core.database import Document, DocumentVersion, SessionLocal

    db = SessionLocal()
    try:
        doc_id = (document_id or "").strip() or str(uuid.uuid4())
        doc = db.query(Document).filter(Document.id == doc_id, Document.owner == owner).first()
        if doc:
            doc.title = title
            doc.current_content = body
            doc.language = "markdown"
            doc.is_active = True
            doc.archived = False
            doc.version_count = (doc.version_count or 1) + 1
            ver = DocumentVersion(
                id=str(uuid.uuid4()),
                document_id=doc_id,
                version_number=doc.version_count,
                content=body,
                summary="Updated from Deep Research paper summary pipeline",
                source="research_summary",
            )
            db.add(ver)
        else:
            doc = Document(
                id=doc_id,
                session_id=None,
                title=title,
                language="markdown",
                current_content=body,
                version_count=1,
                is_active=True,
                owner=owner,
            )
            ver = DocumentVersion(
                id=str(uuid.uuid4()),
                document_id=doc_id,
                version_number=1,
                content=body,
                summary="Created from Deep Research paper summary pipeline",
                source="research_summary",
            )
            db.add(doc)
            db.add(ver)
        db.commit()
        return doc_id
    except Exception as exc:
        db.rollback()
        raise exc
    finally:
        db.close()


def load_cached_paper_summary_body(owner: str, zotero_key: str) -> Optional[dict]:
    """Return cached summary body for Tier 1.5 reads when a summarizes edge exists."""
    from src.knowledge_graph import find_pipeline_edge, node_id, parse_node_id

    key = (zotero_key or "").strip().upper()
    if not owner or not key:
        return None
    paper_id = node_id("paper", key)
    edge = find_pipeline_edge(
        owner,
        paper_id,
        kind=PAPER_SUMMARY_EDGE_KIND,
        source=PAPER_SUMMARY_EDGE_SOURCE,
    )
    if not edge:
        return None
    to_ref = (edge.get("to") or "").strip()
    ntype, doc_id = parse_node_id(to_ref)
    if ntype != "document" or not doc_id:
        return None
    from core.database import Document, SessionLocal

    db = SessionLocal()
    try:
        doc = db.query(Document).filter(Document.id == doc_id, Document.owner == owner).first()
        if not doc or not (doc.current_content or "").strip():
            return None
        body = (doc.current_content or "").strip()
        if len(body) > PAPER_READ_DEFAULT_MAX_CHARS:
            body = body[:PAPER_READ_DEFAULT_MAX_CHARS] + "\n… [summary truncated]"
        return {
            "document_id": doc_id,
            "title": doc.title,
            "body": body,
            "generated_at": edge.get("generated_at") or "",
            "research_session_id": edge.get("research_session_id") or "",
        }
    finally:
        db.close()


def sync_paper_summaries_on_complete(owner: str, session_id: str, data: dict) -> Dict[str, Any]:
    """Create or refresh paper summary documents; enqueue summarizes edges for review."""
    from src.knowledge_graph import find_pipeline_edge, node_id
    from src.learned_link_prefs import producer_enqueue_allowed
    from src.pending_graph_edges import enqueue_proposals

    owner = (owner or "").strip()
    session_id = (session_id or "").strip()
    if not owner or not session_id:
        return {"ok": False, "error": "owner and session_id required", "summaries": [], "proposals": []}

    generated_at = _utc_now_iso()
    query = ((data or {}).get("query") or "").strip()
    papers = collect_papers_for_summary(data)
    if not papers:
        return {"ok": True, "summaries": [], "proposals": [], "note": "No catalog papers to summarize"}

    created: List[dict] = []
    summary_proposals: List[dict] = []
    project_id = ((data or {}).get("project_id") or "").strip()
    for paper in papers:
        key = paper["zotero_key"]
        paper_id = node_id("paper", key)
        try:
            body = build_summary_markdown(
                paper,
                session_id=session_id,
                research_query=query,
                generated_at=generated_at,
            )
            title = _summary_doc_title(paper.get("title") or key)
            existing = find_pipeline_edge(
                owner,
                paper_id,
                kind=PAPER_SUMMARY_EDGE_KIND,
                source=PAPER_SUMMARY_EDGE_SOURCE,
            )
            existing_doc_id = None
            if existing:
                to_ref = (existing.get("to") or "").strip()
                if to_ref.startswith("document:"):
                    existing_doc_id = to_ref.split(":", 1)[1]

            doc_id = _upsert_summary_document(
                owner,
                document_id=existing_doc_id,
                title=title,
                body=body,
            )
            doc_node = node_id("document", doc_id)
            summary_proposals.append({
                "from": paper_id,
                "to": doc_node,
                "kind": PAPER_SUMMARY_EDGE_KIND,
                "source": PAPER_SUMMARY_EDGE_SOURCE,
                "source_session": session_id,
                "generated_at": generated_at,
                "research_session_id": session_id,
                "zotero_key": key,
                "reason": f"Summary note from Deep Research «{query[:80]}»" if query else "Summary note from Deep Research",
                "from_title": (paper.get("title") or key).strip(),
                "to_title": title,
                **({"project_id": project_id} if project_id else {}),
            })
            created.append({
                "zotero_key": key,
                "document_id": doc_id,
                "graph_node_id": doc_node,
                "replaced": bool(existing_doc_id),
            })
        except Exception as exc:
            logger.warning("Paper summary failed for %s: %s", key, exc)

    enqueue_out = (
        enqueue_proposals(owner, summary_proposals, source="research")
        if summary_proposals and producer_enqueue_allowed(owner)
        else {
            "ok": True,
            "added": 0,
            "skipped": len(summary_proposals),
            "rows": [],
            "gated": bool(summary_proposals and not producer_enqueue_allowed(owner)),
        }
    )

    if created:
        try:
            from src.knowledge_sync import after_document_change

            after_document_change(owner)
        except Exception:
            logger.debug("Knowledge rebuild after paper summaries failed", exc_info=True)

    rows = enqueue_out.get("rows") or []
    note = f"Paper summaries: {len(created)} document(s), {len(rows)} edge proposal(s)"
    logger.info("%s for research %s", note, session_id)
    return {
        "ok": True,
        "summaries": created,
        "proposals": rows,
        "proposal_count": len(rows),
        "note": note,
    }
