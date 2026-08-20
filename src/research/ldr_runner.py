"""Run Deep Research via Local Deep Research LangGraph agent (Phase L2).

Gathering: LDR langgraph-agent + search engines + Nobody tools.
Synthesis: Nobody EvidenceRegistry + academic templates (decision B).
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable, Dict, List, Optional, Set

from src.research_evidence import doi_from_finding
from src.research.ldr_availability import ldr_stack_available
from src.research.ldr_collector_mapper import (
    compile_gathering_draft,
    ingest_ldr_links,
)
from src.research.ldr_llm_adapter import build_langchain_chat_model
from src.research.ldr_planning import (
    build_agent_context_prompt,
    build_retrieval_plan,
    load_seed_findings,
)
from src.research.ldr_progress import wrap_progress_callback
from src.research.ldr_session import LdrResearchSession
from src.research.ldr_synthesis import synthesize_academic_report
from src.research.ldr_tools import NobodyAgentConfig, attach_nobody_tools, map_ldr_progress_callback
from src.research_relevance import build_relevance_query

logger = logging.getLogger(__name__)

# Nobody search_provider → LDR search.tool
_SEARCH_TOOL_ALIASES = {
    "searxng": "searxng",
    "brave": "brave",
    "tavily": "tavily",
    "duckduckgo": "duckduckgo",
    "google": "serper",
    "serper": "serper",
}


class LdrResearchNotReadyError(RuntimeError):
    """Raised when research_engine=ldr but integration is incomplete or deps missing."""


def _resolve_ldr_search_tool(search_provider: Optional[str]) -> str:
    key = (search_provider or "searxng").strip().lower()
    return _SEARCH_TOOL_ALIASES.get(key, key if key else "searxng")


def _harvest_partial_gather_links(gather_state: Optional[dict]) -> List[dict]:
    """Best-effort link harvest when gather times out but the agent collected sources."""
    if not gather_state:
        return []
    cached = gather_state.get("links")
    if cached:
        return list(cached)
    system = gather_state.get("system")
    if not system:
        return []
    try:
        collector = getattr(getattr(system, "strategy", None), "collector", None)
        raw = getattr(system, "all_links_of_system", None) or getattr(collector, "results", None) or []
        return list(raw)
    except Exception:
        logger.debug("Could not harvest partial LDR links after gather timeout", exc_info=True)
        return []


def _run_ldr_gather_sync(
    *,
    agent_query: str,
    chat_model,
    search_tool: str,
    max_iterations: int,
    progress_callback: Optional[Callable],
    agent_config: NobodyAgentConfig,
    gather_state: Optional[dict] = None,
) -> List[dict]:
    """Blocking LDR LangGraph gather; returns collector link dicts."""
    from local_deep_research.config.search_config import get_search
    from local_deep_research.search_system import AdvancedSearchSystem
    from src.research_engines.settings_bridge import build_ldr_settings_snapshot

    settings_snapshot = build_ldr_settings_snapshot(
        search_provider=search_tool,
        extra_overrides={
            "search.tool": search_tool,
            "search.search_strategy": "langgraph-agent",
            "langgraph_agent.max_iterations": max_iterations,
            "langgraph_agent.include_sub_research": False,
        },
    )
    search_engine = get_search(
        search_tool,
        llm_instance=chat_model,
        settings_snapshot=settings_snapshot,
        programmatic_mode=True,
    )
    system = AdvancedSearchSystem(
        llm=chat_model,
        search=search_engine,
        strategy_name="langgraph-agent",
        settings_snapshot=settings_snapshot,
        programmatic_mode=True,
        max_iterations=max_iterations,
    )
    if gather_state is not None:
        gather_state["system"] = system

    def _live_source_count() -> int:
        links = system.all_links_of_system
        if links is not None:
            try:
                return len(links)
            except TypeError:
                pass
        try:
            return len(system.strategy.collector.results or [])
        except Exception:
            return 0

    ldr_progress = map_ldr_progress_callback(
        progress_callback,
        source_count_fn=_live_source_count,
    )
    if ldr_progress:
        system.set_progress_callback(ldr_progress)

    attach_nobody_tools(system.strategy, agent_config)

    try:
        system.analyze_topic(agent_query)
        links = list(system.all_links_of_system or system.strategy.collector.results)
        if gather_state is not None:
            gather_state["links"] = links
        return links
    finally:
        if gather_state is not None and "links" not in gather_state:
            gather_state["links"] = _harvest_partial_gather_links(gather_state)
        try:
            system.close()
        except Exception:
            pass
        try:
            from local_deep_research.utilities.resource_utils import safe_close

            safe_close(search_engine, "search engine")
        except Exception:
            pass


async def run_ldr_research(
    question: str,
    *,
    llm_endpoint: str,
    llm_model: str,
    llm_headers: Optional[Dict[str, str]] = None,
    progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    seed_papers: Optional[List[str]] = None,
    research_mode: str = "literature_review",
    owner: str = "",
    max_iterations: int = 50,
    max_time: int = 300,
    search_provider: Optional[str] = None,
    approved_plan: Optional[Dict[str, Any]] = None,
    prior_report: str = "",
    prior_findings: Optional[List[Dict]] = None,
    prior_urls: Optional[Set[str]] = None,
    include_preprints: bool = True,
    include_zotero: bool = True,
    include_knowledge: bool = True,
    report_length: str = "standard",
    result_holder: Optional[Dict[str, Any]] = None,
) -> str:
    """Execute LDR LangGraph research; returns Nobody academic markdown report."""
    if not ldr_stack_available():
        raise LdrResearchNotReadyError(
            "local-deep-research is not installed. "
            "Reinstall with: pip install -r requirements.txt "
            "(requires Python 3.12–3.13; LDR dependencies may not install on 3.14+)."
        )

    wrapped = wrap_progress_callback(progress_callback)
    start_time = time.time()

    session = LdrResearchSession(
        llm_model=llm_model,
        include_preprints=include_preprints,
        include_zotero=include_zotero,
        owner=owner,
    )
    if result_holder is not None:
        result_holder["researcher"] = session

    if wrapped:
        wrapped({"phase": "planning", "message": "Building retrieval plan…"})

    from src.settings import get_setting
    from src.research_utils import get_research_max_content_chars

    max_content_chars = get_research_max_content_chars()
    max_report_tokens = int(get_setting("research_max_tokens", 16384))
    if report_length == "extended":
        max_report_tokens = max(max_report_tokens, 24576)

    seed_findings: List[dict] = []
    if seed_papers and owner and not prior_report:
        if wrapped:
            wrapped({"phase": "reading", "message": "Loading seed papers…", "source": "seed_papers"})
        seed_findings, seed_note = await load_seed_findings(
            owner=owner,
            seed_papers=seed_papers,
            max_content_chars=max_content_chars,
        )
        if seed_note and wrapped:
            wrapped({"phase": "reading", "message": seed_note, "source": "seed_papers"})
        for item in seed_findings:
            item["is_seed"] = True
            session.evidence_registry.register(item, is_seed=True)
            url = (item.get("url") or "").strip()
            if url:
                session.urls_fetched.add(url)
            doi = doi_from_finding(item)
            if doi:
                session.dois_seen.add(doi)
        session.findings.extend(seed_findings)
        if wrapped and seed_findings:
            wrapped({
                "phase": "reading",
                "message": f"Loaded {len(seed_findings)} seed paper(s)",
                "total_sources": len(session.evidence_registry),
                "new_sources": len(seed_findings),
            })

        # One-hop citation-graph snowball from seeds (forward + backward).
        from src.research_citation_lookup import snowball_seed

        seed_email = (get_setting("openalex_email", "") or "").strip()
        for seed in seed_findings[:3]:
            try:
                expand = await asyncio.to_thread(
                    snowball_seed,
                    seed,
                    limit_each=15,
                    email=seed_email,
                    include_preprints=include_preprints,
                )
            except Exception as exc:
                logger.warning("LDR seed citation-graph snowball failed: %s", exc)
                expand = []
            for item in expand:
                session.evidence_registry.register(item)
                curl = (item.get("url") or "").strip()
                if curl:
                    session.urls_fetched.add(curl)
                cdoi = doi_from_finding(item)
                if cdoi:
                    session.dois_seen.add(cdoi)
            if expand:
                session.findings.extend(expand)
                logger.info("LDR seed citation-graph snowball: %d work(s)", len(expand))
                if wrapped:
                    wrapped({
                        "phase": "reading",
                        "message": f"Citation snowball: +{len(expand)} work(s)",
                        "total_sources": len(session.evidence_registry),
                        "new_sources": len(expand),
                    })

    if prior_findings:
        session.evidence_registry.sync_findings(prior_findings)
        session.findings.extend(list(prior_findings))
    if prior_urls:
        session.urls_fetched.update(prior_urls)

    # Forward-citation discovery: "papers that cite/use <X>" queries can't be
    # answered by the LangGraph agent's web search alone, so resolve <X> in
    # OpenAlex and inject its citing works (most-cited first) as findings.
    if not prior_report:
        from src.research_citation_lookup import (
            detect_citation_target,
            fetch_citing_works,
            has_citation_intent,
        )

        citation_target = detect_citation_target(question)
        if not citation_target and seed_findings and has_citation_intent(question):
            citation_target = (seed_findings[0].get("title") or "").strip() or None
        if citation_target:
            if wrapped:
                wrapped({
                    "phase": "searching",
                    "message": f"Finding papers that cite \u201c{citation_target}\u201d\u2026",
                })
            try:
                citing = await asyncio.to_thread(
                    fetch_citing_works,
                    citation_target,
                    limit=25,
                    email=(get_setting("openalex_email", "") or "").strip(),
                    include_preprints=include_preprints,
                )
            except Exception as exc:
                logger.warning("LDR citation lookup failed: %s", exc)
                citing = []
            for item in citing:
                session.evidence_registry.register(item)
                curl = (item.get("url") or "").strip()
                if curl:
                    session.urls_fetched.add(curl)
                cdoi = doi_from_finding(item)
                if cdoi:
                    session.dois_seen.add(cdoi)
            if citing:
                session.findings.extend(citing)
                logger.info("LDR forward-citation discovery: %d citing work(s)", len(citing))
                if wrapped:
                    wrapped({
                        "phase": "searching",
                        "message": f"Found {len(citing)} citing work(s)",
                        "total_sources": len(session.evidence_registry),
                        "new_sources": len(citing),
                    })

    plan, plan_display, _plan_source = await build_retrieval_plan(
        question=question,
        llm_endpoint=llm_endpoint,
        llm_model=llm_model,
        llm_headers=llm_headers,
        research_mode=research_mode,
        seed_findings=seed_findings or None,
        approved_plan=approved_plan,
    )

    relevance_query = build_relevance_query(
        question,
        seed_findings=[f for f in session.findings if f.get("is_seed")],
    )
    agent_query = build_agent_context_prompt(
        question=question,
        plan=plan,
        plan_display=plan_display,
        research_mode=research_mode,
        include_preprints=include_preprints,
        include_zotero=include_zotero,
        include_knowledge=include_knowledge,
        seed_findings=seed_findings or None,
        prior_report=prior_report,
    )

    chat_model = build_langchain_chat_model(
        chat_endpoint=llm_endpoint,
        model=llm_model,
        headers=llm_headers,
        temperature=0.3,
    )
    search_tool = _resolve_ldr_search_tool(search_provider)
    session.providers_used.append(search_tool)

    agent_config = NobodyAgentConfig(
        owner=owner,
        include_zotero=include_zotero,
        include_knowledge=include_knowledge,
        seed_findings=seed_findings or None,
        relevance_query=relevance_query,
        max_content_chars=max_content_chars,
    )

    if wrapped:
        wrapped(
            {
                "phase": "searching",
                "message": f"LangGraph agent gathering sources ({search_tool})…",
            }
        )

    effective_iterations = max(12, min(int(max_iterations or 50), 35))
    # Reserve wall time for planning + Nobody synthesis; gather uses the remainder.
    elapsed_before_gather = time.time() - start_time
    gather_budget = int(max_time) - int(elapsed_before_gather) - 90 if max_time else None
    if gather_budget is not None:
        gather_budget = max(60, gather_budget)
    remaining = gather_budget
    gather_state: dict = {}

    try:
        ldr_links = await asyncio.wait_for(
            asyncio.to_thread(
                _run_ldr_gather_sync,
                agent_query=agent_query,
                chat_model=chat_model,
                search_tool=search_tool,
                max_iterations=effective_iterations,
                progress_callback=progress_callback,
                agent_config=agent_config,
                gather_state=gather_state,
            ),
            timeout=remaining,
        )
    except asyncio.TimeoutError as exc:
        ldr_links = _harvest_partial_gather_links(gather_state)
        if ldr_links:
            logger.warning(
                "LDR gather hit max_time (%ss); continuing with %d partial link(s)",
                max_time,
                len(ldr_links),
            )
            if wrapped:
                wrapped(
                    {
                        "phase": "warning",
                        "message": (
                            f"Source gathering timed out after {max_time}s; "
                            f"synthesizing from {len(ldr_links)} collected source(s)."
                        ),
                    }
                )
        else:
            raise LdrResearchNotReadyError(
                f"LDR research exceeded max_time ({max_time}s) during source gathering."
            ) from exc

    if session.cancelled:
        raise LdrResearchNotReadyError("Research cancelled.")

    logger.info("LDR gather returned %d link(s) for ingest", len(ldr_links or []))

    ldr_excluded: Dict[str, int] = {}

    def _emit_rejection(finding: dict, reason: str) -> None:
        label = (reason or "excluded").strip().lower()
        ldr_excluded[label] = ldr_excluded.get(label, 0) + 1
        if not wrapped:
            return
        title = (finding.get("title") or "Untitled").strip()
        wrapped(
            {
                "phase": "warning",
                "event": "source_rejected",
                "reason": reason,
                "source": finding.get("search_provider") or "ldr",
                "message": f"Skipped source ({reason}): {title[:80]}",
            }
        )

    new_findings = ingest_ldr_links(
        session.evidence_registry,
        ldr_links,
        include_preprints=include_preprints,
        avoid_topics=plan.avoid_topics,
        seen_urls=session.urls_fetched,
        seen_dois=session.dois_seen,
        on_reject=_emit_rejection,
    )
    session.findings.extend(new_findings)
    session.round_count = 1
    if wrapped:
        wrapped({
            "phase": "reading",
            "message": f"Ingested {len(new_findings)} gathered source(s)",
            "total_sources": len(session.evidence_registry),
            "new_sources": len(new_findings),
        })

    if wrapped:
        wrapped(
            {
                "phase": "reading",
                "message": "Enriching sources (DOI abstracts + selective full text)…",
                "total_sources": len(session.evidence_registry),
            }
        )

    from src.research.ldr_content_enrich import run_ldr_content_enrichment

    def _enrich_progress(event: Dict[str, Any]) -> None:
        if not wrapped:
            return
        payload = dict(event or {})
        payload.setdefault("total_sources", len(session.evidence_registry))
        wrapped(payload)

    deep_read_context = await run_ldr_content_enrichment(
        question=question,
        registry=session.evidence_registry,
        findings=session.findings,
        owner=owner,
        llm_endpoint=llm_endpoint,
        llm_model=llm_model,
        llm_headers=llm_headers,
        max_content_chars=max_content_chars,
        progress_callback=_enrich_progress if wrapped else None,
    )

    if wrapped:
        wrapped(
            {
                "phase": "synthesizing",
                "message": f"Synthesizing {len(session.evidence_registry)} sources…",
                "total_sources": len(session.evidence_registry),
            }
        )

    draft = prior_report.strip() or compile_gathering_draft(session.evidence_registry)

    report = await synthesize_academic_report(
        question=question,
        draft_report=draft,
        registry=session.evidence_registry,
        llm_endpoint=llm_endpoint,
        llm_model=llm_model,
        llm_headers=llm_headers,
        research_mode=research_mode,
        report_length=report_length,
        max_report_tokens=max_report_tokens,
        deep_read_context=deep_read_context,
        findings=session.findings,
    )
    session.evolving_report = report

    # Soft claim-grounding verification (#1, always on) + search-coverage (#2).
    try:
        from src.research_claim_verify import verify_and_annotate

        if wrapped:
            wrapped({"phase": "writing", "message": "Verifying citations against sources\u2026"})
        report, verification_summary = await verify_and_annotate(
            report,
            registry=session.evidence_registry,
            findings=session.findings,
            llm_endpoint=llm_endpoint,
            llm_model=llm_model,
            llm_headers=llm_headers,
        )
        session.verification_summary = verification_summary
    except Exception as exc:
        logger.warning("LDR claim verification failed: %s", exc)

    try:
        from src.research_coverage import (
            build_search_coverage_section,
            insert_section_before_references,
        )

        dbs = list(dict.fromkeys(getattr(session, "providers_used", []) or []))
        extra = set()
        for f in session.findings:
            sim = (f.get("similar_source") or "").lower()
            if "openalex" in sim:
                extra.add("OpenAlex")
            elif "semantic" in sim:
                extra.add("Semantic Scholar")
        dbs.extend(sorted(extra))
        coverage = build_search_coverage_section(
            databases=dbs,
            queries_count=0,
            screened=len(ldr_links or []),
            included=len(session.evidence_registry),
            excluded_reasons=ldr_excluded,
            sources=session.evidence_registry.sources(),
        )
        report = insert_section_before_references(report, coverage)
    except Exception as exc:
        logger.warning("LDR coverage section build failed: %s", exc)

    session.evolving_report = report

    if wrapped:
        wrapped({"phase": "done", "message": "Research complete."})

    logger.info(
        "LDR research complete: %d registry sources, %.1fs",
        len(session.evidence_registry),
        time.time() - start_time,
    )
    return report
