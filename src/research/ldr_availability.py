"""Feature detection for the Local Deep Research stack."""
from __future__ import annotations

import logging
from typing import Literal

logger = logging.getLogger(__name__)

ResearchEngineMode = Literal["ldr"]
DEFAULT_RESEARCH_ENGINE: ResearchEngineMode = "ldr"


def ldr_stack_available() -> bool:
    """True when local-deep-research and langgraph are importable."""
    try:
        import langgraph  # noqa: F401
        import local_deep_research  # noqa: F401
        return True
    except ImportError:
        return False


def research_engine_mode() -> ResearchEngineMode:
    """Resolved research backend from settings.

    Deep Research always uses LDR. Unknown or retired values (e.g. the former
    ``iterresearch`` setting) are ignored and LDR is used.
    """
    from src.settings import get_setting

    raw = (get_setting("research_engine", DEFAULT_RESEARCH_ENGINE) or DEFAULT_RESEARCH_ENGINE).strip().lower()
    if raw and raw != "ldr":
        logger.warning(
            "Unknown or retired research_engine=%r; using ldr "
            "(IterResearch has been removed)",
            raw,
        )
    return "ldr"
