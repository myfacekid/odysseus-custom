"""Map Odysseus admin settings into LDR settings snapshots (Phase L1)."""
from __future__ import annotations

import os
from typing import Any, Dict, Optional


def _odysseus_settings() -> dict:
    try:
        from src.settings import load_settings

        return load_settings() or {}
    except Exception:
        return {}


def academic_engine_overrides(*, include_preprints: bool = True) -> Dict[str, Any]:
    """LDR snapshot overrides for academic engines using Odysseus admin keys."""
    settings = _odysseus_settings()
    overrides: Dict[str, Any] = {}

    email = (settings.get("openalex_email") or os.environ.get("OPENALEX_EMAIL") or "").strip()
    if email:
        overrides["search.engine.web.openalex.email"] = email

    s2_key = (
        settings.get("semantic_scholar_api_key")
        or os.environ.get("SEMANTIC_SCHOLAR_API_KEY")
        or ""
    ).strip()
    if s2_key:
        overrides["search.engine.web.semantic_scholar.api_key"] = s2_key

    if not include_preprints:
        overrides["search.engine.web.arxiv.default_params.include_preprints"] = False

    return overrides


def web_search_overrides(search_provider: Optional[str] = None) -> Dict[str, Any]:
    """LDR snapshot overrides for Odysseus web search provider + API keys."""
    from src.research_engines.registry import odysseus_web_to_ldr_tool

    settings = _odysseus_settings()
    tool = odysseus_web_to_ldr_tool(search_provider or settings.get("research_search_provider"))
    overrides: Dict[str, Any] = {"search.tool": tool}

    key_map = {
        "brave": ("search.engine.web.brave.api_key", "brave_api_key", "DATA_BRAVE_API_KEY"),
        "tavily": ("search.engine.web.tavily.api_key", "tavily_api_key", "TAVILY_API_KEY"),
        "serper": ("search.engine.web.serper.api_key", "serper_api_key", "SERPER_API_KEY"),
        "google_pse": ("search.engine.web.google_pse.api_key", "google_pse_key", "GOOGLE_API_KEY"),
    }
    if tool in key_map:
        ldr_key, setting_key, env_key = key_map[tool]
        val = (settings.get(setting_key) or os.environ.get(env_key) or "").strip()
        if val:
            overrides[ldr_key] = val

    searx_url = (settings.get("search_url") or os.environ.get("SEARXNG_INSTANCE") or "").strip()
    if searx_url and tool == "searxng":
        overrides["search.engine.web.searxng.instance_url"] = searx_url.rstrip("/")

    return overrides


def build_ldr_settings_snapshot(
    *,
    search_provider: Optional[str] = None,
    include_preprints: bool = True,
    extra_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Full LDR settings snapshot with Odysseus keys wired in."""
    from local_deep_research.api.settings_utils import create_settings_snapshot

    overrides: Dict[str, Any] = {}
    overrides.update(academic_engine_overrides(include_preprints=include_preprints))
    overrides.update(web_search_overrides(search_provider))
    if extra_overrides:
        overrides.update(extra_overrides)
    return create_settings_snapshot(overrides)
