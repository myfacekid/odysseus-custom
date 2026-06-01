# src/deep_research.py
"""
IterResearch-style deep research engine.

Implements an iterative Think→Search→Extract→Synthesize loop where the LLM
drives every decision: what to search, what's relevant, what's missing, and
when to stop.  Inspired by Alibaba's IterResearch approach.
"""
import asyncio
import json
import logging
import re
import time
from datetime import datetime
from typing import Callable, Dict, List, Optional, Set

from src.research_utils import strip_thinking, is_low_quality

from src.goal_based_extractor import EXTRACTOR_PROMPT

logger = logging.getLogger(__name__)


def current_date_context() -> str:
    """Preamble that grounds query-generation/planning LLMs in the real current
    date. Without it the model falls back to its training-cutoff year and emits
    queries like "best Python tutorials 2025" when the year is actually 2026.
    System TZ-local so it matches what the user sees. Portable strftime only."""
    now = datetime.now().astimezone()
    return (
        f"Today's date is {now.strftime('%B %d, %Y')} ({now.strftime('%Y-%m-%d')}). "
        f"When a search query needs a year or refers to 'latest'/'current'/"
        f"'this year', use {now.strftime('%Y')} or relative wording — never a "
        f"year inferred from training data.\n\n"
    )


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
    title = (result.get("title") or "").lower()
    score = 0
    if "doi.org" in url or "pubmed" in url or "ncbi.nlm.nih.gov" in url:
        score += 12
    if "systematic review" in title or "meta-analysis" in title or "meta analysis" in title:
        score += 10
    if "review" in title and "systematic" in title:
        score += 8
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
# Prompts
# ---------------------------------------------------------------------------
RESEARCH_PLAN_PROMPT = """\
You are an academic research strategist preparing a scholarly literature review plan.

**Research question:** {question}

Break this question down for rigorous academic investigation:
1. What sub-questions must be answered from primary literature?
2. What study types matter (systematic reviews, RCTs, meta-analyses, cohort studies)?
3. What would a scientifically sound synthesis include — including gaps and limitations?

Return a JSON object with:
- "sub_questions": Array of 3-6 specific scholarly sub-questions
- "key_topics": Array of key concepts, methods, or populations to cover
- "success_criteria": One sentence describing what a complete academic answer looks like

Example:
{{
  "sub_questions": ["What RCTs exist on X?", "What do meta-analyses conclude about Y?"],
  "key_topics": ["mechanism", "effect size", "limitations", "conflicting evidence"],
  "success_criteria": "A synthesis grounded in peer-reviewed sources with explicit uncertainty."
}}
"""

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
Use terms like "systematic review", "meta-analysis", "randomized controlled trial", or "peer-reviewed" when appropriate.
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
- Ground every factual claim in the cited sources — do not invent statistics or citations
- Use numbered inline citations like [1], [2] consistently (reuse numbers for the same source)
- Note study design and evidence quality where relevant (RCT vs observational, review vs single study)
- Flag conflicting results and preprints vs peer-reviewed sources
- Resolve contradictions explicitly; do not gloss over disagreement
- Maintain scholarly tone — precise, cautious, evidence-first

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

FINAL_REPORT_PROMPT = """\
Write a rigorous **academic literature synthesis** answering this research question:

**Question:** {question}

**Collected evidence and draft synthesis:**
{report}

Requirements:
- Write at MINIMUM 1200 words — thorough but scientifically precise, not promotional
- Structure with clear ## headings: Executive Summary, Background, Key Findings, Conflicting Evidence, \
Limitations of the Evidence, Limitations of This Report, Conclusion, References
- Use numbered inline citations [1], [2], etc. for every substantive claim
- Include specific data (effect sizes, sample sizes, p-values) ONLY when present in the evidence — never invent numbers
- Distinguish peer-reviewed sources from preprints where known
- Note where evidence is strong, weak, or absent
- End with a ## References section listing every cited source as:
  [N] Author et al. (Year). Title. Venue/Journal. URL or DOI
- Use cautious academic language — avoid overstating conclusions
"""

