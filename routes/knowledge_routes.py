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
    read_knowledge_content,
    rebuild_owner_graph,
    remove_graph_link,
    schedule_rebuild,
    search_knowledge,
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
    kind: str = Field(default="link")


class GraphLinkRemove(BaseModel):
    from_id: str = Field(..., min_length=1)
    to_id: str = Field(..., min_length=1)
    kind: Optional[str] = None


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
    def content_query(request: Request, id: str = Query(..., min_length=1), max_chars: int = 12000):
        owner = _owner(request)
        out = read_knowledge_content(owner, id, max_chars=max_chars)
        if out.get("exit_code") != 0:
            raise HTTPException(404, out.get("error") or "Not found")
        return out

    @router.get("/nodes/{node_id:path}/content")
    def content_route(node_id: str, request: Request, max_chars: int = 12000):
        owner = _owner(request)
        out = read_knowledge_content(owner, node_id, max_chars=max_chars)
        if out.get("exit_code") != 0:
            raise HTTPException(404, out.get("error") or "Not found")
        return out

    @router.post("/links")
    def create_link(body: GraphLinkCreate, request: Request):
        owner = _owner(request)
        result = add_graph_link(owner, body.from_id, body.to_id, kind=body.kind)
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
