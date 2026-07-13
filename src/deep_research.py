# src/deep_research.py
"""
Deprecated import path for the legacy IterResearch engine.

Prefer:
- **LDR (default):** ``research_engine=ldr`` → ``src.research.ldr_runner``
- **IterResearch fallback:** ``src.research.iterresearch.DeepResearcher``
- **Shared prompts:** ``src.research.research_prompts``
"""
from src.research import iterresearch as _iterresearch

# Re-export public API for ``from src.deep_research import DeepResearcher`` etc.
DeepResearcher = _iterresearch.DeepResearcher
ACADEMIC_CATEGORY = _iterresearch.ACADEMIC_CATEGORY
filter_and_rank_academic_results = _iterresearch.filter_and_rank_academic_results
current_date_context = _iterresearch.current_date_context
RESEARCH_PLAN_PROMPT = _iterresearch.RESEARCH_PLAN_PROMPT
MODE_PLAN_CONTEXT = _iterresearch.MODE_PLAN_CONTEXT
REPORT_LENGTH_SPECS = _iterresearch.REPORT_LENGTH_SPECS


def __getattr__(name: str):
    """Lazy re-export (including private helpers used by legacy tests)."""
    return getattr(_iterresearch, name)


def __dir__():
    return sorted(set(dir(_iterresearch) + list(globals().keys())))
