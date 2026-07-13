# src/research/iterresearch.py
"""
IterResearch-style deep research engine (legacy fallback).

Default backend is LDR LangGraph (`research_engine=ldr`). This module runs when
LDR is unavailable or `research_engine=iterresearch` is set explicitly.
"""
import asyncio
import json
import logging
import re
import time
from typing import Callable, Dict, List, Optional, Set

from src.research.research_prompts import (
    MODE_PLAN_CONTEXT,
    RESEARCH_PLAN_PROMPT,
    REPORT_LENGTH_SPECS,
    current_date_context,
)

from src.research_utils import strip_thinking, is_low_quality
from src.research_evidence import EvidenceRegistry
from src.research_web_search import (
    annotate_search_results,
    apply_academic_query_templates,
    infer_search_kind,
    is_scholar_author_profile_url,
    rank_similar_paper_search_results,
    research_web_search,
    similar_paper_queries_from_findings,
    similar_paper_queries_from_seeds,
    similar_source_from_url,
)
from src.research_zotero import research_zotero_findings
from src.research_knowledge import research_knowledge_findings
from src.research_templates import (
    ACADEMIC_REPORT_OVERRIDE,
    RESEARCH_MODES,
    build_final_report_prompt,
    expansion_user_message,
)
from src.research_finding_enrich import enrich_web_finding, normalize_finding_fields
from src.research_relevance import (
    build_relevance_query,
    filter_relevant_findings,
    format_seed_context,
    heuristic_relevance_decision,
    is_extraction_irrelevant,
    is_finding_relevant,
    is_similar_paper_relevant,
    parse_relevance_yes_no,
    RELEVANCE_GATE_PROMPT,
    RELEVANCE_GATE_WITH_SEEDS_PROMPT,
    score_search_result,
)
from src.research_retrieval_plan import (
    ResearchRetrievalPlan,
    derive_retrieval_plan_fallback,
    parse_retrieval_plan,
    plan_to_display_text,
)
from src.research_synthesis import (
    build_evidence_table,
    build_thematic_outline_prompt,
    combine_final_context_blocks,
    format_thematic_outline,
    heuristic_thematic_outline,
    should_cluster_thematically,
    should_include_evidence_table,
)

from src.goal_based_extractor import EXTRACTOR_PROMPT

logger = logging.getLogger(__name__)


ACADEMIC_CATEGORY = "academic"

# Host fragments used to detect preprint servers (excluded when include_preprints=False).
PREPRINT_HOST_FRAGMENTS = (
    "arxiv.org",
    "biorxiv.org",
    "medrxiv.org",
    "chemrxiv.org",
    "ssrn.com",
    "researchsquare.com",
    "preprints.org",
    "asapbio.org",
    "osf.io/preprints",
)

ACADEMIC_URL_MARKERS = (
    "doi.org",
    "pubmed",
    "ncbi.nlm.nih.gov",
    "scholar.google",
    "semanticscholar.org",
    "openalex.org",
    "crossref.org",
    "jstor.org",
    "springer.com",
    "sciencedirect.com",
    "wiley.com",
    "nature.com",
    "science.org",
    "cell.com",
    "plos.org",
    "ieee.org",
    "acm.org",
    "journals.",
    ".edu/",
    ".edu?",
    "researchgate.net",
    "arxiv.org",
    "systematic review",
    "meta-analysis",
    "peer-reviewed",
    "journal",
)


def _is_preprint_url(url: str) -> bool:
    lower = (url or "").lower()
    return any(h in lower for h in PREPRINT_HOST_FRAGMENTS)


def _is_academic_url(url: str) -> bool:
    lower = (url or "").lower()
    if any(m in lower for m in ACADEMIC_URL_MARKERS):
        return True
    if lower.endswith(".pdf"):
        return True
    return False


def _academic_result_score(result: Dict, include_preprints: bool) -> int:
    url = (result.get("url") or "").lower()
    score = 0
    if "doi.org" in url or "pubmed" in url or "ncbi.nlm.nih.gov" in url:
        score += 12
    if "scholar.google" in url:
        score += 10
    if _is_academic_url(url):
        score += 4
    if _is_preprint_url(url):
        score += 3 if include_preprints else -15
    if any(x in url for x in ("wikipedia.org", "reddit.com", "quora.com", "medium.com", "blog.")):
        score -= 8
    return score


def filter_and_rank_academic_results(
    results: List[Dict],
    include_preprints: bool = True,
) -> List[Dict]:
    """Prefer scholarly URLs; optionally exclude preprint hosts."""
    if not results:
        return []

    academic = []
    for r in results:
        url = r.get("url", "")
        if not url:
            continue
        if not _is_academic_url(url):
            continue
        if not include_preprints and _is_preprint_url(url):
            continue
        academic.append(r)

    pool = academic
    if not pool:
        # Relax: allow any result except blocked preprints when disabled.
        pool = [
            r for r in results
            if r.get("url") and (include_preprints or not _is_preprint_url(r.get("url", "")))
        ]
    if not pool:
        pool = list(results)

    return sorted(pool, key=lambda r: _academic_result_score(r, include_preprints), reverse=True)

# ---------------------------------------------------------------------------
# Prompts (IterResearch loop only — shared plan specs in research_prompts.py)
# ---------------------------------------------------------------------------
QUERY_GEN_PROMPT = """\
You are an academic research assistant planning scholarly web searches.

**Research question:** {question}

**Research plan:**
{research_plan}

**Current synthesis:**
{report}

**Round:** {round_num}

**Source policy:** {source_policy}

Generate {num_queries} search queries to find scholarly sources (papers, reviews, guidelines).
Prefer queries that surface: PubMed, Google Scholar, DOI pages, journal sites, university repositories.
Use exact paper titles or DOIs when searching for seed papers or related work.
Do NOT search author names alone — always pair identifiers with paper titles or DOIs.
Use terms like "randomized controlled trial" or "peer-reviewed" when appropriate; include
"systematic review" or "meta-analysis" only when that study type fits the user's question.
Prioritize topical fit to the research question and any seed papers over publication recency.
Avoid blog, news, or SEO-oriented queries.
{round_instruction}

Return ONLY a JSON array of query strings, nothing else.
Example: ["systematic review X mechanism", "meta-analysis Y outcomes site:pubmed.ncbi.nlm.nih.gov"]
"""

SYNTHESIZE_PROMPT = """\
You are updating an evolving **academic literature synthesis**.

**Research question:** {question}

**Current synthesis:**
{report}

**New findings from this round:**
{new_findings}

Integrate the new findings into the synthesis. Requirements:
- Use ONLY the citation numbers from the source registry below — do not invent new numbers
- Ground every factual claim in the cited sources — do not invent statistics or citations
- **Never infer a paper's methods, results, or conclusions from its title alone**
- For sources marked metadata-only or retrieval-failed: state only bibliographic facts (title, authors, year, DOI) and explicitly note that full text was unavailable — do not guess content
- Use numbered inline citations like [1], [2] consistently (reuse numbers for the same source)
- Note study design and evidence quality where relevant (RCT vs observational, review vs single study)
- When citing a systematic review or meta-analysis, say so explicitly (e.g. "a 2022 systematic review [3]")
- Flag conflicting results and preprints vs peer-reviewed sources
- Resolve contradictions explicitly; do not gloss over disagreement
- Maintain scholarly tone — precise, cautious, evidence-first
- Track poorly sourced papers; **Limitations of This Report** must name any source that could not be fully retrieved

Write only the updated synthesis — no preamble or meta-commentary.
"""

