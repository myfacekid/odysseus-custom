"""Knowledge graph API — search, browse links, rebuild."""

import logging
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from src.auth_helpers import get_current_user
from src.knowledge_graph import (
    add_graph_link,
    execute_knowledge_tool,
    get_neighbors,
    get_node,
    list_graph_summary,
    parse_node_id,
    read_knowledge_content,
    rebuild_owner_graph,
    remove_graph_link,
    schedule_rebuild,
    search_knowledge,
)
from src.paper_retrieval import (
    NON_PAPER_READ_DEFAULT_MAX_CHARS,
    PAPER_READ_DEFAULT_INCLUDE_PDF,
    PAPER_READ_DEFAULT_MAX_CHARS,
    PAPER_SECTION_DEFAULT_MAX_CHARS,
)

logger = logging.getLogger(__name__)


class KnowledgeSearchRequest(BaseModel):
    query: str = ""
    types: Optional[List[str]] = None
    limit: int = Field(default=20, ge=1, le=50)
    expand_hops: int = Field(default=1, ge=0, le=2)


class GraphLinkCreate(BaseModel):
    from_id: str = Field(..., min_length=1)
    to_id: str = Field(..., min_length=1)
    kind: str = Field(default="relates")
    reason: Optional[str] = Field(default=None, max_length=280)
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)


class GraphLinkRemove(BaseModel):
    from_id: str = Field(..., min_length=1)
    to_id: str = Field(..., min_length=1)
    kind: Optional[str] = None


class MergePreviewRequest(BaseModel):
    proposals: List[dict] = Field(default_factory=list)


class MergeApplyRequest(BaseModel):
    accepted: List[dict] = Field(default_factory=list)


class PendingEnqueueRequest(BaseModel):
    proposals: List[dict] = Field(default_factory=list)
    source: str = Field(default="agent")
    project_id: Optional[str] = None


class ComparePapersRequest(BaseModel):
    paper_keys: List[str] = Field(default_factory=list)
    focus: str = Field(default="methods")
    question: str = Field(default="")


class PendingRejectRequest(BaseModel):
    from_id: Optional[str] = Field(default=None, alias="from")
    to_id: Optional[str] = Field(default=None, alias="to")
    kind: str = Field(default="relates")
    id: Optional[str] = None
    proposal_id: Optional[str] = None

    class Config:
        populate_by_name = True


class PendingAcceptBatchRequest(BaseModel):
    proposals: List[dict] = Field(default_factory=list)


class PendingRejectBatchRequest(BaseModel):
    proposals: List[dict] = Field(default_factory=list)


