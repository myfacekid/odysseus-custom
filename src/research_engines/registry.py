"""Engine name registry for Deep Research (Tier A)."""
from __future__ import annotations

from typing import Dict, Tuple

# LDR config keys for academic keyword search (not co-citation recommenders).
ACADEMIC_ENGINE_NAMES: Tuple[str, ...] = (
    "openalex",
    "semantic_scholar",
    "pubmed",
    "arxiv",
    "crossref",
)

# IterResearch similar-paper fallback: keyword search on these engines.
DEFAULT_SIMILAR_ENGINES: Tuple[str, ...] = ("openalex", "semantic_scholar")

# Odysseus panel search_provider → LDR meta-search tool (web bridge).
ODY_WEB_TO_LDR: Dict[str, str] = {
    "searxng": "searxng",
    "brave": "brave",
    "tavily": "tavily",
    "duckduckgo": "duckduckgo",
    "google": "serper",
    "serper": "serper",
    "google_pse": "google_pse",
}


def odysseus_web_to_ldr_tool(search_provider: str | None) -> str:
    key = (search_provider or "searxng").strip().lower()
    return ODY_WEB_TO_LDR.get(key, key or "searxng")
