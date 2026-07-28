"""Zotero integration routes — per-user credentials, library search, export."""

import json
import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Body, HTTPException, Query, Request
from pydantic import BaseModel, Field

from src.auth_helpers import get_current_user, require_privilege
from src.zotero_client import (
    ZoteroClient,
    fetch_zotero_findings,
    mask_api_key,
    resolve_zotero_credentials,
)
from src.zotero_catalog import (
    catalog_stats,
    clear_zotero_catalog,
    load_collections,
    sync_zotero_catalog,
)

logger = logging.getLogger(__name__)

RESEARCH_DATA_DIR = Path("data/deep_research")


class ZoteroConfigRequest(BaseModel):
    user_id: str = ""
    api_key: str = ""
    include_in_research: bool = True


class ZoteroExportRequest(BaseModel):
    session_id: str


def setup_zotero_routes() -> APIRouter:
    router = APIRouter(prefix="/api/zotero", tags=["zotero"])

    def _owner(request: Request) -> str:
        user = get_current_user(request)
        if not user:
            raise HTTPException(401, "Not authenticated")
        return user

    def _load_user_zotero(owner: str) -> dict:
        from routes.prefs_routes import _load_for_user
        return dict((_load_for_user(owner) or {}).get("zotero") or {})

    def _save_user_zotero(owner: str, zotero_cfg: dict):
        from routes.prefs_routes import _load_for_user, _save_for_user
        prefs = dict(_load_for_user(owner) or {})
        if zotero_cfg:
            prefs["zotero"] = zotero_cfg
        else:
            prefs.pop("zotero", None)
        _save_for_user(owner, prefs)

    @router.get("/config")
    async def get_config(request: Request):
        owner = _owner(request)
        cfg = _load_user_zotero(owner)
        has_key = bool((cfg.get("api_key") or "").strip())
        stats = catalog_stats(owner)
        return {
            "configured": has_key and bool((cfg.get("user_id") or "").strip()),
            "user_id": (cfg.get("user_id") or "").strip(),
            "api_key_masked": mask_api_key(cfg.get("api_key") or ""),
            "has_api_key": has_key,
            "include_in_research": cfg.get("include_in_research", True),
            "catalog": stats,
        }

    @router.post("/config")
    async def save_config(body: ZoteroConfigRequest, request: Request):
        owner = _owner(request)
        existing = _load_user_zotero(owner)
        cfg = dict(existing)
        uid = (body.user_id or "").strip()
        if uid:
            cfg["user_id"] = uid
        key = (body.api_key or "").strip()
        if key:
            cfg["api_key"] = key
        elif not cfg.get("api_key"):
            raise HTTPException(400, "API key is required")
        if not (cfg.get("user_id") or "").strip():
            raise HTTPException(400, "User ID is required")
        cfg["include_in_research"] = bool(body.include_in_research)
        _save_user_zotero(owner, cfg)
        sync_note = ""
        try:
            result = sync_zotero_catalog(owner)
            if result.get("ok"):
                sync_note = f" Catalog synced ({result.get('items', 0)} items)."
        except Exception as e:
            logger.warning(f"Zotero catalog sync after save failed: {e}")
        return {
            "ok": True,
            "user_id": cfg["user_id"],
            "api_key_masked": mask_api_key(cfg.get("api_key") or ""),
            "include_in_research": cfg["include_in_research"],
            "message": f"Saved.{sync_note}",
            "catalog": catalog_stats(owner),
        }

    @router.post("/config/clear")
    async def clear_config(request: Request):
        owner = _owner(request)
        _save_user_zotero(owner, {})
        clear_zotero_catalog(owner)
        try:
            from src.knowledge_sync import after_zotero_sync
            after_zotero_sync(owner)
        except Exception:
            pass
        return {"ok": True}

    @router.post("/test")
    async def test_connection(
        request: Request,
        body: ZoteroConfigRequest = Body(default_factory=ZoteroConfigRequest),
    ):
        owner = _owner(request)
        uid = (body.user_id or "").strip()
        key = (body.api_key or "").strip()
        if uid and key:
            creds = {"api_key": key, "user_id": uid}
        else:
            creds = resolve_zotero_credentials(owner)
        if not creds:
            raise HTTPException(
                400,
                "Zotero not configured — enter your User ID and API key, then click Save or Test",
            )
        client = ZoteroClient(creds["api_key"], creds["user_id"])
        ok, message, info = client.test_connection()
        if not ok:
            raise HTTPException(400, message)
        sync_result = sync_zotero_catalog(owner)
        items = client.search_items("", limit=3, seed_library=True)
        sample_titles = [
            (i.get("data") or {}).get("title") or "Untitled"
            for i in items[:3]
        ]
        return {
            "ok": True,
            "message": message,
            "library_sample": len(items),
            "sample_titles": sample_titles,
            "info": info,
            "catalog": catalog_stats(owner),
            "sync": sync_result,
        }

    @router.get("/catalog")
    async def get_catalog_status(request: Request):
        owner = _owner(request)
        creds = resolve_zotero_credentials(owner)
        if not creds:
            raise HTTPException(400, "Zotero not configured")
        return {"ok": True, "catalog": catalog_stats(owner)}

    @router.post("/sync")
    async def sync_catalog(request: Request):
        owner = _owner(request)
        creds = resolve_zotero_credentials(owner)
        if not creds:
            raise HTTPException(400, "Zotero not configured — save credentials first")
        result = sync_zotero_catalog(owner)
        if not result.get("ok"):
            raise HTTPException(400, result.get("error") or "Sync failed")
        return {
            "ok": True,
            "items": result.get("items", 0),
            "collections": result.get("collections", 0),
            "synced_at": result.get("synced_at"),
            "catalog": catalog_stats(owner),
        }

    @router.get("/items")
    async def search_library(
        request: Request,
        q: str = Query(""),
        limit: int = Query(10, ge=1, le=25),
    ):
        owner = _owner(request)
        creds = resolve_zotero_credentials(owner)
        if not creds:
            raise HTTPException(400, "Zotero not configured")
        client = ZoteroClient(creds["api_key"], creds["user_id"])
        items = client.search_items(q, limit=limit)
        simplified = []
        for item in items:
            data = item.get("data") or {}
            simplified.append({
                "key": item.get("key"),
                "title": data.get("title"),
                "itemType": data.get("itemType"),
                "date": data.get("date"),
                "DOI": data.get("DOI"),
            })
        return {"items": simplified, "count": len(simplified)}

    @router.get("/collections")
    async def list_collections(request: Request):
        """List Zotero collections for destination pickers (catalog-first)."""
        owner = _owner(request)
        creds = resolve_zotero_credentials(owner)
        if not creds:
            raise HTTPException(400, "Zotero not configured")
        cols = load_collections(owner)
        source = "catalog"
        if not cols:
            client = ZoteroClient(creds["api_key"], creds["user_id"])
            cols = client.list_collections()
            source = "live"

        by_key = { (c.get("key") or "").strip(): c for c in cols if (c.get("key") or "").strip() }

        def _display_path(col: dict) -> str:
            """Prefer catalog path; else rebuild Parent/Child from parent links."""
            existing = (col.get("path") or "").strip()
            # Catalog paths use " / "; normalize to dir/subdir for the picker.
            if existing and " / " in existing:
                return "/".join(part.strip() for part in existing.split("/") if part.strip())
            if existing and "/" in existing and existing != (col.get("name") or "").strip():
                return "/".join(part.strip() for part in existing.split("/") if part.strip())
            if existing and existing != (col.get("name") or "").strip():
                return existing

            parts = []
            current = col
            seen = set()
            while current:
                key = (current.get("key") or "").strip()
                if not key or key in seen:
                    break
                seen.add(key)
                parts.insert(0, (current.get("name") or "Untitled").strip())
                parent = (current.get("parent") or "").strip()
                current = by_key.get(parent) if parent else None
            return "/".join(parts) if parts else (col.get("name") or "Untitled").strip()

        simplified = []
        for col in cols:
            key = (col.get("key") or "").strip()
            if not key:
                continue
            path = _display_path(col)
            name = (col.get("name") or "Untitled").strip()
            depth = path.count("/") if path else 0
            simplified.append({
                "key": key,
                "name": name,
                "path": path,
                "depth": depth,
            })
        simplified.sort(key=lambda c: (c.get("path") or "").lower())
        return {
            "collections": simplified,
            "count": len(simplified),
            "source": source,
        }

    @router.post("/export")
    async def export_research_sources(body: ZoteroExportRequest, request: Request):
        """Create Zotero items from a completed research session's sources."""
        owner = require_privilege(request, "can_use_research")
        creds = resolve_zotero_credentials(owner)
        if not creds:
            raise HTTPException(400, "Zotero not configured")

        path = RESEARCH_DATA_DIR / f"{body.session_id}.json"
        if not path.exists():
            raise HTTPException(404, "Research not found")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            raise HTTPException(404, "Research not found")
        if data.get("owner") != owner:
            raise HTTPException(404, "Research not found")

        from src.research_zotero_save import save_research_sources_to_zotero

        client = ZoteroClient(creds["api_key"], creds["user_id"])
        result = save_research_sources_to_zotero(data, client, scope="cited")
        if not result.get("ok"):
            raise HTTPException(502, f"Zotero export failed: {result.get('error')}")
        if result.get("attempted", 0) == 0:
            raise HTTPException(400, "No exportable sources in this research")
        if result.get("created", 0) > 0:
            try:
                sync_zotero_catalog(owner)
            except Exception:
                logger.warning("Catalog sync after Zotero export failed", exc_info=True)
        return {
            "ok": True,
            "created": result.get("created", 0),
            "attempted": result.get("attempted", 0),
            "skipped_in_library": result.get("skipped_in_library", 0),
        }

    return router
