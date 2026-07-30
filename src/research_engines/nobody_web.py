"""Bridge Nobody ``services/search`` to research finding dicts (Phase L1 Tier A)."""
from __future__ import annotations

import logging
from typing import List, Optional

logger = logging.getLogger(__name__)


def search_via_nobody_web(
    query: str,
    *,
    search_provider: Optional[str] = None,
    count: int = 10,
    search_kind: str = "discovery",
) -> List[dict]:
    """Run a web search through the shared Nobody provider layer."""
    from src.research_web_search import annotate_search_results, research_web_search

    try:
        outcome = research_web_search(
            query,
            search_kind=search_kind,
            provider_override=search_provider,
            count=count,
        )
    except Exception as e:
        logger.info("Nobody web search failed for %r: %s", query[:80], e)
        return []

    if outcome.error and not outcome.results:
        logger.info("Nobody web search error: %s", outcome.error)
        return []

    annotated = annotate_search_results(outcome.results, outcome)
    findings: List[dict] = []
    for row in annotated:
        url = (row.get("url") or row.get("link") or "").strip()
        if not url:
            continue
        title = (row.get("title") or "Untitled").strip()
        snippet = (row.get("content") or row.get("snippet") or "")[:2000]
        findings.append(
            {
                "url": url,
                "title": title,
                "rational": f"Web search ({outcome.provider or 'web'})",
                "evidence": snippet[:15000],
                "summary": snippet[:800],
                "source_type": "web",
                "search_provider": outcome.provider or "web",
                "search_query": query,
            }
        )
    return findings
