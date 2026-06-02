"""Obsidian vault path settings and connectivity test."""

import logging
import os

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from src.auth_helpers import get_current_user
from src.obsidian_vault import (
    DEFAULT_DAILY_NOTES_FOLDER,
    DEFAULT_VAULT_PATH,
    VaultConfig,
    resolve_vault_config,
    test_vault_connection,
)

logger = logging.getLogger(__name__)


class ObsidianVaultConfigRequest(BaseModel):
    vault_path: str = ""
    daily_notes_folder: str = Field(default=DEFAULT_DAILY_NOTES_FOLDER)
    daily_note_format: str = Field(default="%Y-%m-%d.md")


def setup_obsidian_vault_routes() -> APIRouter:
    router = APIRouter(prefix="/api/obsidian-vault", tags=["obsidian-vault"])

    def _owner(request: Request) -> str:
        user = get_current_user(request)
        if not user:
            raise HTTPException(401, "Not authenticated")
        return user

    def _load_user_cfg(owner: str) -> dict:
        from routes.prefs_routes import _load_for_user

        return dict((_load_for_user(owner) or {}).get("obsidian_vault") or {})

    def _save_user_cfg(owner: str, cfg: dict):
        from routes.prefs_routes import _load_for_user, _save_for_user

        prefs = dict(_load_for_user(owner) or {})
        if cfg:
            prefs["obsidian_vault"] = cfg
        else:
            prefs.pop("obsidian_vault", None)
        _save_for_user(owner, prefs)

    @router.get("/config")
    async def get_config(request: Request):
        owner = _owner(request)
        cfg = _load_user_cfg(owner)
        resolved = resolve_vault_config(owner)
        vault_path = (cfg.get("vault_path") or "").strip() or DEFAULT_VAULT_PATH
        expanded = os.path.expanduser(vault_path)
        return {
            "configured": resolved is not None,
            "vault_path": vault_path,
            "vault_path_expanded": expanded,
            "daily_notes_folder": (cfg.get("daily_notes_folder") or DEFAULT_DAILY_NOTES_FOLDER),
            "daily_note_format": (cfg.get("daily_note_format") or "%Y-%m-%d.md"),
            "exists": os.path.isdir(expanded),
        }

    @router.post("/config")
    async def save_config(body: ObsidianVaultConfigRequest, request: Request):
        owner = _owner(request)
        path = (body.vault_path or "").strip()
        if not path:
            raise HTTPException(400, "Vault path is required")
        expanded = os.path.expanduser(path)
        if not os.path.isdir(expanded):
            raise HTTPException(400, f"Folder not found: {expanded}")
        cfg = {
            "vault_path": path,
            "daily_notes_folder": (body.daily_notes_folder or DEFAULT_DAILY_NOTES_FOLDER).strip()
            or DEFAULT_DAILY_NOTES_FOLDER,
            "daily_note_format": (body.daily_note_format or "%Y-%m-%d.md").strip() or "%Y-%m-%d.md",
        }
        _save_user_cfg(owner, cfg)
        resolved = resolve_vault_config(owner)
        return {
            "ok": True,
            "configured": resolved is not None,
            "vault_path": cfg["vault_path"],
            "vault_path_expanded": expanded,
            "daily_notes_folder": cfg["daily_notes_folder"],
        }

    @router.post("/config/clear")
    async def clear_config(request: Request):
        owner = _owner(request)
        _save_user_cfg(owner, {})
        return {"ok": True}

    @router.post("/test")
    async def test_config(body: ObsidianVaultConfigRequest, request: Request):
        owner = _owner(request)
        path = (body.vault_path or "").strip()
        if path:
            expanded = os.path.expanduser(path)
            if not os.path.isdir(expanded):
                raise HTTPException(400, f"Folder not found: {expanded}")
            config = VaultConfig(
                vault_path=expanded,
                daily_notes_folder=(body.daily_notes_folder or DEFAULT_DAILY_NOTES_FOLDER).strip()
                or DEFAULT_DAILY_NOTES_FOLDER,
            )
        else:
            config = resolve_vault_config(owner)
            if not config:
                raise HTTPException(400, "Vault path not configured")
        ok, message, info = test_vault_connection(config)
        if not ok:
            raise HTTPException(400, message)
        return {"ok": True, "message": message, "info": info or {}}

    @router.post("/reindex")
    async def reindex_vault(request: Request):
        owner = _owner(request)
        config = resolve_vault_config(owner)
        if not config:
            raise HTTPException(400, "Vault path not configured")
        from src.obsidian_vault import reindex_vault_semantic

        result = reindex_vault_semantic(config, owner=owner)
        if not result.get("success"):
            raise HTTPException(503, result.get("message", "Reindex failed"))
        return {"ok": True, **result}

    return router
