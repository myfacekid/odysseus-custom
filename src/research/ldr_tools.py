"""Odysseus-only LangGraph tools for Zotero and Links knowledge."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class OdysseusAgentConfig:
    owner: str = ""
    include_zotero: bool = False
    include_knowledge: bool = False
    seed_findings: Optional[List[dict]] = None
    relevance_query: str = ""
    max_content_chars: int = 15000


def _format_odysseus_tool_results(results: List[dict], start_idx: int) -> str:
    lines = []
    for i, item in enumerate(results):
        if not isinstance(item, dict):
            continue
        idx = start_idx + i + 1
        title = item.get("title", "No title")
        link = item.get("url", "")
        snippet = (item.get("content") or item.get("snippet") or "")[:500]
        lines.append(f"[{idx}] {title} ({link})\n{snippet}")
    return "\n\n".join(lines) if lines else "No results."


def _findings_to_ldr_results(findings: List[dict]) -> List[dict]:
    out = []
    for f in findings:
        url = (f.get("url") or "").strip()
        if not url:
            continue
        out.append(
            {
                "title": f.get("title") or "Untitled",
                "link": url,
                "url": url,
                "snippet": (f.get("content") or "")[:2000],
                "source_engine": f.get("search_provider") or "odysseus",
                "zotero_key": f.get("zotero_key"),
                "paper_key": f.get("paper_key"),
                "doi": f.get("doi_or_id"),
                "authors": f.get("authors"),
                "year": f.get("year"),
            }
        )
    return out


def make_zotero_search_tool(collector, config: OdysseusAgentConfig):
    from langchain_core.tools import tool

    @tool
    def search_zotero(query: str) -> str:
        """Search the user's Zotero library for papers matching a keyword query."""
        from src.research_zotero import research_zotero_findings

        outcome = research_zotero_findings(
            query,
            config.owner,
            limit=5,
            extract_pdfs=False,
            seed_library=False,
            pdf_max_chars=config.max_content_chars,
        )
        results = _findings_to_ldr_results(outcome.findings)
        if not results:
            return outcome.note or f"No Zotero matches for '{query}'."
        start = collector.add_results(results, engine_name="zotero")
        return _format_odysseus_tool_results(results, start + 1)

    search_zotero.name = "search_zotero"
    search_zotero.description = (
        "Search the user's Zotero library by keyword. "
        "Use focused method/topic terms — not the full research question."
    )
    return search_zotero


def make_knowledge_search_tool(collector, config: OdysseusAgentConfig):
    from langchain_core.tools import tool

    @tool
    def search_knowledge(query: str) -> str:
        """Search the user's Links knowledge graph for relevant papers and notes."""
        from src.research_knowledge import research_knowledge_findings

        outcome = research_knowledge_findings(
            query,
            config.owner,
            seed_findings=config.seed_findings or [],
            limit=5,
            seed_graph=False,
            content_max_chars=config.max_content_chars,
            relevance_query=config.relevance_query or query,
        )
        results = _findings_to_ldr_results(outcome.findings)
        if not results:
            return outcome.note or f"No knowledge graph matches for '{query}'."
        start = collector.add_results(results, engine_name="knowledge")
        return _format_odysseus_tool_results(results, start + 1)

    search_knowledge.name = "search_knowledge"
    search_knowledge.description = (
        "Search the user's Links knowledge graph for papers, notes, and related nodes."
    )
    return search_knowledge


def attach_odysseus_tools(strategy, config: OdysseusAgentConfig) -> None:
    """Extend a LangGraphAgentStrategy with Odysseus Zotero/knowledge tools."""
    original_build: Callable = strategy._build_tools
    collector = strategy.collector

    def patched_build(overall_query: str = ""):
        tools = list(original_build(overall_query))
        if config.include_zotero and config.owner:
            tools.append(make_zotero_search_tool(collector, config))
        if config.include_knowledge and config.owner:
            tools.append(make_knowledge_search_tool(collector, config))
        return tools

    strategy._build_tools = patched_build


def map_ldr_progress_callback(
    odysseus_callback: Optional[Callable],
) -> Optional[Callable]:
    """Adapt LDR (message, progress, metadata) → Odysseus progress dict."""
    if odysseus_callback is None:
        return None
    from src.research.ldr_progress import ldr_event_to_progress

    def inner(message: str, progress: int, metadata: dict) -> None:
        event = dict(metadata or {})
        if message:
            event.setdefault("message", message)
        event.setdefault("phase", event.get("phase") or "searching")
        odysseus_callback(ldr_event_to_progress(event))

    return inner