def setup_knowledge_routes() -> APIRouter:
    router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])

    def _owner(request: Request) -> str:
        user = get_current_user(request)
        if not user:
            raise HTTPException(401, "Not authenticated")
        return user

    @router.get("/graph")
    def graph_summary(request: Request, type: Optional[str] = None, limit: int = 200):
        owner = _owner(request)
        return list_graph_summary(owner, type_filter=type, limit=min(limit, 500))

    @router.get("/search")
    def search(request: Request, q: str = "", types: Optional[str] = None, limit: int = 20, expand_hops: int = 1):
        owner = _owner(request)
        type_list = [t.strip() for t in types.split(",")] if types else None
        return search_knowledge(
            owner,
            query=q,
            types=type_list,
            limit=limit,
            expand_hops=expand_hops,
        )

    @router.post("/search")
    def search_post(body: KnowledgeSearchRequest, request: Request):
        owner = _owner(request)
        return search_knowledge(
            owner,
            query=body.query,
            types=body.types,
            limit=body.limit,
            expand_hops=body.expand_hops,
        )

    @router.get("/nodes/{node_id:path}")
    def get_node_route(node_id: str, request: Request):
        owner = _owner(request)
        node = get_node(owner, node_id)
        if not node:
            raise HTTPException(404, "Node not found")
        return {"node": node}

    @router.get("/neighbors")
    def neighbors_query(request: Request, id: str = Query(..., min_length=1)):
        """Resolve links by node id — query param avoids path encoding issues with ``document:vault:…`` ids."""
        owner = _owner(request)
        result = get_neighbors(owner, id)
        if not result.get("node"):
            raise HTTPException(404, "Node not found")
        return result

    @router.get("/nodes/{node_id:path}/neighbors")
    def neighbors_route(node_id: str, request: Request):
        owner = _owner(request)
        result = get_neighbors(owner, node_id)
        if not result.get("node"):
            raise HTTPException(404, "Node not found")
        return result

    @router.get("/content")
    def content_query(
        request: Request,
        id: str = Query(..., min_length=1),
        max_chars: Optional[int] = Query(None),
        include_pdf: Optional[bool] = Query(None),
        section: Optional[str] = Query(None),
    ):
        owner = _owner(request)
        ntype, _ = parse_node_id(id)
        is_paper = ntype == "paper"
        section_q = (section or "").strip()
        if max_chars is not None:
            cap = max_chars
        elif is_paper and section_q:
            cap = PAPER_SECTION_DEFAULT_MAX_CHARS
        else:
            cap = PAPER_READ_DEFAULT_MAX_CHARS if is_paper else NON_PAPER_READ_DEFAULT_MAX_CHARS
        if include_pdf is not None:
            pdf = include_pdf
        elif section_q and is_paper:
            pdf = False
        else:
            pdf = PAPER_READ_DEFAULT_INCLUDE_PDF if is_paper else False
        out = read_knowledge_content(
            owner,
            id,
            max_chars=cap,
            include_pdf=pdf and is_paper and not section_q,
            section=section_q or None,
        )
        if out.get("exit_code") != 0:
            raise HTTPException(404, out.get("error") or "Not found")
        return out

    @router.get("/nodes/{node_id:path}/content")
    def content_route(
        node_id: str,
        request: Request,
        max_chars: Optional[int] = Query(None),
        include_pdf: Optional[bool] = Query(None),
        section: Optional[str] = Query(None),
    ):
        owner = _owner(request)
        ntype, _ = parse_node_id(node_id)
        is_paper = ntype == "paper"
        section_q = (section or "").strip()
        if max_chars is not None:
            cap = max_chars
        elif is_paper and section_q:
            cap = PAPER_SECTION_DEFAULT_MAX_CHARS
        else:
            cap = PAPER_READ_DEFAULT_MAX_CHARS if is_paper else NON_PAPER_READ_DEFAULT_MAX_CHARS
        if include_pdf is not None:
            pdf = include_pdf
        elif section_q and is_paper:
            pdf = False
        else:
            pdf = PAPER_READ_DEFAULT_INCLUDE_PDF if is_paper else False
        out = read_knowledge_content(
            owner,
            node_id,
            max_chars=cap,
            include_pdf=pdf and is_paper and not section_q,
            section=section_q or None,
        )
        if out.get("exit_code") != 0:
            raise HTTPException(404, out.get("error") or "Not found")
        return out

    @router.post("/links")
    def create_link(body: GraphLinkCreate, request: Request):
        owner = _owner(request)
        result = add_graph_link(
            owner,
            body.from_id,
            body.to_id,
            kind=body.kind,
            reason=body.reason or "",
            confidence=body.confidence,
            source="user",
        )
        if not result.get("ok"):
            raise HTTPException(400, result.get("error") or "Link failed")
        return result

    @router.delete("/links")
    def delete_link(
        request: Request,
        from_id: str = Query(..., min_length=1),
        to_id: str = Query(..., min_length=1),
        kind: Optional[str] = Query(None),
    ):
        owner = _owner(request)
        result = remove_graph_link(owner, from_id, to_id, kind=kind)
        if not result.get("ok"):
            raise HTTPException(404, result.get("error") or "Link not found")
        return result

    @router.post("/merge/preview")
    def merge_preview(body: MergePreviewRequest, request: Request):
        from src.graph_merge import preview_merge_proposals

        owner = _owner(request)
        result = preview_merge_proposals(owner, body.proposals)
        if not result.get("ok"):
            raise HTTPException(400, result.get("error") or "Preview failed")
        return result

    @router.post("/merge/apply")
    def merge_apply(body: MergeApplyRequest, request: Request):
        from src.graph_merge import apply_merge_proposals

        owner = _owner(request)
        rows = body.accepted
        result = apply_merge_proposals(owner, rows)
        if not result.get("ok"):
            raise HTTPException(400, result.get("error") or "Apply failed")
        return result

    @router.get("/pending")
    def list_pending(
        request: Request,
        project_id: Optional[str] = Query(None),
        kind: Optional[str] = Query(None),
        source: Optional[str] = Query(None),
        min_confidence: Optional[float] = Query(None, ge=0.0, le=1.0),
    ):
        from src.pending_graph_edges import filter_pending_for_project, load_pending_edges, pending_count

        owner = _owner(request)
        rows = load_pending_edges(owner)
        if project_id:
            rows = filter_pending_for_project(owner, project_id, rows)
        if kind:
            kind_l = kind.strip().lower()
            rows = [r for r in rows if (r.get("kind") or "").lower() == kind_l]
        if source:
            src_l = source.strip().lower()
            rows = [r for r in rows if (r.get("source") or "").lower() == src_l]
        if min_confidence is not None:
            rows = [
                r for r in rows
                if r.get("confidence") is not None and float(r.get("confidence")) >= min_confidence
            ]
        return {"ok": True, "rows": rows, "count": len(rows)}

    @router.post("/pending/enqueue")
    def enqueue_pending(body: PendingEnqueueRequest, request: Request):
        from src.pending_graph_edges import enqueue_proposals

        owner = _owner(request)
        proposals = list(body.proposals or [])
        if body.project_id:
            pid = body.project_id.strip()
            for row in proposals:
                if isinstance(row, dict) and not (row.get("project_id") or "").strip():
                    row["project_id"] = pid
        result = enqueue_proposals(
            owner,
            proposals,
            source=body.source or "agent",
            user_initiated=True,
        )
        if not result.get("ok"):
            raise HTTPException(400, result.get("error") or "Enqueue failed")
        return result

    @router.post("/compare-papers")
    def compare_papers_library(body: ComparePapersRequest, request: Request):
        """Library multi-select: sync compare ≤3 papers → suggested_edges for review pop-up."""
        from src.paper_compare import execute_compare_papers

        owner = _owner(request)
        result = execute_compare_papers(
            {
                "paper_keys": body.paper_keys,
                "focus": body.focus or "methods",
                "question": body.question or "",
            },
            owner=owner,
        )
        if result.get("exit_code") == 1:
            raise HTTPException(400, result.get("error") or "Compare failed")
        return {
            "ok": True,
            "defer_to_research": bool(result.get("defer_to_research")),
            "output": result.get("output") or "",
            "suggested_edges": result.get("suggested_edges") or [],
            "paper_keys": result.get("paper_keys") or body.paper_keys,
            "focus": result.get("focus") or body.focus,
        }

    @router.post("/pending/reject")
    def reject_pending(body: PendingRejectRequest, request: Request):
        from src.pending_graph_edges import load_pending_edges, reject_proposal

        owner = _owner(request)
        payload = body.model_dump(by_alias=True)
        pid = body.id or body.proposal_id
        if pid and not (body.from_id or payload.get("from")):
            row = next((r for r in load_pending_edges(owner) if r.get("id") == pid), None)
            if not row:
                raise HTTPException(404, "Proposal not found")
            payload = row
        result = reject_proposal(owner, payload)
        if not result.get("ok"):
            raise HTTPException(400, result.get("error") or "Reject failed")
        return result

    @router.post("/pending/reject-batch")
    def reject_pending_batch(body: PendingRejectBatchRequest, request: Request):
        from src.pending_graph_edges import reject_proposals

        owner = _owner(request)
        result = reject_proposals(owner, body.proposals)
        if not result.get("ok"):
            raise HTTPException(400, result.get("error") or "Reject failed")
        return result

    @router.post("/pending/accept-batch")
    def accept_pending_batch(body: PendingAcceptBatchRequest, request: Request):
        from src.pending_graph_edges import accept_proposals

        owner = _owner(request)
        result = accept_proposals(owner, body.proposals)
        if not result.get("ok"):
            raise HTTPException(400, result.get("error") or "Accept failed")
        return result

    @router.post("/pending/{proposal_id}/accept")
    def accept_pending(proposal_id: str, request: Request):
        from src.pending_graph_edges import accept_pending_edge

        owner = _owner(request)
        result = accept_pending_edge(owner, proposal_id)
        if not result.get("ok"):
            raise HTTPException(400, result.get("error") or "Accept failed")
        return result

    @router.delete("/pending/{proposal_id}")
    def delete_pending(proposal_id: str, request: Request):
        from src.pending_graph_edges import delete_pending_edge

        owner = _owner(request)
        result = delete_pending_edge(owner, proposal_id)
        if not result.get("ok"):
            raise HTTPException(404, result.get("error") or "Not found")
        return result

    @router.post("/rebuild")
    def rebuild(request: Request):
        owner = _owner(request)
        stats = rebuild_owner_graph(owner)
        if not stats.get("ok"):
            raise HTTPException(400, stats.get("error") or "Rebuild failed")
        return stats

    @router.post("/sync")
    def sync_debounced(request: Request):
        """Schedule a background rebuild (same as task/document hooks)."""
        owner = _owner(request)
        schedule_rebuild(owner)
        return {"ok": True, "scheduled": True}

    return router
