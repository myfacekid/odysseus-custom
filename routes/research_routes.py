"""Research background task routes — /api/research/*."""

import asyncio
import json
import logging
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, Response, StreamingResponse
from pydantic import BaseModel, Field
from src.endpoint_resolver import resolve_endpoint
from src.auth_helpers import _auth_disabled, get_current_user

_SESSION_ID_RE = re.compile(r"^[a-zA-Z0-9-]{1,128}$")

logger = logging.getLogger(__name__)

# Model-name substrings that are NOT chat/generation models — research must
# never pick these as its model. An OpenAI-style endpoint often lists
# `text-embedding-ada-002` etc. first in its model list, which is why research
# was failing with "Cannot reach model 'text-embedding-ada-002'".
_NON_CHAT_MODEL = (
    "text-embedding", "embedding", "tts-", "whisper", "dall-e",
    "moderation", "rerank", "reranker", "clip", "stable-diffusion",
)


def _first_chat_model(models) -> str:
    """First model that isn't an embedding/tts/etc. — falls back to models[0]."""
    for m in (models or []):
        if not any(p in str(m).lower() for p in _NON_CHAT_MODEL):
            return m
    return (models[0] if models else "")


def _resolve_research_endpoint(sess) -> tuple:
    """Return (endpoint_url, model, headers) for Deep Research, checking admin overrides."""
    url, model, headers = resolve_endpoint(
        "research",
        fallback_url=sess.endpoint_url,
        fallback_model=sess.model,
        fallback_headers=sess.headers,
    )
    return url, model, headers