STOP_PROMPT = """\
You are deciding whether an academic literature synthesis is comprehensive enough.

**Research question:** {question}

**Current synthesis:**
{report}

**Rounds completed:** {round_num}

Consider scholarly completeness:
- Are key sub-questions addressed with primary or review-level evidence?
- Are there obvious gaps (missing study types, populations, or time periods)?
- Is evidence from multiple independent sources, not a single blog or secondary summary?
- Are limitations and uncertainty acknowledged?

Reply with ONLY "YES" or "NO" followed by a brief one-sentence reason.
Example: "YES — Major sub-questions are covered with multiple peer-reviewed sources and limitations noted."
Example: "NO — We still lack primary evidence on the mechanism and long-term outcomes."
"""

# ---------------------------------------------------------------------------
# DeepResearcher
# ---------------------------------------------------------------------------
class DeepResearcher:
    """
    Iterative research engine following the IterResearch pattern.

    Each round: LLM generates queries → SearXNG search → LLM extracts from
    top pages → LLM synthesizes into evolving report → LLM decides continue/stop.
    """

    def __init__(
        self,
        llm_endpoint: str,
        llm_model: str,
        llm_headers: Optional[Dict] = None,
        max_rounds: int = 8,
        max_time: int = 300,
        max_urls_per_round: int = 6,
        max_content_chars: int = 15000,
        max_report_tokens: int = 8192,
        extraction_timeout: int = 90,
        extraction_concurrency: int = 3,
        min_rounds: int = 2,
        max_empty_rounds: int = 2,
        synthesis_window: int = 20,
        progress_callback: Optional[Callable] = None,
        search_provider: Optional[str] = None,
        category: Optional[str] = None,
        include_preprints: bool = True,
        include_zotero: bool = True,
        include_knowledge: bool = True,
        owner: str = "",
        seed_papers: Optional[List[str]] = None,
        research_mode: str = "literature_review",
        report_length: str = "standard",
        approved_plan: Optional[dict] = None,
    ):
        self.llm_endpoint = llm_endpoint
        self.llm_model = llm_model
        self.llm_headers = llm_headers
        self.search_provider_override = search_provider
        self.category = ACADEMIC_CATEGORY
        self.include_preprints = bool(include_preprints)
        self.include_zotero = bool(include_zotero)
        self.include_knowledge = bool(include_knowledge)
        self.owner = owner or ""
        self.seed_papers = [s.strip() for s in (seed_papers or []) if (s or "").strip()]
        self.research_mode = (
            research_mode if research_mode in RESEARCH_MODES else "literature_review"
        )
        self.report_length = (
            report_length if report_length in REPORT_LENGTH_SPECS else "standard"
        )
        self._zotero_keys_seen: Set[str] = set()
        self._graph_nodes_seen: Set[str] = set()
        self.max_rounds = max_rounds
        self.max_time = max_time
        self.max_urls_per_round = max_urls_per_round
        self.max_content_chars = max_content_chars
        self.max_report_tokens = max_report_tokens
        self.extraction_timeout = min(3600, max(15, int(extraction_timeout or 90)))
        self.extraction_concurrency = min(12, max(1, int(extraction_concurrency or 3)))
        self.min_rounds = min_rounds
        self.max_empty_rounds = max_empty_rounds
        self.synthesis_window = synthesis_window
        self._progress = progress_callback
        self._cancelled = False
        self._start_time: float = 0
        self.queries_used: Set[str] = set()
        self.urls_fetched: Set[str] = set()
        self.round_count: int = 0
        # Track which search providers actually returned results during the
        # run, in arrival order — surfaced in the visual report so users can
        # see whether searxng / brave / tavily etc. carried the work.
        self.providers_used: List[str] = []
        self.findings: List[Dict] = []
        self.evolving_report: str = ""
        self.research_plan: str = ""
        self.retrieval_plan: Optional[ResearchRetrievalPlan] = None
        self._approved_plan: Optional[Dict] = (
            dict(approved_plan) if isinstance(approved_plan, dict) else None
        )
        self.evidence_registry = EvidenceRegistry()
        # Search-coverage tallies for the report's "Search coverage" section.
        self._coverage_screened = 0
        self._coverage_excluded: Dict[str, int] = {}
        # Structured claim-verification summary (populated after synthesis).
        self.verification_summary: Optional[Dict] = None

    def _cov_exclude(self, reason: str, n: int = 1) -> None:
        self._coverage_excluded[reason] = self._coverage_excluded.get(reason, 0) + n

    def cancel(self):
        """Request cooperative cancellation of the research loop."""
        self._cancelled = True

    def _seed_findings(self) -> List[Dict]:
        return [
            f for f in (getattr(self, "findings", None) or [])
            if f.get("is_seed")
        ]

    def _relevance_query(self, question: str) -> str:
        base = build_relevance_query(question, seed_findings=self._seed_findings())
        plan = getattr(self, "retrieval_plan", None)
        if plan:
            extra = " ".join(plan.search_keywords + plan.anchor_terms)
            if extra.strip():
                return f"{base} {extra}".strip()
        return base

    def _avoid_topics(self) -> List[str]:
        plan = getattr(self, "retrieval_plan", None)
        return list(plan.avoid_topics) if plan and plan.avoid_topics else []

    def _plan_anchor_terms(self) -> List[str]:
        plan = getattr(self, "retrieval_plan", None)
        return list(plan.anchor_terms) if plan and plan.anchor_terms else []

    def _relevance_kwargs(self) -> Dict:
        return {
            "avoid_topics": self._avoid_topics(),
            "plan_anchor_terms": self._plan_anchor_terms(),
        }

    def _register_finding_if_new(self, item: dict, *, is_seed: bool = False) -> bool:
        """Register a finding; return True only when a new registry source was created."""
        before = len(self.evidence_registry)
        self.evidence_registry.register(item, is_seed=is_seed)
        return len(self.evidence_registry) > before

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    async def research(
        self,
        question: str,
        prior_report: str = "",
        prior_findings: Optional[List[Dict]] = None,
        prior_urls: Optional[Set[str]] = None,
    ) -> str:
        """Run iterative research and return a final report.

        Args:
            question: The research question.
            prior_report: Previous report to continue from (for follow-up research).
            prior_findings: Previous findings to build on.
            prior_urls: URLs already visited (won't be re-fetched).
        """
        self._start_time = time.time()
        findings: List[Dict] = list(prior_findings) if prior_findings else []
        report = prior_report or ""
        self.evidence_registry = EvidenceRegistry()
        if findings:
            self.evidence_registry.sync_findings(findings)

        if prior_urls:
            self.urls_fetched.update(prior_urls)
        self.findings = findings
        consecutive_empty_rounds = 0

        # User-provided seed papers (Phase 2) — load before planning when present.
        if self.seed_papers and not prior_report:
            if self.research_mode == "compare" and len(self.seed_papers) < 2:
                logger.warning("Compare mode requires at least 2 seed papers")
            user_seeds = await self._load_user_seed_papers()
            if user_seeds:
                for item in user_seeds:
                    item["is_seed"] = True
                    self.evidence_registry.register(item, is_seed=True)
                    zkey = (item.get("zotero_key") or item.get("paper_key") or "").strip()
                    if zkey:
                        self._zotero_keys_seen.add(zkey)
                findings.extend(user_seeds)
                self.findings = findings
                logger.info("User seed papers: %d item(s)", len(user_seeds))
                self._emit(
                    phase="reading",
                    new_sources=len(user_seeds),
                    total_sources=len(self.urls_fetched),
                    source="seed_papers",
                )

        # PLAN: Analyze the question before discovery so retrieval_plan drives gating.
        if not prior_report:
            self._emit(phase="planning")
            self.research_plan = await self._create_plan(question)
            logger.info(f"Research plan: {self.research_plan[:200]}")
        else:
            self._emit(phase="planning")
            self.research_plan = await self._create_plan(question)
            logger.info(f"Continuation plan: {self.research_plan[:200]}")

        # Forward-citation discovery: "papers that cite/use <X>" queries cannot be
        # answered by lexical web search (downstream papers rarely repeat the seed
        # name), so resolve <X> in OpenAlex and pull its citing works directly.
        if not prior_report:
            citing = await self._fetch_citation_findings(question)
            if citing:
                added_citing = []
                for item in citing:
                    if self._register_finding_if_new(item):
                        added_citing.append(item)
                findings.extend(added_citing)
                self.findings = findings
                logger.info("Forward-citation discovery: %d citing work(s)", len(added_citing))
                self._emit(
                    phase="reading",
                    new_sources=len(added_citing),
                    total_sources=len(self.urls_fetched),
                    source="citations",
                )

        if self.seed_papers and not prior_report:
            user_seeds = self._seed_findings()
            if user_seeds and self.research_mode in (
                "literature_review", "similar_papers", "gap_analysis", "compare",
            ):
                similar = await self._fetch_similar_paper_findings(
                    user_seeds,
                    relevance_query=self._relevance_query(question),
                )
                if similar:
                    added_similar = []
                    for item in similar:
                        if self._register_finding_if_new(item):
                            added_similar.append(item)
                    findings.extend(added_similar)
                    self.findings = findings
                    self._emit(
                        phase="reading",
                        new_sources=len(added_similar),
                        total_sources=len(self.urls_fetched),
                        source="similar_papers",
                    )

                # Citation-graph snowball from seeds: forward (who cites the
                # seed) + backward (the seed's own references), 1 hop.
                graph_expand = await self._fetch_seed_citation_graph(user_seeds)
                if graph_expand:
                    added_graph = []
                    for item in graph_expand:
                        if self._register_finding_if_new(item):
                            added_graph.append(item)
                    findings.extend(added_graph)
                    self.findings = findings
                    logger.info("Seed citation-graph snowball: %d work(s)", len(added_graph))
                    self._emit(
                        phase="reading",
                        new_sources=len(added_graph),
                        total_sources=len(self.urls_fetched),
                        source="citations",
                    )

        # Seeding is explicit (user-attached papers only). Zotero/Links may be
        # queried in later rounds when enabled, but are not auto-seeded here.

        if self.include_knowledge and self.owner and not prior_report and self.seed_papers:
            gate_q = self._relevance_query(question)
            graph_related = await self._fetch_knowledge_findings(
                question,
                seed_findings=findings,
                limit=5,
                seed_graph=True,
                relevance_query=gate_q,
            )
            if graph_related:
                added_graph = []
                for item in graph_related:
                    if self._register_finding_if_new(item):
                        added_graph.append(item)
                findings.extend(added_graph)
                logger.info("Links graph expansion from seeds: %d items", len(added_graph))
                self._emit(
                    phase="reading",
                    new_sources=len(added_graph),
                    total_sources=len(self.urls_fetched),
                    source="knowledge",
                )

        for round_num in range(1, self.max_rounds + 1):
            self.round_count = round_num
            if self._cancelled:
                logger.info(f"Research cancelled after {round_num - 1} rounds")
                break
            if self._time_exceeded():
                logger.info(f"Time limit reached after {round_num - 1} rounds")
                break

            logger.info(f"=== Research Round {round_num} ===")
            self._emit(phase="searching", round=round_num, total_sources=len(self.urls_fetched))

            # THINK: generate queries
            queries = await self._generate_queries(question, report, round_num)
            if round_num > 1 and findings:
                for sq in similar_paper_queries_from_findings(findings, limit=2):
                    if sq not in self.queries_used:
                        queries.append(sq)
                        self.queries_used.add(sq)
            if not queries:
                logger.warning(f"Round {round_num}: no queries generated, stopping")
                break

            self._emit(phase="searching", round=round_num, queries=len(queries),
                       query_preview=queries[0] if queries else "",
                       total_sources=len(self.urls_fetched))

            # SEARCH + EXTRACT
            round_findings = await self._search_and_extract(
                queries, self._relevance_query(question), search_kind=infer_search_kind(round_num),
            )
            if self.include_zotero and round_num > 1:
                for q in queries[:2]:
                    zf = await self._fetch_zotero_findings(
                        q, limit=2, relevance_query=self._relevance_query(question),
                    )
                    if zf:
                        round_findings.extend(zf)
            if self.include_knowledge and round_num > 1:
                for q in queries[:2]:
                    kf = await self._fetch_knowledge_findings(
                        q,
                        seed_findings=findings,
                        limit=2,
                        relevance_query=self._relevance_query(question),
                    )
                    if kf:
                        round_findings.extend(kf)
            if round_findings:
                added_round = []
                for item in round_findings:
                    if self._register_finding_if_new(item):
                        added_round.append(item)
                findings.extend(added_round)
                consecutive_empty_rounds = 0
                logger.info(f"Round {round_num}: extracted {len(added_round)} findings")
                self._emit(phase="reading", round=round_num,
                           new_sources=len(added_round),
                           total_sources=len(self.urls_fetched),
                           total_findings=len(findings))
            else:
                consecutive_empty_rounds += 1
                logger.info(f"Round {round_num}: no new findings ({consecutive_empty_rounds} consecutive empty)")
                if consecutive_empty_rounds >= self.max_empty_rounds:
                    logger.warning(f"Search appears to be down — {self.max_empty_rounds} consecutive rounds with no results")
                    err_detail = getattr(self, '_last_search_error', 'unknown error')
                    self._emit(phase="error", message=f"Search engine unavailable: {err_detail}")
                    if not findings:
                        return (
                            f"**Search unavailable** — Web search failed after "
                            f"{round_num} rounds. Error: {err_detail}\n\n"
                            "Please check your search provider settings and ensure the service is running."
                        )
                    break

            # SYNTHESIZE
            if findings:
                self._emit(phase="analyzing", round=round_num,
                           total_sources=len(self.urls_fetched),
                           total_findings=len(findings))
                report = await self._synthesize(question, findings, report)

            # DECIDE
            if round_num >= self.min_rounds:
                should_stop = await self._should_stop(question, report, round_num)
                if should_stop:
                    logger.info(f"LLM decided to stop after round {round_num}")
                    break

        # FINAL REPORT
        self._emit(phase="writing", total_sources=len(self.urls_fetched),
                   total_findings=len(findings))
        if not report:
            # Synthesis can fail (e.g. the LLM timed out) even though the search
            # rounds did gather findings. Don't throw that work away — return the
            # gathered findings as a basic compiled report instead of claiming
            # nothing was found (#1551).
            if findings:
                logger.warning(
                    "Synthesis produced no report; returning %d gathered "
                    "finding(s) as a fallback", len(findings)
                )
                return self._fallback_report(question, findings)
            return "No information could be gathered for this question."

        self.evolving_report = report  # preserve pre-synthesis report
        self.findings = findings
        final = await self._final_report(question, report)
        final, repair_warnings = self.evidence_registry.validate_and_repair_report(final)
        for msg in repair_warnings:
            logger.warning("Report citation repair: %s", msg)
        final = await self._verify_and_annotate(question, final)
        final = self._append_coverage(final)
        elapsed = time.time() - self._start_time
        logger.info(
            f"Research complete: {self.round_count} rounds, "
            f"{len(findings)} findings, {len(self.urls_fetched)} URLs, "
            f"{elapsed:.1f}s"
        )
        return final

    # ------------------------------------------------------------------
    # LLM helper
    # ------------------------------------------------------------------
    async def _llm(self, messages: List[Dict], temperature: float = 0.3,
                   max_tokens: int = 4096, timeout: int = 60) -> str:
        """Call the LLM asynchronously and strip thinking tags."""
        from src.llm_core import llm_call_async
        response = await llm_call_async(
            url=self.llm_endpoint,
            model=self.llm_model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            headers=self.llm_headers,
            timeout=timeout,
        )
        return strip_thinking(response)

    async def _llm_relevance_gate(
        self,
        question: str,
        title: str,
        preview: str,
        *,
        source_type: str = "web",
    ) -> bool:
        """Cheap YES/NO relevance check before heavy extraction."""
        question = (question or "").strip()
        if not question:
            return True
        title = (title or "Untitled").strip()
        preview = (preview or "").strip()[:2000]
        heuristic = heuristic_relevance_decision(title, preview, question)
        if heuristic is not None:
            return heuristic
        seeds = self._seed_findings()
        if seeds:
            pseudo = {"title": title, "summary": preview, "evidence": preview}
            if not is_finding_relevant(
                pseudo,
                question,
                **self._relevance_kwargs(),
            ):
                return False
        if seeds:
            prompt = RELEVANCE_GATE_WITH_SEEDS_PROMPT.format(
                question=question,
                seed_context=format_seed_context(seeds),
                title=title,
                source_type=source_type,
                preview=preview or "(no preview)",
            )
        else:
            prompt = RELEVANCE_GATE_PROMPT.format(
                question=question,
                title=title,
                source_type=source_type,
                preview=preview or "(no preview)",
            )
        try:
            response = await self._llm(
                [{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=8,
                timeout=25,
            )
            decision = parse_relevance_yes_no(response)
            if decision is None:
                return False if seeds else (
                    heuristic_relevance_decision(title, preview, question) is not False
                )
            return decision
        except Exception as exc:
            logger.warning("Relevance gate LLM failed for %r: %s", title[:60], exc)
            if seeds:
                return False
            return heuristic_relevance_decision(title, preview, question) is not False

    # ------------------------------------------------------------------
    # PLAN: create research strategy
    # ------------------------------------------------------------------
    async def _create_plan(self, question: str) -> str:
        """LLM analyzes the question and creates a research + retrieval plan."""
        mode = getattr(self, "research_mode", "literature_review")
        seed_findings = self._seed_findings()
        if getattr(self, "_approved_plan", None):
            self.retrieval_plan = parse_retrieval_plan(
                self._approved_plan,
                question,
                seed_findings,
                research_mode=mode,
            )
            display = plan_to_display_text(self.retrieval_plan)
            return display or "Approved retrieval plan."
        mode_ctx = MODE_PLAN_CONTEXT.get(mode, "")
        seed_ctx = format_seed_context(seed_findings) if seed_findings else ""
        prompt = current_date_context() + RESEARCH_PLAN_PROMPT.format(question=question)
        if mode_ctx:
            prompt += f"\n\n{mode_ctx}"
        if seed_ctx and seed_ctx != "(none)":
            prompt += f"\n\nSeed papers (use titles and abstracts for anchor_terms and avoid_topics):\n{seed_ctx}"
        try:
            response = await self._llm(
                [{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=1536,
                timeout=45,
            )
            parsed = self._parse_json_object(response)
            self.retrieval_plan = parse_retrieval_plan(
                parsed,
                question,
                seed_findings,
                research_mode=mode,
            )
            display = plan_to_display_text(self.retrieval_plan)
            if display:
                return display
            return response
        except Exception as e:
            logger.warning(f"Research planning failed: {e}")
            self._emit(phase="warning", message="Planning step failed, proceeding with direct search")
            self.retrieval_plan = derive_retrieval_plan_fallback(
                question,
                seed_findings,
                research_mode=mode,
            )
            return plan_to_display_text(self.retrieval_plan)

    # ------------------------------------------------------------------
    # THINK: generate search queries
    # ------------------------------------------------------------------
    async def _generate_queries(self, question: str, report: str,
                                round_num: int) -> List[str]:
        if self.include_preprints:
            source_policy = (
                "Include peer-reviewed papers AND preprints (arXiv, bioRxiv, medRxiv) when relevant. "
                "Label preprints as such in follow-up synthesis."
            )
        else:
            source_policy = (
                "Peer-reviewed and published sources ONLY — exclude preprints (arXiv, bioRxiv, medRxiv, SSRN). "
                "Prefer journal articles, systematic reviews, and meta-analyses."
            )

        if round_num == 1:
            num_queries = 6
            mode = getattr(self, "research_mode", "literature_review")
            if mode == "similar_papers":
                round_instruction = (
                    "First round — generate PubMed and Google Scholar queries for related papers. "
                    "Use site:pubmed.ncbi.nlm.nih.gov, site:scholar.google.com intitle:\"…\", "
                    "exact seed paper titles, and DOIs. Never query author names without a paper title."
                )
            elif mode == "gap_analysis":
                round_instruction = (
                    "First round — search for evidence the seed papers likely miss: "
                    "alternative methods, populations, outcomes, and contradictory findings."
                )
            elif mode == "compare":
                round_instruction = (
                    "First round — search PubMed and Google Scholar for external benchmarks, "
                    "independent replications, and comparative studies relevant to the seed papers. "
                    "Use site:pubmed.ncbi.nlm.nih.gov and site:scholar.google.com filters."
                )
            else:
                round_instruction = (
                    "First round — generate diverse scholarly queries covering definitions, mechanisms, "
                    "empirical evidence, and (when appropriate) reviews. Include at least one query targeting "
                    "PubMed or Google Scholar patterns. Match the user's scope: broad field overviews may "
                    "include foundational work; narrow comparisons should stay close to the named papers."
                )
        else:
            num_queries = 4
            round_instruction = (
                "Follow-up round — gap-filling: target missing study types, conflicting claims, "
                "or specific populations not yet in the synthesis. Prefer precise sub-questions over "
                "broad topic restatements. Do not add calendar-year or recency filters unless the user "
                "asked for recent literature."
            )

        prompt = current_date_context() + QUERY_GEN_PROMPT.format(
            question=question,
            research_plan=self.research_plan or "(No plan — search scholarly sources broadly.)",
            report=report or "(No findings yet.)",
            round_num=round_num,
            num_queries=num_queries,
            round_instruction=round_instruction,
            source_policy=source_policy,
        )
        mode_ctx = MODE_PLAN_CONTEXT.get(getattr(self, "research_mode", "literature_review"), "")
        if mode_ctx:
            prompt += f"\n\n{mode_ctx}"

        try:
            response = await self._llm(
                [{"role": "user", "content": prompt}],
                temperature=0.5,
                max_tokens=4096,
            )
            queries = self._parse_json_array(response)
            search_kind = infer_search_kind(round_num)
            has_seeds = bool(self._seed_findings())
            plan = getattr(self, "retrieval_plan", None)
            scope = plan.normalized_scope() if plan else "balanced"
            expansion = list(plan.expansion_queries) if plan and round_num == 1 else []
            queries = apply_academic_query_templates(
                queries,
                search_kind=search_kind,
                question=question,
                research_plan=self.research_plan or "",
                has_seeds=has_seeds,
                scope=scope,
                expansion_queries=expansion,
            )
            # Deduplicate
            new_queries = [q for q in queries if q not in self.queries_used]
            self.queries_used.update(new_queries)
            logger.info(f"Round {round_num} queries: {new_queries}")
            return new_queries
        except Exception as e:
            logger.error(f"Query generation failed: {e}")
            self._emit(phase="warning", message=f"Query generation failed: {e}")
            return []

    # ------------------------------------------------------------------
    # SEARCH + EXTRACT
    # ------------------------------------------------------------------
    async def _search_and_extract(self, queries: List[str],
                                  question: str,
                                  search_kind: str = "discovery") -> List[Dict]:
        """Search each query and extract relevant info from top results."""
        from src.research_finding_enrich import extract_doi
        from src.research_evidence import normalize_doi
        from src.research_relevance import score_search_result, score_seed_overlap, score_specific_text_relevance

        all_findings: List[Dict] = []
        seed_findings = self._seed_findings()

        def _search_hit_score(row: Dict) -> float:
            base = score_search_result(row, question)
            specific = score_specific_text_relevance(
                " ".join([
                    row.get("title") or "",
                    row.get("snippet") or "",
                    row.get("content") or "",
                ]),
                question,
            )
            base = base * 0.45 + specific * 0.55
            if seed_findings:
                pseudo = {
                    "title": row.get("title") or "",
                    "summary": row.get("snippet") or row.get("content") or "",
                    "evidence": row.get("description") or "",
                }
                overlap = score_seed_overlap(pseudo, seed_findings)
                base = base * 0.65 + overlap * 0.35
            return base

        # Search all queries in parallel
        search_tasks = [self._search(q, search_kind=search_kind) for q in queries]
        search_results = await asyncio.gather(*search_tasks, return_exceptions=True)

        # Collect URLs to fetch from all search results (relevance-filtered).
        # Thresholds are recall-oriented: keep the gate loose enough to surface
        # more candidate literature, and rely on the post-synthesis citation
        # verification pass to protect precision.
        urls_to_fetch = []
        min_snippet_score = 0.14 if seed_findings else 0.12
        for result in search_results:
            if isinstance(result, Exception):
                logger.warning(f"Search error: {result}")
                continue
            if not result:
                continue
            ranked = sorted(
                result,
                key=_search_hit_score,
                reverse=True,
            )
            self._coverage_screened += len(ranked)
            for r in ranked:
                url = r.get("url", "")
                if not url or url in self.urls_fetched:
                    self._cov_exclude("already retrieved")
                    continue
                doi = normalize_doi(extract_doi(url))
                if doi and self.evidence_registry.has_doi(doi):
                    logger.info(
                        "Skipping web fetch for paper already in registry (DOI %s): %s",
                        doi,
                        (r.get("title") or url)[:80],
                    )
                    self.urls_fetched.add(url)
                    self._cov_exclude("duplicate")
                    continue
                rel = _search_hit_score(r)
                if rel < min_snippet_score:
                    logger.info(
                        "Skipping low-relevance search hit (score=%.2f): %s",
                        rel,
                        (r.get("title") or url)[:80],
                    )
                    self._cov_exclude("low relevance")
                    continue
                urls_to_fetch.append(r)
                self.urls_fetched.add(url)
                if len(urls_to_fetch) >= self.max_urls_per_round * len(queries):
                    break

        if self._cancelled or self._time_exceeded():
            return all_findings

        # Fetch and extract URLs with backpressure. Local model servers often
        # serialize requests behind one GPU; flooding them makes every request
        # slower and can trip the extraction timeout.
        semaphore = asyncio.Semaphore(self.extraction_concurrency)

        async def _bounded_extract(result: Dict) -> Optional[Dict]:
            async with semaphore:
                finding = await self._fetch_and_extract(
                    result["url"], question, result.get("title", ""),
                )
                if finding and question and not is_finding_relevant(
                    finding, question, **self._relevance_kwargs(),
                ):
                    logger.info(
                        "Skipping off-topic extraction: %s",
                        (finding.get("title") or result.get("url") or "")[:80],
                    )
                    self._cov_exclude("off-topic after read")
                    return None
                if not finding:
                    self._cov_exclude("extraction failed")
                if finding and result:
                    for key in (
                        "search_query", "search_provider", "search_kind",
                        "search_time_filter", "source_type",
                    ):
                        if result.get(key) and not finding.get(key):
                            finding[key] = result[key]
                return finding

        extract_tasks = [_bounded_extract(r) for r in urls_to_fetch]
        results_gathered = await asyncio.gather(*extract_tasks, return_exceptions=True)

        for result in results_gathered:
            if isinstance(result, Exception):
                logger.warning(f"Extraction error: {result}")
                continue
            if result:
                all_findings.append(result)

        return all_findings

    async def _fetch_zotero_findings(
        self,
        query: str,
        limit: int = 5,
        seed_library: bool = False,
        relevance_query: str = "",
    ) -> List[Dict]:
        """Pull matching items from the user's Zotero library (catalog first)."""
        if not self.owner:
            return []
        try:
            from src.zotero_client import resolve_zotero_credentials
            if not resolve_zotero_credentials(self.owner):
                return []
            try:
                from routes.prefs_routes import _load_for_user
                user_cfg = (_load_for_user(self.owner) or {}).get("zotero") or {}
                if user_cfg.get("include_in_research") is False:
                    return []
            except Exception:
                pass

            outcome = await asyncio.to_thread(
                research_zotero_findings,
                query,
                self.owner,
                limit=limit,
                extract_pdfs=False,
                seed_library=seed_library,
                pdf_max_chars=self.max_content_chars,
            )
            if outcome.note:
                logger.info("Zotero research: %s", outcome.note)
                self._emit(
                    phase="reading",
                    source="zotero",
                    zotero_source=outcome.source,
                    catalog_synced=outcome.catalog_synced,
                    message=outcome.note,
                )

            unique = []
            gate_q = (relevance_query or query or "").strip()
            for f in outcome.findings:
                zkey = f.get("zotero_key") or f.get("url", "")
                if zkey in self._zotero_keys_seen:
                    continue
                if gate_q and not is_finding_relevant(f, gate_q, **self._relevance_kwargs()):
                    logger.info(
                        "Skipping irrelevant Zotero item: %s",
                        (f.get("title") or zkey)[:80],
                    )
                    continue
                preview = " ".join([
                    f.get("title") or "",
                    (f.get("summary") or "")[:1200],
                    (f.get("evidence") or "")[:800],
                ])
                if gate_q and not await self._llm_relevance_gate(
                    gate_q,
                    f.get("title") or "",
                    preview,
                    source_type="zotero",
                ):
                    logger.info(
                        "Relevance gate rejected Zotero item: %s",
                        (f.get("title") or zkey)[:80],
                    )
                    continue
                self._zotero_keys_seen.add(zkey)
                url = f.get("url", "")
                if url:
                    self.urls_fetched.add(url)
                unique.append(f)
            return unique
        except Exception as e:
            logger.warning(f"Zotero fetch failed: {e}")
            return []

    async def _fetch_knowledge_findings(
        self,
        query: str,
        limit: int = 5,
        seed_findings: Optional[List[Dict]] = None,
        seed_graph: bool = False,
        relevance_query: str = "",
    ) -> List[Dict]:
        """Pull matching items from the Links knowledge graph."""
        if not self.owner:
            return []
        try:
            gate_q = (relevance_query or query or "").strip()
            outcome = await asyncio.to_thread(
                research_knowledge_findings,
                query,
                self.owner,
                seed_findings=seed_findings or self.findings,
                limit=limit,
                seed_graph=seed_graph,
                expand_hops=1,
                content_max_chars=self.max_content_chars,
                relevance_query=gate_q,
            )
            if outcome.note:
                logger.info("Links graph research: %s", outcome.note)
                self._emit(
                    phase="reading",
                    source="knowledge",
                    graph_source=outcome.source,
                    message=outcome.note,
                )

            unique = []
            for f in outcome.findings:
                gid = (f.get("graph_node_id") or "").strip()
                if gid in self._graph_nodes_seen:
                    continue
                if gate_q and not is_finding_relevant(f, gate_q, **self._relevance_kwargs()):
                    logger.info(
                        "Skipping irrelevant Links item: %s",
                        (f.get("title") or gid)[:80],
                    )
                    continue
                preview = " ".join([
                    f.get("title") or "",
                    (f.get("summary") or "")[:1200],
                    (f.get("evidence") or "")[:800],
                ])
                if gate_q and not await self._llm_relevance_gate(
                    gate_q,
                    f.get("title") or "",
                    preview,
                    source_type=f.get("node_type") or "knowledge",
                ):
                    logger.info(
                        "Relevance gate rejected Links item: %s",
                        (f.get("title") or gid)[:80],
                    )
                    continue
                self._graph_nodes_seen.add(gid)
                zkey = (f.get("zotero_key") or f.get("paper_key") or "").strip()
                if zkey:
                    if zkey in self._zotero_keys_seen:
                        continue
                    self._zotero_keys_seen.add(zkey)
                url = f.get("url", "")
                if url and not url.startswith("links://"):
                    self.urls_fetched.add(url)
                unique.append(f)
            return unique
        except Exception as e:
            logger.warning(f"Links graph fetch failed: {e}")
            return []

    async def _load_user_seed_papers(self) -> List[Dict]:
        """Load user-selected seed papers from the local catalog."""
        if not self.owner or not self.seed_papers:
            return []
        try:
            from src.research_seeds import enrich_seed_findings_from_web, seed_findings_from_refs

            outcome = await asyncio.to_thread(
                seed_findings_from_refs,
                self.owner,
                self.seed_papers,
                extract_pdfs=True,
                pdf_max_chars=self.max_content_chars,
            )
            enriched = await asyncio.to_thread(
                enrich_seed_findings_from_web,
                outcome.findings,
                owner=self.owner,
                max_chars=self.max_content_chars,
            )
            outcome = type(outcome)(
                enriched,
                outcome.resolved_keys,
                outcome.missing,
                outcome.note,
            )
            if outcome.note:
                logger.info("Seed papers: %s", outcome.note)
                self._emit(
                    phase="reading",
                    source="seed_papers",
                    message=outcome.note,
                )
            unique = []
            for f in outcome.findings:
                zkey = (f.get("zotero_key") or f.get("paper_key") or "").strip()
                if zkey and zkey in self._zotero_keys_seen:
                    continue
                if zkey:
                    self._zotero_keys_seen.add(zkey)
                url = f.get("url", "")
                if url:
                    self.urls_fetched.add(url)
                unique.append(f)
            return unique
        except Exception as e:
            logger.warning("Seed paper load failed: %s", e)
            return []

    async def _fetch_citation_findings(self, question: str) -> List[Dict]:
        """Resolve a forward-citation query to the works that cite the named paper."""
        from src.research_citation_lookup import (
            detect_citation_target,
            fetch_citing_works,
            has_citation_intent,
        )

        target = detect_citation_target(question)
        seeds = self._seed_findings()
        if not target and seeds and has_citation_intent(question):
            # Citation verb present but the target is the attached seed paper(s).
            target = (seeds[0].get("title") or "").strip() or None
        if not target:
            return []

        from src.settings import get_setting

        email = (get_setting("openalex_email", "") or "").strip()
        self._emit(
            phase="searching",
            message=f"Finding papers that cite \u201c{target}\u201d\u2026",
        )
        try:
            findings = await asyncio.to_thread(
                fetch_citing_works,
                target,
                limit=max(self.synthesis_window, 25),
                email=email,
                include_preprints=self.include_preprints,
            )
        except Exception as exc:
            logger.warning("Citation lookup failed: %s", exc)
            return []
        return findings

    async def _fetch_seed_citation_graph(self, seeds: List[Dict]) -> List[Dict]:
        """One-hop citation-graph expansion (forward + backward) of seed papers."""
        from src.research_citation_lookup import snowball_seed
        from src.settings import get_setting

        email = (get_setting("openalex_email", "") or "").strip()
        out: List[Dict] = []
        for seed in (seeds or [])[:3]:
            try:
                out += await asyncio.to_thread(
                    snowball_seed,
                    seed,
                    limit_each=15,
                    email=email,
                    include_preprints=self.include_preprints,
                )
            except Exception as exc:
                logger.warning("Seed citation-graph snowball failed: %s", exc)
        return out

    async def _fetch_similar_paper_findings(
        self,
        seed_findings: List[Dict],
        *,
        relevance_query: str = "",
    ) -> List[Dict]:
        """Find related papers via PubMed/Google Scholar; API fallback if sparse."""
        gate_q = (relevance_query or self._relevance_query("")).strip()
        unique: List[Dict] = []
        api_fallback_min = 3
        max_web_urls = 8

        async def _accept_similar(finding: Dict) -> bool:
            url = (finding.get("url") or "").strip()
            if url and url in self.urls_fetched:
                return False
            if gate_q and not is_similar_paper_relevant(
                finding,
                gate_q,
                seed_findings,
                research_mode=getattr(self, "research_mode", ""),
                **self._relevance_kwargs(),
            ):
                logger.info(
                    "Skipping unrelated similar paper: %s",
                    (finding.get("title") or url)[:80],
                )
                return False
            preview = " ".join([
                finding.get("title") or "",
                (finding.get("summary") or "")[:1200],
                (finding.get("evidence") or "")[:800],
            ])
            if gate_q and not await self._llm_relevance_gate(
                gate_q,
                finding.get("title") or "",
                preview,
                source_type="similar_paper",
            ):
                logger.info(
                    "Relevance gate rejected similar paper: %s",
                    (finding.get("title") or url)[:80],
                )
                return False
            if url:
                self.urls_fetched.add(url)
            return True

        # Primary: targeted PubMed + Google Scholar searches
        try:
            queries = similar_paper_queries_from_seeds(seed_findings, gate_q, limit=6)
            if queries:
                search_results = await asyncio.gather(
                    *[self._search(q, search_kind="similar_papers") for q in queries],
                    return_exceptions=True,
                )
                pooled: List[Dict] = []
                for result in search_results:
                    if isinstance(result, Exception):
                        logger.warning("Similar-paper search error: %s", result)
                        continue
                    if result:
                        pooled.extend(result)

                ranked = rank_similar_paper_search_results(gate_q, pooled)
                urls_to_fetch: List[Dict] = []
                seen_urls: Set[str] = set()
                for row in ranked:
                    url = row.get("url", "")
                    if is_scholar_author_profile_url(url):
                        logger.info(
                            "Skipping Scholar author profile: %s",
                            url[:80],
                        )
                        continue
                    if not url or url in self.urls_fetched or url in seen_urls:
                        continue
                    seen_urls.add(url)
                    urls_to_fetch.append(row)
                    if len(urls_to_fetch) >= max_web_urls:
                        break

                for row in urls_to_fetch:
                    finding = await self._fetch_and_extract(
                        row["url"], gate_q, row.get("title", ""),
                    )
                    if not finding:
                        continue
                    finding["source_type"] = "similar_paper"
                    finding["similar_source"] = similar_source_from_url(
                        finding.get("url") or row.get("url") or "",
                    )
                    for key in (
                        "search_query", "search_provider", "search_kind",
                        "search_time_filter",
                    ):
                        if row.get(key) and not finding.get(key):
                            finding[key] = row[key]
                    if await _accept_similar(finding):
                        unique.append(finding)

                if unique:
                    logger.info(
                        "Similar papers (PubMed/Scholar): %d item(s) from %d queries",
                        len(unique),
                        len(queries),
                    )
                    self._emit(
                        phase="reading",
                        source="similar_papers",
                        message=f"Similar papers (PubMed/Scholar): {len(unique)}",
                    )
        except Exception as e:
            logger.warning("Similar-paper web search failed: %s", e)

        # Fallback: OpenAlex + Semantic Scholar when scholarly web search is sparse
        if len(unique) >= api_fallback_min:
            return unique

        try:
            from src.research_similar_papers import similar_papers_from_seeds

            exclude = set(self._zotero_keys_seen)
            remaining = max(api_fallback_min - len(unique), 2)
            outcome = await asyncio.to_thread(
                similar_papers_from_seeds,
                seed_findings,
                limit_per_seed=3,
                total_limit=remaining,
                exclude_keys=exclude,
                relevance_query=gate_q,
                research_mode=getattr(self, "research_mode", ""),
                avoid_topics=self._avoid_topics(),
                plan_anchor_terms=self._plan_anchor_terms(),
            )
            if outcome.note:
                logger.info(outcome.note)
                self._emit(
                    phase="reading",
                    source="similar_papers",
                    message=outcome.note,
                )
            for f in outcome.findings:
                if await _accept_similar(f):
                    unique.append(f)
        except Exception as e:
            logger.warning("Similar-paper API fallback failed: %s", e)

        return unique

    async def _search(self, query: str, search_kind: str = "discovery") -> List[Dict]:
        """Run a search via the shared web_search provider layer (Phase 1a)."""
        try:
            outcome = await asyncio.to_thread(
                research_web_search,
                query,
                search_kind=search_kind,
                provider_override=self.search_provider_override,
                count=10,
            )
            if outcome.error and not outcome.results:
                self._last_search_error = outcome.error
                logger.warning("Research search failed for %r: %s", query, outcome.error)
                return []

            if outcome.provider and outcome.provider not in self.providers_used:
                self.providers_used.append(outcome.provider)

            results = annotate_search_results(outcome.results, outcome)
            results = filter_and_rank_academic_results(
                results, include_preprints=self.include_preprints,
            )
            logger.info(
                "Research search (%s/%s): %d results via %s (preprints=%s)",
                search_kind,
                query[:80],
                len(results),
                outcome.provider,
                "on" if self.include_preprints else "off",
            )
            return results
        except Exception as e:
            logger.error(f"Search failed for '{query}': {e}")
            self._last_search_error = str(e)
            return []

    async def _fetch_and_extract(self, url: str, question: str,
                                 title: str) -> Optional[Dict]:
        """Fetch a URL's content and use LLM to extract relevant info."""
        display = title or url
        self._emit(phase="reading", url=url, title=display,
                   total_sources=len(self.urls_fetched))
        try:
            from src.search import fetch_webpage_content
            page = await asyncio.to_thread(
                fetch_webpage_content, url, 10, 0, include_og_image=False,
            )
        except Exception as e:
            logger.warning(f"Failed to fetch {url}: {e}")
            return None

        if not page.get("success") or not page.get("content"):
            return None

        content = page["content"]
        page_title = title or page.get("title", "")
        if not await self._llm_relevance_gate(
            question,
            page_title,
            content[:2000],
            source_type="web",
        ):
            logger.info("Relevance gate rejected web page: %s", url)
            return None

        # Truncate to avoid blowing up context, preferring paragraph boundary
        if len(content) > self.max_content_chars:
            truncated = content[:self.max_content_chars]
            last_para = truncated.rfind('\n\n')
            if last_para > self.max_content_chars * 0.8:
                content = truncated[:last_para]
            else:
                content = truncated

        prompt = EXTRACTOR_PROMPT.format(webpage_content=content, goal=question)

        try:
            response = await self._llm(
                [{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=2048,
                timeout=self.extraction_timeout,
            )
            parsed = self._parse_json_object(response)
            if parsed:
                parsed["url"] = url
                parsed["title"] = title or page.get("title", "")
                parsed.setdefault("source_type", "web")
                parsed = enrich_web_finding(parsed, url=url, content=content)
                if is_extraction_irrelevant(parsed):
                    logger.info("Skipping irrelevant extraction from %s", url)
                    return None
                # Skip findings where the LLM says the page is useless
                if is_low_quality(parsed.get("summary", "")):
                    logger.info(f"Skipping low-quality extraction from {url}")
                    return None
                return parsed
            # If JSON parsing fails, treat entire response as evidence
            return normalize_finding_fields(enrich_web_finding({
                "url": url,
                "title": title or page.get("title", ""),
                "source_type": "web",
                "rational": "LLM extraction (raw)",
                "evidence": response[:3000],
                "summary": response[:500],
            }, url=url, content=content))
        except Exception as e:
            logger.warning(f"LLM extraction failed for {url}: {e}")
            return None

    # ------------------------------------------------------------------
    # SYNTHESIZE
    # ------------------------------------------------------------------
    async def _synthesize(self, question: str, findings: List[Dict],
                          current_report: str) -> str:
        """LLM synthesizes findings into an updated report using the evidence registry."""
        selected = self.evidence_registry.select_for_synthesis(
            findings,
            self.synthesis_window,
            relevance_query=self._relevance_query(question),
        )
        if len(findings) > len(selected):
            logger.info(
                "Synthesis using %d of %d findings (%d seed + %d top-relevance)",
                len(selected),
                len(findings),
                sum(1 for f in selected if f.get("is_seed")),
                sum(1 for f in selected if not f.get("is_seed")),
            )
        findings_text = self.evidence_registry.format_findings(selected)
        registry_block = self.evidence_registry.format_registry_block(selected)

        prompt = SYNTHESIZE_PROMPT.format(
            question=question,
            report=current_report or "(First round — no report yet.)",
            new_findings=findings_text,
        )
        if registry_block:
            prompt += f"\n\n{registry_block}\n"
        sourcing_block = self.evidence_registry.sourcing_limitations_block()
        if sourcing_block:
            prompt += f"\n\n{sourcing_block}\n"

        try:
            return await self._llm(
                [{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=self.max_report_tokens,
                # Synthesis is a heavy generation call like the final report
                # (which gets 180s); a slow local model (e.g. a 20B served from
                # LM Studio) routinely needs >60s for it. The old 60s cap timed
                # out mid-stream and discarded the round's findings (#1551).
                timeout=180,
            )
        except Exception as e:
            logger.error(f"Synthesis failed: {e}")
            self._emit(phase="warning", message="Synthesis failed, keeping previous report")
            return current_report  # keep the old report on failure

    # ------------------------------------------------------------------
    # DECIDE
    # ------------------------------------------------------------------
    async def _should_stop(self, question: str, report: str,
                           round_num: int) -> bool:
        """Let the LLM decide whether the report is comprehensive enough."""
        prompt = STOP_PROMPT.format(
            question=question,
            report=report,
            round_num=round_num,
        )

        try:
            response = await self._llm(
                [{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=128,
            )
            # Reasoning models prepend a <think>...</think> block — strip it
            # before checking for YES/NO, otherwise the answer always looks
            # like it starts with "<THINK>" and the engine never stops.
            clean = strip_thinking(response).strip()
            # Tolerate "**YES**", "Yes.", quotes, etc.
            answer = re.sub(r'^[\s*_`"\'>#\-]+', '', clean).upper()
            should_stop = answer.startswith("YES")
            logger.info(f"Stop decision (round {round_num}): {clean[:120]}")
            return should_stop
        except Exception as e:
            logger.warning(f"Stop decision failed: {e}")
            return False  # continue on error

    # ------------------------------------------------------------------
    # FINAL REPORT
    # ------------------------------------------------------------------
    async def _build_pre_final_context(self, question: str) -> str:
        """Thematic outline + evidence table blocks for the final report prompt."""
        registry = self.evidence_registry
        outline = ""
        if should_cluster_thematically(registry):
            self._emit(phase="analyzing", message="Clustering findings by theme...")
            prompt = build_thematic_outline_prompt(question, registry, self.findings)
            try:
                raw = await self._llm(
                    [{"role": "user", "content": prompt}],
                    temperature=0.2,
                    max_tokens=1536,
                    timeout=90,
                )
                outline = format_thematic_outline(raw)
            except Exception as exc:
                logger.warning("Thematic clustering failed: %s", exc)
            if not outline:
                outline = heuristic_thematic_outline(registry, self.findings)

        table = ""
        if should_include_evidence_table(registry):
            table = build_evidence_table(registry)

        return combine_final_context_blocks(outline, table)

    async def _verify_and_annotate(self, question: str, report: str) -> str:
        """Soft claim-grounding pass; appends a 'Citation verification' section.

        Always on — every report is checked against its cited sources.
        """
        try:
            from src.research_claim_verify import verify_and_annotate

            self._emit(phase="writing", message="Verifying citations against sources\u2026")
            report, summary = await verify_and_annotate(
                report,
                registry=self.evidence_registry,
                findings=self.findings,
                llm_endpoint=self.llm_endpoint,
                llm_model=self.llm_model,
                llm_headers=self.llm_headers,
            )
            self.verification_summary = summary
            return report
        except Exception as exc:
            logger.warning("Claim verification failed: %s", exc)
            return report

    def _append_coverage(self, report: str) -> str:
        """Append a '## Search coverage' section summarizing what was searched."""
        from src.research_coverage import (
            build_search_coverage_section,
            insert_section_before_references,
        )

        databases: List[str] = list(dict.fromkeys(self.providers_used or []))
        extra: Set[str] = set()
        for f in self.findings:
            sim = (f.get("similar_source") or "").lower()
            if "openalex" in sim:
                extra.add("OpenAlex")
            elif "semantic" in sim:
                extra.add("Semantic Scholar")
        databases.extend(sorted(extra))

        try:
            section = build_search_coverage_section(
                databases=databases,
                queries_count=len(self.queries_used),
                screened=self._coverage_screened,
                included=len(self.evidence_registry),
                excluded_reasons=self._coverage_excluded,
                sources=self.evidence_registry.sources(),
            )
            return insert_section_before_references(report, section)
        except Exception as exc:
            logger.warning("Coverage section build failed: %s", exc)
            return report

    async def _final_report(self, question: str, report: str) -> str:
        """LLM writes a polished academic synthesis, retrying if too short."""
        length_spec = REPORT_LENGTH_SPECS.get(self.report_length, REPORT_LENGTH_SPECS["standard"])
        min_words = length_spec["min_words"]
        expand_threshold = length_spec["expand_threshold"]
        prompt = build_final_report_prompt(
            question=question,
            report=report,
            min_words=min_words,
            mode=self.research_mode,
        )
        prompt += "\n\n" + ACADEMIC_REPORT_OVERRIDE
        registry_block = self.evidence_registry.registry_prompt_block()
        if registry_block:
            prompt += f"\n\n{registry_block}\n"
        quant_block = self.evidence_registry.quantitative_evidence_block()
        if quant_block:
            prompt += f"\n\n{quant_block}\n"
        sourcing_block = self.evidence_registry.sourcing_limitations_block()
        if sourcing_block:
            prompt += f"\n\n{sourcing_block}\n"
        synthesis_block = await self._build_pre_final_context(question)
        if synthesis_block:
            prompt += f"\n\n{synthesis_block}\n"

        try:
            result = await self._llm(
                [{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=self.max_report_tokens,
                timeout=180,
            )

            # If report is too short, ask the LLM to expand it
            if len(result.split()) < expand_threshold:
                logger.info(f"Final report too short ({len(result.split())} words), requesting expansion")
                self._emit(phase="writing", message="Expanding report...")
                expanded = await self._llm(
                    [
                        {"role": "user", "content": prompt},
                        {"role": "assistant", "content": result},
                        {"role": "user", "content": expansion_user_message(min_words)},
                    ],
                    temperature=0.4,
                    max_tokens=self.max_report_tokens,
                    timeout=180,
                )
                if len(expanded.split()) > len(result.split()):
                    result = expanded

            result, _warnings = self.evidence_registry.validate_and_repair_report(result)
            return result
        except Exception as e:
            logger.error(f"Final report generation failed: {e}")
            repaired, _warnings = self.evidence_registry.validate_and_repair_report(report)
            return repaired  # return the evolving report as-is

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _emit(self, **kwargs):
        """Send a progress event via the callback, if one is registered."""
        if self._progress:
            try:
                self._progress(kwargs)
            except Exception:
                pass

    def _time_exceeded(self) -> bool:
        return (time.time() - self._start_time) > self.max_time

    # _strip_think_tags removed — use research_utils.strip_thinking()

    @staticmethod
    def _strip_code_block(text: str) -> str:
        """Strip markdown code-block fences (```json ... ```) if present."""
        text = text.strip()
        if text.startswith("```"):
            text = re.sub(r'^```(?:json)?\s*', '', text)
            text = re.sub(r'\s*```$', '', text)
        return text.strip()

    def _parse_json_array(self, text: str) -> List[str]:
        """Extract a JSON array of strings from LLM output."""
        text = self._strip_code_block(text)
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return [str(item) for item in parsed]
        except json.JSONDecodeError:
            pass

        # Handle truncated arrays — e.g. '["query one", "query two", "query thr'
        # Repair from the LAST array start so an echoed example array earlier
        # in the reply is not harvested into the real query set.
        last_start = text.rfind('[')
        truncated = last_start != -1 and ']' not in text[last_start:]
        if truncated:
            complete_items = re.findall(r'"([^"]*)"', text[last_start:])
            if complete_items:
                logger.info(f"Repaired truncated JSON array: recovered {len(complete_items)} items")
                return complete_items

        # Greedy match to capture the full outermost array
        match = re.search(r'\[[\s\S]*\]', text)
        if match:
            try:
                parsed = json.loads(match.group())
                if isinstance(parsed, list):
                    return [str(item) for item in parsed]
            except json.JSONDecodeError:
                pass

        # Multiple complete arrays in one reply (e.g. the model echoes the
        # prompt's Example: [...] before the real array). The greedy match
        # above spans them all and fails to parse, so scan non-greedily and
        # keep the LAST parseable array, which is the model's actual answer.
        last_parsed = None
        for m in re.finditer(r'\[[\s\S]*?\]', text):
            try:
                parsed = json.loads(m.group())
                if isinstance(parsed, list):
                    last_parsed = parsed
            except json.JSONDecodeError:
                continue
        if last_parsed is not None:
            return [str(item) for item in last_parsed]

        # Last resort: harvest quoted strings from the first array start
        arr_start = text.find('[')
        if arr_start != -1:
            fragment = text[arr_start:]
            # Find the last complete quoted string
            complete_items = re.findall(r'"([^"]*)"', fragment)
            if complete_items:
                logger.info(f"Repaired truncated JSON array: recovered {len(complete_items)} items")
                return complete_items

        logger.warning(f"Could not parse JSON array from: {text[:200]}")
        return []

    def _parse_json_object(self, text: str) -> Optional[Dict]:
        """Extract a JSON object from LLM output."""
        text = self._strip_code_block(text)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Greedy match to capture the full outermost object
        match = re.search(r'\{[\s\S]*\}', text)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass

        return None

    def _format_findings(self, findings: List[Dict]) -> str:
        """Format findings list into readable text (legacy helper)."""
        self.evidence_registry.sync_findings(findings)
        return self.evidence_registry.format_findings(findings)

    def _fallback_report(self, question: str, findings: List[Dict]) -> str:
        """Compile gathered findings into a structured academic fallback report."""
        return self.evidence_registry.build_structured_fallback(question, findings)

    def get_stats(self) -> Dict:
        """Return research statistics."""
        elapsed = time.time() - self._start_time if self._start_time else 0
        stats = {
            "Duration": f"{elapsed:.1f}s",
            "Rounds": self.round_count,
            "Queries": len(self.queries_used),
            "URLs": len(self.urls_fetched),
            "Sources": len(self.evidence_registry),
            "Model": self.llm_model,
        }
        if self.providers_used:
            stats["Search"] = ", ".join(self.providers_used)
        stats["Mode"] = "Academic"
        if not self.include_preprints:
            stats["Preprints"] = "Excluded"
        if self.include_zotero and self.owner:
            try:
                from src.zotero_client import resolve_zotero_credentials
                if resolve_zotero_credentials(self.owner):
                    stats["Zotero"] = "Included"
            except Exception:
                pass
        return stats