ACADEMIC_REPORT_OVERRIDE = """\
IMPORTANT — this is exclusively an ACADEMIC research report:
- Prioritize primary literature, systematic reviews, and meta-analyses over secondary summaries
- Label preprints explicitly when used
- Never cite a source not present in the collected evidence
- The References section must match every [N] citation in the body
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
        max_urls_per_round: int = 3,
        max_content_chars: int = 15000,
        max_report_tokens: int = 8192,
        extraction_timeout: int = 90,
        extraction_concurrency: int = 3,
        min_rounds: int = 2,
        max_empty_rounds: int = 2,
        synthesis_window: int = 10,
        progress_callback: Optional[Callable] = None,
        search_provider: Optional[str] = None,
        category: Optional[str] = None,
        include_preprints: bool = True,
        include_zotero: bool = True,
        owner: str = "",
    ):
        self.llm_endpoint = llm_endpoint
        self.llm_model = llm_model
        self.llm_headers = llm_headers
        self.search_provider_override = search_provider
        self.category = ACADEMIC_CATEGORY
        self.include_preprints = bool(include_preprints)
        self.include_zotero = bool(include_zotero)
        self.owner = owner or ""
        self._zotero_keys_seen: Set[str] = set()
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

    def cancel(self):
        """Request cooperative cancellation of the research loop."""
        self._cancelled = True

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

        # PLAN: Analyze the question and create a research strategy
        if not prior_report:
            self._emit(phase="planning")
            self.research_plan = await self._create_plan(question)
            logger.info(f"Research plan: {self.research_plan[:200]}")
        else:
            # Continuation — plan around the follow-up
            self._emit(phase="planning")
            self.research_plan = await self._create_plan(question)
            logger.info(f"Continuation plan: {self.research_plan[:200]}")

        if prior_urls:
            self.urls_fetched.update(prior_urls)
        self.findings = findings  # expose for handler
        consecutive_empty_rounds = 0

        # Seed from the user's Zotero library (cloud API — works on any host).
        if self.include_zotero and not prior_report:
            if not self.owner:
                logger.info("Zotero skipped: no research owner")
            else:
                try:
                    from src.zotero_client import resolve_zotero_credentials
                    if not resolve_zotero_credentials(self.owner):
                        logger.info("Zotero skipped: not configured for user %s", self.owner)
                        self._emit(
                            phase="reading",
                            source="zotero",
                            zotero_status="not_configured",
                            message="Zotero not configured — add User ID + API key in Settings → Search, then Save",
                        )
                except Exception:
                    pass
            zotero_seed = await self._fetch_zotero_findings(question, limit=5, seed_library=True)
            if zotero_seed:
                findings.extend(zotero_seed)
                logger.info(f"Zotero seed: {len(zotero_seed)} items from library")
                self._emit(phase="reading", new_sources=len(zotero_seed),
                           total_sources=len(self.urls_fetched), source="zotero")

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
            if not queries:
                logger.warning(f"Round {round_num}: no queries generated, stopping")
                break

            self._emit(phase="searching", round=round_num, queries=len(queries),
                       query_preview=queries[0] if queries else "",
                       total_sources=len(self.urls_fetched))

            # SEARCH + EXTRACT
            round_findings = await self._search_and_extract(queries, question)
            if self.include_zotero and round_num > 1:
                for q in queries[:2]:
                    zf = await self._fetch_zotero_findings(q, limit=2)
                    if zf:
                        round_findings.extend(zf)
            if round_findings:
                findings.extend(round_findings)
                consecutive_empty_rounds = 0
                logger.info(f"Round {round_num}: extracted {len(round_findings)} findings")
                self._emit(phase="reading", round=round_num,
                           new_sources=len(round_findings),
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
        final = await self._final_report(question, report)
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

    # ------------------------------------------------------------------
    # PLAN: create research strategy
    # ------------------------------------------------------------------
    async def _create_plan(self, question: str) -> str:
        """LLM analyzes the question and creates a research plan."""
        prompt = current_date_context() + RESEARCH_PLAN_PROMPT.format(question=question)
        try:
            response = await self._llm(
                [{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=1024,
                timeout=30,
            )
            # Try to parse as JSON for structured plan
            parsed = self._parse_json_object(response)
            if parsed:
                parts = []
                if parsed.get("sub_questions"):
                    parts.append("Sub-questions: " + "; ".join(parsed["sub_questions"]))
                if parsed.get("key_topics"):
                    parts.append("Key topics: " + ", ".join(parsed["key_topics"]))
                if parsed.get("success_criteria"):
                    parts.append("Success: " + parsed["success_criteria"])
                return "\n".join(parts) if parts else response
            return response
        except Exception as e:
            logger.warning(f"Research planning failed: {e}")
            self._emit(phase="warning", message="Planning step failed, proceeding with direct search")
            return ""

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
            num_queries = 4
            round_instruction = (
                "First round — generate diverse scholarly queries covering definitions, mechanisms, "
                "empirical evidence, and systematic reviews. Include at least one query targeting "
                "PubMed or Google Scholar patterns."
            )
        else:
            num_queries = 3
            round_instruction = (
                "Follow-up round — target gaps in the synthesis: missing study types, conflicting claims, "
                "recent literature, or specific populations not yet covered."
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

        try:
            response = await self._llm(
                [{"role": "user", "content": prompt}],
                temperature=0.5,
                max_tokens=4096,
            )
            queries = self._parse_json_array(response)
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
                                  question: str) -> List[Dict]:
        """Search each query and extract relevant info from top results."""
        all_findings: List[Dict] = []

        # Search all queries in parallel
        search_tasks = [self._search(q) for q in queries]
        search_results = await asyncio.gather(*search_tasks, return_exceptions=True)

        # Collect URLs to fetch from all search results
        urls_to_fetch = []
        for result in search_results:
            if isinstance(result, Exception):
                logger.warning(f"Search error: {result}")
                continue
            if not result:
                continue
            for r in result:
                url = r.get("url", "")
                if url and url not in self.urls_fetched:
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
                return await self._fetch_and_extract(result["url"], question, result.get("title", ""))

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
    ) -> List[Dict]:
        """Pull matching items from the user's Zotero library via the Web API."""
        if not self.owner:
            return []
        try:
            from src.zotero_client import fetch_zotero_findings, resolve_zotero_credentials
            if not resolve_zotero_credentials(self.owner):
                return []
            try:
                from routes.prefs_routes import _load_for_user
                user_cfg = (_load_for_user(self.owner) or {}).get("zotero") or {}
                if user_cfg.get("include_in_research") is False:
                    return []
            except Exception:
                pass

            findings = await asyncio.to_thread(
                fetch_zotero_findings,
                query,
                self.owner,
                limit,
                True,
                seed_library,
            )
            unique = []
            for f in findings:
                zkey = f.get("zotero_key") or f.get("url", "")
                if zkey in self._zotero_keys_seen:
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

    async def _search(self, query: str) -> List[Dict]:
        """Run a search query using the configured research search provider."""
        try:
            from src.search.providers import _get_search_settings
            from src.search.core import _call_provider, _build_provider_chain

            settings = _get_search_settings()
            provider = (self.search_provider_override or "").strip()
            if not provider:
                provider = (settings.get("research_search_provider") or "").strip()
            if not provider:
                provider = settings.get("search_provider", "searxng")

            if provider == "disabled":
                logger.info("Search is disabled for research")
                return []

            # Try primary provider, then fallbacks
            chain = _build_provider_chain(provider)
            raised = False
            for prov in chain:
                try:
                    results = await asyncio.to_thread(_call_provider, prov, query, 10)
                    if results:
                        results = filter_and_rank_academic_results(
                            results, include_preprints=self.include_preprints,
                        )
                        logger.info(
                            f"Research search: {prov} returned {len(results)} results "
                            f"(preprints={'on' if self.include_preprints else 'off'})"
                        )
                        if prov not in self.providers_used:
                            self.providers_used.append(prov)
                        return results
                except Exception as e:
                    raised = True
                    logger.warning(f"Research search: {prov} failed: {e}")
                    self._last_search_error = f"{prov}: {e}"
            # Every provider ran but none returned results. If none of them
            # raised, record an actionable reason here — otherwise this empty
            # path leaves `_last_search_error` unset and the caller surfaces a
            # bare "unknown error" (issue #344). This is exactly the SearXNG
            # case where the service is reachable but all its engines fail, so
            # each provider returns [] without throwing.
            if not raised:
                self._last_search_error = (
                    f"no results from search provider(s): "
                    f"{', '.join(chain) if chain else provider}"
                )
            return []
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
            page = await asyncio.to_thread(fetch_webpage_content, url, 10)
        except Exception as e:
            logger.warning(f"Failed to fetch {url}: {e}")
            return None

        if not page.get("success") or not page.get("content"):
            return None

        content = page["content"]
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
                parsed["og_image"] = page.get("og_image", "")
                # Skip findings where the LLM says the page is useless
                if is_low_quality(parsed.get("summary", "")):
                    logger.info(f"Skipping low-quality extraction from {url}")
                    return None
                return parsed
            # If JSON parsing fails, treat entire response as evidence
            return {
                "url": url,
                "title": title or page.get("title", ""),
                "og_image": page.get("og_image", ""),
                "rational": "LLM extraction (raw)",
                "evidence": response[:3000],
                "summary": response[:500],
            }
        except Exception as e:
            logger.warning(f"LLM extraction failed for {url}: {e}")
            return None

    # ------------------------------------------------------------------
    # SYNTHESIZE
    # ------------------------------------------------------------------
    async def _synthesize(self, question: str, findings: List[Dict],
                          current_report: str) -> str:
        """LLM synthesizes all findings into an updated report."""
        # Format findings for the prompt
        window = findings[-self.synthesis_window:]
        if len(findings) > self.synthesis_window:
            logger.info(f"Synthesis using last {self.synthesis_window} of {len(findings)} findings")
        findings_text = self._format_findings(window)

        prompt = SYNTHESIZE_PROMPT.format(
            question=question,
            report=current_report or "(First round — no report yet.)",
            new_findings=findings_text,
        )

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
    async def _final_report(self, question: str, report: str) -> str:
        """LLM writes a polished academic synthesis, retrying if too short."""
        prompt = FINAL_REPORT_PROMPT.format(
            question=question,
            report=report,
        )
        prompt += "\n\n" + ACADEMIC_REPORT_OVERRIDE

        try:
            result = await self._llm(
                [{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=self.max_report_tokens,
                timeout=180,
            )

            # If report is too short, ask the LLM to expand it
            if len(result.split()) < 400:
                logger.info(f"Final report too short ({len(result.split())} words), requesting expansion")
                self._emit(phase="writing", message="Expanding report...")
                expanded = await self._llm(
                    [
                        {"role": "user", "content": prompt},
                        {"role": "assistant", "content": result},
                        {"role": "user", "content":
                            "This academic synthesis is too brief. Expand it significantly:\n"
                            "- Add detailed paragraphs for Background and Key Findings\n"
                            "- Include specific data from the evidence only — do not invent statistics\n"
                            "- Add Limitations of the Evidence and Limitations of This Report sections\n"
                            "- Use numbered citations [1], [2] and a complete ## References section\n"
                            "- Target at least 1000 words\n"
                            "Write the full expanded synthesis now."
                        },
                    ],
                    temperature=0.4,
                    max_tokens=self.max_report_tokens,
                    timeout=180,
                )
                if len(expanded.split()) > len(result.split()):
                    return expanded

            return result
        except Exception as e:
            logger.error(f"Final report generation failed: {e}")
            return report  # return the evolving report as-is

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
        """Format findings list into readable text for synthesis prompt."""
        parts = []
        for i, f in enumerate(findings, 1):
            url = f.get("url", "unknown")
            title = f.get("title", "")
            summary = f.get("summary", "")
            evidence = f.get("evidence", "")
            authors = f.get("authors", "")
            year = f.get("year", "")
            doi = f.get("doi_or_id", "")
            study_type = f.get("study_type", "")
            peer = f.get("peer_review_status", "")
            meta_bits = []
            if authors:
                meta_bits.append(f"Authors: {authors}")
            if year:
                meta_bits.append(f"Year: {year}")
            if doi:
                meta_bits.append(f"ID: {doi}")
            if study_type:
                meta_bits.append(f"Type: {study_type}")
            if peer:
                meta_bits.append(f"Status: {peer}")
            meta = " | ".join(meta_bits)
            content = summary if summary else (evidence[:1000] if evidence else "(no content)")
            header = f"**Finding {i}** — [{title}]({url})"
            if meta:
                header += f"\n*{meta}*"
            parts.append(f"{header}\n{content}")
        return "\n\n".join(parts)

    def _fallback_report(self, question: str, findings: List[Dict]) -> str:
        """Compile gathered findings into a basic report.

        Used when the LLM synthesis step produced no report (e.g. it timed out)
        but the search rounds did collect findings — so the user still gets the
        material that was gathered instead of "No information could be gathered"
        (#1551).
        """
        return (
            f"# {question}\n\n"
            "_Automatic synthesis did not complete, so this report lists the "
            f"{len(findings)} finding(s) gathered during research._\n\n"
            f"{self._format_findings(findings)}"
        )

    def get_stats(self) -> Dict:
        """Return research statistics."""
        elapsed = time.time() - self._start_time if self._start_time else 0
        stats = {
            "Duration": f"{elapsed:.1f}s",
            "Rounds": self.round_count,
            "Queries": len(self.queries_used),
            "URLs": len(self.urls_fetched),
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
