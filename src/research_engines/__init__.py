"""Academic search engine registry and Nobody ↔ LDR bridge (Phase L1)."""

from src.research_engines.keyword_search import (
    build_seed_search_queries,
    keyword_search_findings,
)
from src.research_engines.ldr_factory import create_academic_engine, ldr_engines_available
from src.research_engines.registry import (
    ACADEMIC_ENGINE_NAMES,
    DEFAULT_SIMILAR_ENGINES,
    nobody_web_to_ldr_tool,
)

__all__ = [
    "ACADEMIC_ENGINE_NAMES",
    "DEFAULT_SIMILAR_ENGINES",
    "build_seed_search_queries",
    "create_academic_engine",
    "keyword_search_findings",
    "ldr_engines_available",
    "nobody_web_to_ldr_tool",
]
