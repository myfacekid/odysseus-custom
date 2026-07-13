"""Create LDR academic search engines with Odysseus settings (Phase L1 Tier B)."""
from __future__ import annotations

import logging
from typing import Any, Optional

from src.research_engines.settings_bridge import build_ldr_settings_snapshot

logger = logging.getLogger(__name__)


def ldr_engines_available() -> bool:
    try:
        from local_deep_research.web_search_engines.search_engine_factory import (  # noqa: F401
            create_search_engine,
        )

        return True
    except ImportError:
        return False


def create_academic_engine(
    engine_name: str,
    *,
    llm=None,
    max_results: int = 10,
    include_preprints: bool = True,
    programmatic_mode: bool = True,
    settings_snapshot: Optional[dict] = None,
):
    """Instantiate an LDR ``BaseSearchEngine`` for *engine_name*."""
    if not ldr_engines_available():
        raise RuntimeError(
            "local-deep-research is not installed; "
            "pip install -r requirements-optional-ldr.txt"
        )

    from local_deep_research.web_search_engines.search_engine_factory import (
        create_search_engine,
    )

    snapshot = settings_snapshot or build_ldr_settings_snapshot(
        include_preprints=include_preprints,
        extra_overrides={
            f"search.engine.web.{engine_name}.default_params.max_results": max_results,
        },
    )
    engine = create_search_engine(
        engine_name,
        llm=llm,
        settings_snapshot=snapshot,
        programmatic_mode=programmatic_mode,
        max_results=max_results,
    )
    if engine is None:
        raise RuntimeError(f"LDR could not create search engine: {engine_name}")
    return engine


def close_engine(engine: Any) -> None:
    """Best-effort cleanup for a created engine."""
    if engine is None:
        return
    try:
        engine.close()
    except Exception:
        logger.debug("Engine close failed", exc_info=True)
    try:
        from local_deep_research.utilities.resource_utils import safe_close

        safe_close(engine, "search engine")
    except Exception:
        pass