def setup_research_routes(research_handler, session_manager=None) -> APIRouter:
    router = APIRouter(tags=["research"])

    def _require_user(request: Request) -> str:
        """All research endpoints require an authenticated user. Research
        data isn't owner-scoped in the on-disk JSON yet, so we at least
        block anonymous access. Multi-tenant deploys should additionally
        verify the session belongs to this user."""
        user = get_current_user(request)
        if not user:
            if _auth_disabled():
                return ""
            raise HTTPException(401, "Not authenticated")
        return user

    def _validate_session_id(session_id: str) -> None:
        if not _SESSION_ID_RE.fullmatch(session_id):
            raise HTTPException(400, "Invalid session ID format")

    def _owns_in_memory(session_id: str, user: str) -> bool:
        """Ownership check for an in-flight (in-memory) research task.
        Falls back to the on-disk JSON if the task has already finished."""
        entry = research_handler._active_tasks.get(session_id)
        if entry is not None:
            return entry.get("owner", "") == user
        # Task no longer in memory — check the persisted JSON.
        path = Path("data/deep_research") / f"{session_id}.json"
        if not path.exists():
            return False
        try:
            return json.loads(path.read_text(encoding="utf-8")).get("owner") == user
        except Exception:
            return False

    @router.get("/api/research/active")
    async def research_active(request: Request):
        """List all currently active (running) research tasks."""
        user = _require_user(request)
        active = []
        for sid, entry in research_handler._active_tasks.items():
            # SECURITY: only show this user's running tasks.
            if entry.get("owner", "") != user:
                continue
            if entry.get("status") == "running":
                active.append({
                    "session_id": sid,
                    "query": entry.get("query", ""),
                    "status": "running",
                    "progress": entry.get("progress", {}),
                    "started_at": entry.get("started_at", 0),
                })
        return {"active": active}

    @router.get("/api/research/status/{session_id}")
    async def research_status(session_id: str, request: Request):
        user = _require_user(request)
        _validate_session_id(session_id)
        if not _owns_in_memory(session_id, user):
            raise HTTPException(404, "No research found for this session")
        status = research_handler.get_status(session_id)
        if status is None:
            raise HTTPException(404, "No research found for this session")
        return status

    @router.post("/api/research/cancel/{session_id}")
    async def research_cancel(session_id: str, request: Request):
        user = _require_user(request)
        _validate_session_id(session_id)
        if not _owns_in_memory(session_id, user):
            raise HTTPException(404, "No research found for this session")
        cancelled = research_handler.cancel_research(session_id)
        return {"cancelled": cancelled}

    @router.post("/api/research/result/{session_id}")
    async def research_result(session_id: str, request: Request):
        user = _require_user(request)
        _validate_session_id(session_id)
        if not _owns_in_memory(session_id, user):
            raise HTTPException(404, "No research result available")
        result = research_handler.get_result(session_id)
        if result is None:
            raise HTTPException(404, "No research result available")
        sources = research_handler.get_sources(session_id) or []
        raw_findings = research_handler.get_raw_findings(session_id) or []
        research_handler.clear_result(session_id)
        return {"result": result, "sources": sources, "raw_findings": raw_findings}

    def _assert_owns_research(session_id: str, user: str) -> None:
        """404-not-403 ownership gate for a research session's on-disk JSON.
        Use BEFORE returning any data or mutating the file."""
        path = Path("data/deep_research") / f"{session_id}.json"
        if not path.exists():
            raise HTTPException(404, "Research not found")
        try:
            owner = json.loads(path.read_text(encoding="utf-8")).get("owner")
        except Exception:
            raise HTTPException(404, "Research not found")
        if owner != user:
            raise HTTPException(404, "Research not found")

    @router.get("/api/research/report/{session_id}")
    async def research_report(session_id: str, request: Request):
        """Serve the visual HTML report for a completed research session."""
        user = _require_user(request)
        _validate_session_id(session_id)
        _assert_owns_research(session_id, user)
        logger.info(f"Visual report requested for session {session_id}")
        try:
            html_content = research_handler.get_report_html(session_id)
        except Exception as e:
            logger.error(f"Visual report generation error: {e}", exc_info=True)
            raise HTTPException(500, f"Report generation failed: {e}")
        if html_content is None:
            logger.warning(f"No report data found for session {session_id}")
            raise HTTPException(404, "No visual report available for this session")
        return HTMLResponse(content=html_content)

    @router.get("/api/research/{session_id}/export")
    async def research_export(
        session_id: str,
        request: Request,
        format: str = Query("markdown", alias="format"),
        scope: str = Query("cited"),
    ):
        """Export a completed research session as Markdown, BibTeX, or CSL JSON."""
        user = _require_user(request)
        _validate_session_id(session_id)
        _assert_owns_research(session_id, user)
        try:
            content, media_type, filename = research_handler.export_research(
                session_id,
                format,
                scope=scope,
            )
        except FileNotFoundError:
            raise HTTPException(404, "Research not found")
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return Response(
            content=content,
            media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    class SaveToZoteroRequest(BaseModel):
        citation_nums: Optional[List[int]] = None
        scope: str = "cited"
        collection_key: Optional[str] = None

    @router.get("/api/research/{session_id}/save-to-zotero/preview")
    async def research_save_to_zotero_preview(
        session_id: str,
        request: Request,
        scope: str = Query("cited"),
    ):
        """List registry sources that can be saved to Zotero vs already in library."""
        from src.auth_helpers import require_privilege

        user = require_privilege(request, "can_use_research")
        _validate_session_id(session_id)
        _assert_owns_research(session_id, user)
        try:
            preview = research_handler.preview_save_to_zotero(session_id, scope=scope)
        except FileNotFoundError:
            raise HTTPException(404, "Research not found")
        return preview

    @router.post("/api/research/{session_id}/save-to-zotero")
    async def research_save_to_zotero(
        session_id: str,
        body: SaveToZoteroRequest,
        request: Request,
    ):
        """Batch-save selected research sources to the user's Zotero library."""
        from src.auth_helpers import require_privilege
        from src.zotero_catalog import sync_zotero_catalog

        user = require_privilege(request, "can_use_research")
        _validate_session_id(session_id)
        _assert_owns_research(session_id, user)
        try:
            result = research_handler.save_to_zotero(
                session_id,
                scope=body.scope or "cited",
                citation_nums=body.citation_nums,
                collection_key=body.collection_key,
            )
        except FileNotFoundError:
            raise HTTPException(404, "Research not found")
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        if not result.get("ok"):
            raise HTTPException(502, result.get("error") or "Zotero save failed")
        if result.get("created", 0) > 0:
            try:
                sync_zotero_catalog(user)
            except Exception:
                logger.warning("Catalog sync after Zotero save failed", exc_info=True)
        return result

    class HideImageRequest(BaseModel):
        url: str

    @router.post("/api/research/{session_id}/hide-image")
    async def research_hide_image(session_id: str, body: HideImageRequest, request: Request):
        """Mark an image URL as hidden for this research's visual report.
        Persisted to the research JSON so subsequent /report renders skip it."""
        user = _require_user(request)
        _validate_session_id(session_id)
        _assert_owns_research(session_id, user)
        ok = research_handler.hide_image(session_id, body.url)
        if not ok:
            raise HTTPException(404, "Research not found")
        return {"ok": True}

    @router.post("/api/research/{session_id}/unhide-images")
    async def research_unhide_images(session_id: str, request: Request):
        """Clear the hidden-images list for a research session."""
        user = _require_user(request)
        _validate_session_id(session_id)
        _assert_owns_research(session_id, user)
        ok = research_handler.unhide_all_images(session_id)
        if not ok:
            raise HTTPException(404, "Research not found")
        return {"ok": True}

    @router.get("/api/research/library")
    async def research_library(
        request: Request,
        search: Optional[str] = Query(None),
        sort: str = Query("recent"),
        limit: int = Query(50),
        archived: bool = Query(False),
    ):
        user = _require_user(request)
        """List all completed research for the Library panel."""
        data_dir = Path("data/deep_research")
        items = []
        for p in data_dir.glob("*.json"):
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
                # SECURITY: only show research belonging to this user. Legacy
                # JSONs without an `owner` field are hidden — auth was the only
                # gate before, so every user saw every other user's reports.
                if d.get("owner") != user:
                    continue
                # Archived view shows ONLY archived reports; default hides them.
                if bool(d.get("archived")) != archived:
                    continue
                query = d.get("query", "")
                if search and search.lower() not in query.lower():
                    continue
                sources = d.get("sources", [])
                seed_papers = d.get("seed_papers") or []
                breakdown = d.get("source_breakdown") or {}
                if not breakdown and d.get("evidence_registry"):
                    try:
                        from src.research_graph import compute_source_breakdown
                        breakdown = compute_source_breakdown(d)
                    except Exception:
                        breakdown = {}
                items.append({
                    "id": p.stem,
                    "query": query,
                    "category": d.get("category") or "",
                    "source_count": len(sources),
                    "source_breakdown": breakdown,
                    "seed_count": len(seed_papers),
                    "research_mode": d.get("research_mode") or "literature_review",
                    "status": d.get("status", "done"),
                    "duration": d.get("stats", {}).get("Duration", ""),
                    "rounds": d.get("stats", {}).get("Rounds", ""),
                    "started_at": d.get("started_at", 0),
                    "completed_at": d.get("completed_at", 0),
                    "archived": bool(d.get("archived")),
                })
            except Exception:
                continue

        # Sort
        if sort == "recent":
            items.sort(key=lambda x: x["completed_at"] or 0, reverse=True)
        elif sort == "oldest":
            items.sort(key=lambda x: x["completed_at"] or 0)
        elif sort == "most-messages":
            items.sort(key=lambda x: x["source_count"], reverse=True)
        elif sort == "alpha":
            items.sort(key=lambda x: x["query"].lower())

        return {"research": items[:limit], "total": len(items)}

    @router.get("/api/research/detail/{session_id}")
    async def research_detail(session_id: str, request: Request):
        """Return the full JSON for a single research result — sources,
        summary, stats — used by the Library preview panel."""
        user = _require_user(request)
        _validate_session_id(session_id)
        path = Path("data/deep_research") / f"{session_id}.json"
        if not path.exists():
            raise HTTPException(404, "Research not found")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            raise HTTPException(500, f"Failed to read research: {e}")
        # SECURITY: 404 (not 403) so we don't leak that the report exists.
        if data.get("owner") != user:
            raise HTTPException(404, "Research not found")
        return data

    @router.post("/api/research/{session_id}/archive")
    async def research_archive(session_id: str, request: Request, archived: bool = Query(True)):
        """Soft-archive / restore a research report (sets `archived` in its JSON)."""
        user = _require_user(request)
        _validate_session_id(session_id)
        path = Path("data/deep_research") / f"{session_id}.json"
        if not path.exists():
            raise HTTPException(404, "Research not found")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("owner") != user:
                raise HTTPException(404, "Research not found")
            data["archived"] = bool(archived)
            path.write_text(json.dumps(data), encoding="utf-8")
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(500, f"Failed to update research: {e}")
        return {"ok": True, "id": session_id, "archived": bool(archived)}

    @router.delete("/api/research/{session_id}")
    async def research_delete(session_id: str, request: Request):
        """Delete a research result from disk."""
        user = _require_user(request)
        _validate_session_id(session_id)
        data_dir = Path("data/deep_research")
        json_path = data_dir / f"{session_id}.json"
        deleted = False
        if json_path.exists():
            # SECURITY: verify ownership before letting the caller delete it.
            try:
                data = json.loads(json_path.read_text(encoding="utf-8"))
                if data.get("owner") != user:
                    raise HTTPException(404, "Research not found")
            except HTTPException:
                raise
            except Exception:
                raise HTTPException(404, "Research not found")
            json_path.unlink()
            deleted = True
        return {"deleted": deleted}

    # ------------------------------------------------------------------
    # Panel endpoints — launch research without a chat session
    # ------------------------------------------------------------------

    class ResearchStartRequest(BaseModel):
        query: str
        # max_rounds=0 means "Auto" — let the AI decide when to stop, capped at 20.
        max_rounds: int = Field(default=0, ge=0, le=20)
        search_provider: Optional[str] = None
        endpoint_id: Optional[str] = None
        model: Optional[str] = None
        max_time: int = Field(default=300, ge=60, le=1800)
        extraction_timeout: Optional[int] = Field(default=None, ge=15, le=3600)
        extraction_concurrency: Optional[int] = Field(default=None, ge=1, le=12)
        include_preprints: bool = True
        include_zotero: bool = True
        include_knowledge: bool = True
        seed_papers: List[str] = Field(default_factory=list)
        mode: str = Field(default="literature_review")
        report_length: str = Field(default="standard")
        category: Optional[str] = None  # ignored — always academic
        project_id: Optional[str] = Field(default=None, max_length=128)
        approved_plan: Optional[dict] = None

    class ResearchPlanRequest(BaseModel):
        query: str
        endpoint_id: Optional[str] = None
        model: Optional[str] = None
        seed_papers: List[str] = Field(default_factory=list)
        mode: str = Field(default="literature_review")
        include_zotero: bool = True

    def _resolve_panel_llm(endpoint_id: Optional[str], model_override: Optional[str]):
        if endpoint_id:
            from src.database import SessionLocal
            from src.database import ModelEndpoint
            from src.endpoint_resolver import normalize_base, build_chat_url, build_headers

            db = SessionLocal()
            try:
                ep = db.query(ModelEndpoint).filter(
                    ModelEndpoint.id == endpoint_id,
                    ModelEndpoint.is_enabled == True,
                ).first()
                if not ep:
                    raise HTTPException(404, "Endpoint not found or disabled")
                base = normalize_base(ep.base_url)
                ep_url = build_chat_url(base)
                ep_headers = build_headers(ep.api_key, base)
                ep_model = model_override or ""
                if not ep_model:
                    try:
                        models = json.loads(ep.cached_models) if ep.cached_models else []
                        if models:
                            ep_model = _first_chat_model(models)
                    except Exception:
                        pass
                return ep_url, ep_model, ep_headers
            finally:
                db.close()
        ep_url, ep_model, ep_headers = resolve_endpoint("research")
        if not ep_url:
            ep_url, ep_model, ep_headers = resolve_endpoint("utility")
        if not ep_url:
            ep_url, ep_model, ep_headers = resolve_endpoint("default")
        if not ep_url:
            ep_url, ep_model, ep_headers = resolve_endpoint("chat")
        if not ep_url:
            from src.database import SessionLocal
            from src.database import ModelEndpoint
            from src.endpoint_resolver import normalize_base, build_chat_url, build_headers

            db = SessionLocal()
            try:
                ep = db.query(ModelEndpoint).filter(ModelEndpoint.is_enabled == True).first()
                if ep:
                    base = normalize_base(ep.base_url)
                    ep_url = build_chat_url(base)
                    ep_headers = build_headers(ep.api_key, base)
                    ep_model = ""
                    if ep.cached_models:
                        try:
                            models = json.loads(ep.cached_models)
                            if models:
                                ep_model = _first_chat_model(models)
                        except Exception:
                            pass
                else:
                    ep_url, ep_model, ep_headers = "", "", {}
            finally:
                db.close()
        if model_override:
            ep_model = model_override
        if not ep_url:
            raise HTTPException(400, "No endpoints configured. Add one in Settings first.")
        return ep_url, ep_model, ep_headers

    @router.post("/api/research/plan")
    async def research_plan(body: ResearchPlanRequest, request: Request):
        """Generate a structured retrieval plan for user review before starting."""
        from src.auth_helpers import require_privilege

        user = require_privilege(request, "can_use_research")
        if user == "internal-tool":
            tool_owner = (request.headers.get("X-Odysseus-Owner") or "").strip()
            if tool_owner and tool_owner not in {"internal-tool", "api", "demo", "system"}:
                user = tool_owner
        query = (body.query or "").strip()
        seed_papers = [s.strip() for s in (body.seed_papers or []) if (s or "").strip()]
        mode = (body.mode or "literature_review").strip().lower()
        allowed_modes = {"literature_review", "similar_papers", "gap_analysis", "compare"}
        if mode not in allowed_modes:
            raise HTTPException(400, f"mode must be one of: {', '.join(sorted(allowed_modes))}")
        if not query and not seed_papers:
            raise HTTPException(400, "query or seed_papers required")
        if not query:
            query = "Literature synthesis from selected seed papers."

        ep_url, ep_model, ep_headers = _resolve_panel_llm(body.endpoint_id, body.model)
        plan_payload = await research_handler.generate_research_plan(
            query,
            ep_url,
            ep_model,
            ep_headers,
            owner=user,
            seed_papers=seed_papers,
            research_mode=mode,
            include_zotero=body.include_zotero,
        )
        if not plan_payload:
            raise HTTPException(502, "Plan generation failed")
        return {
            "query": query,
            "mode": mode,
            **plan_payload,
        }

    @router.post("/api/research/start")
    async def research_start(body: ResearchStartRequest, request: Request):
        """Launch a research job from the dedicated panel."""
        from src.auth_helpers import require_privilege
        user = require_privilege(request, "can_use_research")
        if user == "internal-tool":
            tool_owner = (request.headers.get("X-Odysseus-Owner") or "").strip()
            if tool_owner and tool_owner not in {"internal-tool", "api", "demo", "system"}:
                auth_mgr = getattr(request.app.state, "auth_manager", None)
                if auth_mgr is not None and getattr(auth_mgr, "is_configured", False):
                    try:
                        privs = auth_mgr.get_privileges(tool_owner) or {}
                        if not privs.get("can_use_research", True):
                            raise HTTPException(403, f"Your account is not allowed to can use research.")
                    except HTTPException:
                        raise
                    except Exception:
                        pass
                user = tool_owner
        session_id = f"rp-{uuid.uuid4().hex[:12]}"

        ep_url, ep_model, ep_headers = _resolve_panel_llm(body.endpoint_id, body.model)

        # max_rounds=0 → "Auto", let AI decide; pass 20 as the safety cap.
        effective_max_rounds = body.max_rounds if body.max_rounds > 0 else 20
        mode = (body.mode or "literature_review").strip().lower()
        allowed_modes = {"literature_review", "similar_papers", "gap_analysis", "compare"}
        if mode not in allowed_modes:
            raise HTTPException(400, f"mode must be one of: {', '.join(sorted(allowed_modes))}")
        report_length = (body.report_length or "standard").strip().lower()
        if report_length not in ("standard", "extended"):
            raise HTTPException(400, "report_length must be standard or extended")
        seed_papers = [s.strip() for s in (body.seed_papers or []) if (s or "").strip()]
        if mode == "compare" and len(seed_papers) < 2:
            raise HTTPException(400, "Compare mode requires at least 2 seed papers")
        if seed_papers and not (body.query or "").strip():
            body.query = "Literature synthesis from selected seed papers."

        project_id = (body.project_id or "").strip() or None
        if project_id:
            from src.project_workspace import (
                ProjectAccessError,
                ProjectNotFoundError,
                assert_project_owner,
            )

            try:
                assert_project_owner(user, project_id)
            except ProjectNotFoundError:
                raise HTTPException(404, "Project not found")
            except ProjectAccessError:
                raise HTTPException(404, "Project not found")

        research_handler.start_research(
            session_id=session_id,
            query=body.query,
            llm_endpoint=ep_url,
            llm_model=ep_model,
            max_time=body.max_time,
            llm_headers=ep_headers,
            max_rounds=effective_max_rounds,
            search_provider=body.search_provider or None,
            category="academic",
            extraction_timeout=body.extraction_timeout,
            extraction_concurrency=body.extraction_concurrency,
            include_preprints=body.include_preprints,
            include_zotero=body.include_zotero,
            include_knowledge=body.include_knowledge,
            owner=user,
            seed_papers=seed_papers,
            research_mode=mode,
            report_length=report_length,
            project_id=project_id,
            approved_plan=body.approved_plan,
        )
        return {
            "session_id": session_id,
            "status": "running",
            "query": body.query,
            "mode": mode,
            "seed_papers": seed_papers,
            "project_id": project_id,
        }

    @router.get("/api/research/papers")
    async def research_papers(
        request: Request,
        search: str = Query("", max_length=200),
        limit: int = Query(30, ge=1, le=100),
    ):
        """Browse synced catalog papers for the seed-paper picker."""
        from src.auth_helpers import require_privilege
        from src.zotero_catalog import library_items_from_catalog, search_catalog

        user = require_privilege(request, "can_use_research")
        if user == "internal-tool":
            tool_owner = (request.headers.get("X-Odysseus-Owner") or "").strip()
            if tool_owner and tool_owner not in {"internal-tool", "api", "demo", "system"}:
                user = tool_owner
        q = (search or "").strip()
        if q:
            rows = search_catalog(user, q, limit=limit)
            papers = [
                {
                    "zotero_key": r.get("zotero_key"),
                    "title": r.get("title") or "Untitled",
                    "authors": r.get("authors") or "",
                    "year": r.get("year") or "",
                    "doi": r.get("doi") or "",
                    "has_pdf": bool(r.get("has_pdf")),
                    "collection_paths": r.get("collection_paths") or [],
                }
                for r in rows
            ]
        else:
            items = library_items_from_catalog(user, search="")
            papers = [
                {
                    "zotero_key": p.get("zotero_key") or p.get("id", "").replace("paper:", ""),
                    "title": p.get("title") or "Untitled",
                    "authors": p.get("authors") or "",
                    "year": p.get("year") or "",
                    "doi": p.get("doi") or "",
                    "has_pdf": bool(p.get("has_pdf")),
                    "collection_paths": p.get("collection_paths") or [],
                }
                for p in items[:limit]
            ]
        return {"papers": papers, "total": len(papers)}

    class SeedPreviewRequest(BaseModel):
        refs: List[str] = Field(default_factory=list)

    @router.post("/api/research/seeds/preview")
    async def research_seeds_preview(body: SeedPreviewRequest, request: Request):
        """Catalog-based sourcing preview for seed papers before a run."""
        from src.auth_helpers import require_privilege
        from src.research_seeds import preview_seed_refs

        user = require_privilege(request, "can_use_research")
        if user == "internal-tool":
            tool_owner = (request.headers.get("X-Odysseus-Owner") or "").strip()
            if tool_owner and tool_owner not in {"internal-tool", "api", "demo", "system"}:
                user = tool_owner
        refs = [r.strip() for r in (body.refs or []) if (r or "").strip()]
        if not refs:
            return {"seeds": [], "sync_recommended": False}
        seeds = preview_seed_refs(user, refs)
        return {
            "seeds": seeds,
            "sync_recommended": any(s.get("catalog_stale") for s in seeds),
        }

    @router.get("/api/research/stream/{session_id}")
    async def research_stream(session_id: str, request: Request):
        """SSE stream of research progress events."""
        user = _require_user(request)
        _validate_session_id(session_id)
        if not _owns_in_memory(session_id, user):
            raise HTTPException(404, "No research found for this session")
        async def _generate():
            last_progress = None
            while True:
                status = research_handler.get_status(session_id)
                if status is None:
                    yield f"data: {json.dumps({'status': 'not_found'})}\n\n"
                    return
                st = status.get("status", "")
                progress = status.get("progress", {})
                if progress != last_progress:
                    last_progress = progress
                    yield f"data: {json.dumps({**progress, 'status': st})}\n\n"
                if st != "running":
                    final = {'status': st, 'final': True}
                    task = research_handler._active_tasks.get(session_id, {})
                    if st == "error" and task.get("result"):
                        final['error'] = str(task["result"])[:500]
                    hook = task.get("graph_connection_proposals")
                    if hook and hook.get("proposal_count"):
                        final["graph_connection_proposals"] = hook
                    yield f"data: {json.dumps(final)}\n\n"
                    return
                await asyncio.sleep(1.5)

        return StreamingResponse(
            _generate(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @router.post("/api/research/result-peek/{session_id}")
    async def research_result_peek(session_id: str, request: Request):
        """Get research result without clearing it (for panel use)."""
        user = _require_user(request)
        _validate_session_id(session_id)
        if not _owns_in_memory(session_id, user):
            raise HTTPException(404, "No research found for this session")
        result = research_handler.get_result(session_id)
        if result is None:
            p = Path("data/deep_research") / f"{session_id}.json"
            if p.exists():
                d = json.loads(p.read_text(encoding="utf-8"))
                payload = {
                    "result": d.get("raw_report") or d.get("result", ""),
                    "sources": d.get("sources", []),
                    "raw_findings": d.get("raw_findings", []),
                    "category": d.get("category") or "",
                    "evidence_registry": d.get("evidence_registry") or {},
                    "raw_report": d.get("raw_report") or "",
                    "verification": d.get("verification"),
                }
                hook = d.get("graph_connection_proposals")
                if hook:
                    payload["graph_connection_proposals"] = hook
                return payload
            raise HTTPException(404, "No research result available")
        sources = research_handler.get_sources(session_id) or []
        raw_findings = research_handler.get_raw_findings(session_id) or []
        task = research_handler._active_tasks.get(session_id, {})
        _researcher = task.get("researcher")
        payload = {
            "result": result,
            "sources": sources,
            "raw_findings": raw_findings,
            "category": "",
            "verification": (
                getattr(_researcher, "verification_summary", None)
                if _researcher else task.get("verification")
            ),
        }
        hook = task.get("graph_connection_proposals")
        if hook:
            payload["graph_connection_proposals"] = hook
        return payload

    @router.post("/api/research/spinoff/{session_id}")
    async def research_spinoff(session_id: str, request: Request):
        """Create a new chat session pre-seeded with this research as context.

        Reads the persisted research result + per-source summaries for
        `session_id`, creates a fresh session, and injects a system message
        so the user can ask follow-up questions in a clean conversation.
        """
        user = _require_user(request)
        _validate_session_id(session_id)
        # SECURITY: gate on ownership before reading the persisted research —
        # otherwise any authenticated user could spin off (and thereby read)
        # another user's report by guessing its session ID. Mirrors every other
        # endpoint in this file (see result_peek above).
        if not _owns_in_memory(session_id, user):
            raise HTTPException(404, "No research found for this session")
        if session_manager is None:
            raise HTTPException(500, "session_manager not configured")

        path = Path("data/deep_research") / f"{session_id}.json"
        disk: dict = {}
        if path.exists():
            try:
                disk = json.loads(path.read_text(encoding="utf-8"))
                if disk.get("owner") and disk.get("owner") != user:
                    raise HTTPException(404, "Research not found")
            except HTTPException:
                raise
            except Exception as e:
                logger.warning(f"Could not read research JSON for spinoff: {e}")

        result = research_handler.get_result(session_id)
        if not result:
            result = disk.get("result") or disk.get("raw_report") or ""
        sources = research_handler.get_sources(session_id) or disk.get("sources") or []
        raw_findings = research_handler.get_raw_findings(session_id) or disk.get("raw_findings") or []
        query = disk.get("query", "") or ""
        evidence_registry = disk.get("evidence_registry") or {}

        if not (result or "").strip():
            raise HTTPException(404, "No research result available for this session")

        def _registry_context_block() -> str:
            sources = (evidence_registry or {}).get("sources") or []
            if not sources:
                return ""
            lines = ["\n\n=== EVIDENCE REGISTRY (cite using these [N] numbers) ==="]
            for src in sorted(sources, key=lambda s: int((s or {}).get("citation_num") or 0)):
                if not isinstance(src, dict):
                    continue
                num = src.get("citation_num")
                title = (src.get("title") or "Untitled").strip()
                url = (src.get("url") or "").strip()
                doi = (src.get("doi_or_id") or "").strip()
                tier = (src.get("sourcing_tier") or "").strip()
                seed_note = " seed" if src.get("is_seed") else ""
                block = f"\n[{num}]{seed_note} {title}"
                if doi.startswith("10."):
                    block += f"\nDOI: {doi}"
                elif doi:
                    block += f"\nID: {doi}"
                if url:
                    block += f"\nURL: {url}"
                if tier:
                    block += f"\nSourcing: {tier}"
                lines.append(block)
            return "".join(lines)

        # Inherit endpoint/model/headers from the source session when possible.
        # For panel-launched research (rp-* IDs), there is no chat session, so
        # fall back through the same chain as /api/research/start: research →
        # utility → first enabled endpoint in the DB.
        ep_url, ep_model, ep_headers = "", "", {}
        try:
            src_sess = session_manager.get_session(session_id)
            ep_url = src_sess.endpoint_url or ""
            ep_model = src_sess.model or ""
            ep_headers = dict(src_sess.headers or {})
        except KeyError:
            pass

        def _merge(r_url, r_model, r_headers):
            nonlocal ep_url, ep_model, ep_headers
            if not ep_url and r_url:
                ep_url = r_url
            if not ep_model and r_model:
                ep_model = r_model
            if not ep_headers and r_headers:
                ep_headers = dict(r_headers)

        if not ep_url or not ep_model:
            _merge(*resolve_endpoint("chat"))
        if not ep_url or not ep_model:
            _merge(*resolve_endpoint("research"))
        if not ep_url or not ep_model:
            _merge(*resolve_endpoint("utility"))
        if not ep_url or not ep_model:
            # Last resort: any enabled endpoint
            from src.database import SessionLocal
            from src.database import ModelEndpoint
            from src.endpoint_resolver import normalize_base, build_chat_url, build_headers
            db = SessionLocal()
            try:
                ep = db.query(ModelEndpoint).filter(ModelEndpoint.is_enabled == True).first()
                if ep:
                    base = normalize_base(ep.base_url)
                    fallback_url = build_chat_url(base)
                    fallback_headers = build_headers(ep.api_key, base)
                    fallback_model = ""
                    if ep.cached_models:
                        try:
                            models = json.loads(ep.cached_models)
                            if models:
                                fallback_model = models[0]
                        except Exception:
                            pass
                    _merge(fallback_url, fallback_model, fallback_headers)
            finally:
                db.close()

        if not ep_url or not ep_model:
            raise HTTPException(400, "No endpoint configured — add one in Settings first")

        # Create new session
        new_sid = str(uuid.uuid4())

        title_query = (query or "research").strip()
        if len(title_query) > 60:
            title_query = title_query[:57] + "…"
        new_name = f"Follow-up: {title_query}"

        new_sess = session_manager.create_session(
            session_id=new_sid,
            name=new_name,
            endpoint_url=ep_url,
            model=ep_model,
            rag=False,
            owner=user,
        )
        if ep_headers:
            new_sess.headers = ep_headers
            session_manager.save_sessions()
        try:
            from src.event_bus import fire_event
            fire_event("session_created", user)
        except Exception:
            logger.debug("session_created event dispatch failed", exc_info=True)

        # Build the priming system message — synthesized report plus per-source
        # summaries so follow-up chat can cite specific evidence, not just the
        # high-level write-up shown in the UI.
        date_str = datetime.utcnow().strftime("%Y-%m-%d")
        primer = (
            f"[Research context — {date_str}]\n\n"
            f"The user previously ran a deep research investigation. Use the "
            f"report and source summaries below as your primary knowledge base "
            f"when answering follow-up questions. If the user asks something "
            f"not covered, say so plainly rather than guessing.\n\n"
            f"=== ORIGINAL QUERY ===\n{query or '(not recorded)'}\n\n"
            f"=== REPORT ===\n{result}"
        )
        registry_block = _registry_context_block()
        if registry_block:
            primer += registry_block
        elif raw_findings:
            lines = ["\n\n=== SOURCE SUMMARIES ==="]
            for i, finding in enumerate(raw_findings[:25], 1):
                title = (finding.get("title") or "Untitled").strip()
                summary = (finding.get("summary") or "").strip()
                url = (finding.get("url") or "").strip()
                block = f"\n[{i}] {title}"
                if url:
                    block += f"\nURL: {url}"
                if summary:
                    block += f"\n{summary[:2000]}"
                lines.append(block)
            primer += "".join(lines)

        from core.models import ChatMessage
        new_sess.add_message(ChatMessage(
            role="system",
            content=primer,
            metadata={"research_spinoff_from": session_id},
        ))
        session_manager.save_sessions()

        return {
            "session_id": new_sid,
            "name": new_name,
            "source_count": len(sources),
        }

    return router
