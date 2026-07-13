"""Feature detection for the Local Deep Research optional stack."""
from __future__ import annotations

import logging
from typing import Literal

logger = logging.getLogger(__name__)

ResearchEngineMode = Literal["iterresearch", "ldr"]
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

    Default is LDR. When ``research_engine=ldr`` but the optional stack is not
    installed (e.g. Python 3.14 without wheels), falls back to IterResearch.
    """
    from src.settings import get_setting

    raw = (get_setting("research_engine", DEFAULT_RESEARCH_ENGINE) or DEFAULT_RESEARCH_ENGINE).strip().lower()
    if raw == "iterresearch":
        return "iterresearch"
    if raw == "ldr":
        if ldr_stack_available():
            return "ldr"
        logger.warning(
            "research_engine=ldr but local-deep-research is not installed; "
            "using iterresearch. Install: pip install -r requirements-optional-ldr.txt "
            "(Python 3.12–3.13)."
        )
        return "iterresearch"
    logger.warning("Unknown research_engine=%r; using iterresearch", raw)
    return "iterresearch"
