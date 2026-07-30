# services/research/research_handler.py
"""Handler for research service integration with expandable UI support.

Runs Deep Research via LDR LangGraph. Includes a task registry so research
survives page refreshes and can be cancelled.
"""
import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Optional, Dict

from src.research_utils import is_low_quality, strip_thinking

logger = logging.getLogger(__name__)

RESEARCH_DATA_DIR = Path("data/deep_research")


class ResearchHandler:
    """Handles research service operations with LDR deep research."""

    def __init__(self):
        self._active_tasks: Dict[str, dict] = {}
        RESEARCH_DATA_DIR.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Task registry — background research with persistence
    # ------------------------------------------------------------------

    def start_research(
        self,
        session_id: str,
        query: str,
        llm_endpoint: str,
        llm_model: str,
        max_time: int = 300,
        llm_headers: dict = None,
    ) -> dict:
        """Start research as a background task. Returns task info dict."""
        # Cancel any existing research for this session
        if session_id in self._active_tasks:
            existing = self._active_tasks[session_id]
            if existing.get("status") == "running":
                self.cancel_research(session_id)

        entry = {
            "task": None,
            "researcher": None,
            "query": query,
            "status": "running",
            "progress": {},
            "result": None,
            "started_at": time.time(),
        }
        self._active_tasks[session_id] = entry

        def on_progress(event):
            entry["progress"] = event

        async def _run():
            try:
                result = await self.call_research_service(
                    query, llm_endpoint, llm_model,
                    max_time=max_time,
                    progress_callback=on_progress,
                    _task_entry=entry,
                    llm_headers=llm_headers,
                )
                entry["result"] = result
                entry["status"] = "done"
                self._save_result(session_id, entry)
            except asyncio.CancelledError:
                entry["status"] = "cancelled"
                raise
            except Exception as e:
                logger.error(f"Background research failed: {e}", exc_info=True)
                entry["result"] = str(e)
                entry["status"] = "error"

        task = asyncio.create_task(_run())
        entry["task"] = task
        return {"session_id": session_id, "status": "running", "query": query}

    def get_status(self, session_id: str) -> Optional[dict]:
        """Get current research status for a session."""
        if session_id in self._active_tasks:
            entry = self._active_tasks[session_id]
            return {
                "status": entry["status"],
                "progress": entry["progress"],
                "query": entry["query"],
                "started_at": entry["started_at"],
            }
        # Check disk for completed research
        path = RESEARCH_DATA_DIR / f"{session_id}.json"
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                return {
                    "status": data.get("status", "done"),
                    "progress": {},
                    "query": data.get("query", ""),
                    "started_at": data.get("started_at", 0),
                }
            except Exception:
                pass
        return None

    def cancel_research(self, session_id: str) -> bool:
        """Cancel running research for a session."""
        if session_id not in self._active_tasks:
            return False
        entry = self._active_tasks[session_id]
        if entry["status"] != "running":
            return False
        researcher = entry.get("researcher")
        if researcher:
            researcher.cancel()
        task = entry.get("task")
        if task and not task.done():
            task.cancel()
        entry["status"] = "cancelled"
        return True

    def get_result(self, session_id: str) -> Optional[str]:
        """Get the completed research result."""
        if session_id in self._active_tasks:
            entry = self._active_tasks[session_id]
            if entry["status"] in ("done", "error", "cancelled"):
                return entry.get("result")
        # Check disk
        path = RESEARCH_DATA_DIR / f"{session_id}.json"
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                return data.get("result")
            except Exception:
                pass
        return None

    def get_sources(self, session_id: str) -> Optional[list]:
        """Get deduplicated source list from research findings."""
        # Check in-memory first
        if session_id in self._active_tasks:
            entry = self._active_tasks[session_id]
            if entry.get("sources"):
                return entry["sources"]
            researcher = entry.get("researcher")
            if researcher and researcher.findings:
                return self._extract_sources(researcher.findings)
        # Check disk
        path = RESEARCH_DATA_DIR / f"{session_id}.json"
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                return data.get("sources")
            except Exception:
                pass
        return None

    @staticmethod
    def _finding_text(finding: dict) -> str:
        """Best available text blob for quality gating (LDR uses content/abstract)."""
        for key in ("summary", "evidence", "content", "abstract"):
            val = finding.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
        return ""

    @staticmethod
    def _extract_sources(findings: list) -> list:
        """Extract deduplicated [{url, title}] from findings, filtering low-quality ones."""
        seen = set()
        sources = []
        for f in findings:
            if not isinstance(f, dict):
                continue
            url = f.get("url", "")
            title = f.get("title", "") or url
            summary = ResearchHandler._finding_text(f)
            if url and url not in seen and not is_low_quality(summary):
                seen.add(url)
                sources.append({"url": url, "title": title})
        return sources

    def clear_result(self, session_id: str):
        """Remove persisted result after it's been consumed."""
        self._active_tasks.pop(session_id, None)
        path = RESEARCH_DATA_DIR / f"{session_id}.json"
        if path.exists():
            try:
                path.unlink()
            except Exception:
                pass

    def _save_result(self, session_id: str, entry: dict):
        """Persist completed research result to disk."""
        try:
            # Extract and cache sources
            sources = []
            researcher = entry.get("researcher")
            if researcher and researcher.findings:
                sources = self._extract_sources(researcher.findings)
            entry["sources"] = sources

            path = RESEARCH_DATA_DIR / f"{session_id}.json"
            data = {
                "query": entry["query"],
                "status": entry["status"],
                "result": entry["result"],
                "sources": sources,
                "started_at": entry["started_at"],
                "completed_at": time.time(),
            }
            path.write_text(json.dumps(data), encoding="utf-8")
            logger.info(f"Research result saved to {path}")
        except Exception as e:
            logger.error(f"Failed to save research result: {e}")

    async def call_research_service(
        self,
        query: str,
        llm_endpoint: str,
        llm_model: str,
        max_time: int = 300,
        progress_callback=None,
        _task_entry: dict = None,
        llm_headers: dict = None,
    ) -> str:
        """Run deep research via LDR LangGraph."""
        from src.research.ldr_runner import LdrResearchNotReadyError, run_ldr_research

        logger.info("Starting LDR Deep Research")
        logger.info(f"Query: {query}")
        logger.info(f"LLM: {llm_endpoint} / {llm_model}")
        logger.info(f"Max time: {max_time}s")

        try:
            _holder: dict = {}
            report = await run_ldr_research(
                query,
                llm_endpoint=llm_endpoint,
                llm_model=llm_model,
                llm_headers=llm_headers,
                progress_callback=progress_callback,
                max_time=max_time,
                result_holder=_holder,
            )
            researcher = _holder.get("researcher")
            if _task_entry is not None and researcher is not None:
                _task_entry["researcher"] = researcher

            elapsed = 0.0
            stats = researcher.get_stats() if researcher else {}
            if stats.get("Duration"):
                try:
                    elapsed = float(str(stats["Duration"]).rstrip("s"))
                except ValueError:
                    elapsed = 0.0

            findings = getattr(researcher, "findings", None) if researcher else None
            evolving = getattr(researcher, "evolving_report", None) if researcher else None
            return self._format_research_report(
                query, strip_thinking(report), stats, elapsed,
                findings=findings,
                evolving_report=evolving,
            )

        except LdrResearchNotReadyError as e:
            logger.error("LDR research not ready: %s", e)
            return self._handle_research_failure(query, str(e))
        except Exception as e:
            logger.error(f"LDR research failed: {e}", exc_info=True)
            return self._handle_research_failure(query, str(e))

    def _format_research_report(
        self, query: str, full_report: str, stats: dict, elapsed: float,
        findings: list = None, evolving_report: str = None,
    ) -> str:
        """Format research report with sources list and expandable raw findings."""
        summary_lines = [
            f"**Duration:** {elapsed:.1f}s",
            f"**Rounds:** {stats.get('Rounds', stats.get('Findings', '?'))}",
            f"**Queries:** {stats.get('Queries', stats.get('Searches', '?'))}",
            f"**URLs Analyzed:** {stats.get('URLs', '?')}",
        ]
        summary_text = " | ".join(summary_lines)

        # Build sources list with clickable links
        sources_section = ""
        if findings:
            seen_urls = set()
            source_lines = []
            for f in findings:
                url = f.get("url", "")
                title = f.get("title", "") or url
                summary = self._finding_text(f) if isinstance(f, dict) else ""
                if url and url not in seen_urls and not is_low_quality(summary):
                    seen_urls.add(url)
                    source_lines.append(f"- [{title}]({url})")
            if source_lines:
                sources_section = "\n### Sources\n\n" + "\n".join(source_lines) + "\n"

        # Build raw findings section (individual extractions per source)
        raw_findings_section = ""
        if findings:
            parts = []
            for i, f in enumerate(findings, 1):
                url = f.get("url", "") if isinstance(f, dict) else ""
                title = (f.get("title", "") if isinstance(f, dict) else "") or "Untitled"
                content = self._finding_text(f) if isinstance(f, dict) else ""
                if content and len(content) > 2000:
                    content = content[:2000]
                if not content:
                    content = "(no content)"
                parts.append(f"**{i}. [{title}]({url})**\n\n{content}")
            raw_findings_section = "\n\n".join(parts)

        # Build expandable collected info section
        collected_section = ""
        if evolving_report or raw_findings_section:
            collected_section = "\n<details>\n<summary><strong>Raw collected findings ({} sources)</strong></summary>\n\n".format(
                len(findings) if findings else 0
            )
            if raw_findings_section:
                collected_section += raw_findings_section + "\n"
            collected_section += "\n</details>\n"

        formatted = f"""---

## Research Summary

{summary_text}

---

{full_report}

{sources_section}
{collected_section}
---

**The AI has analyzed all research findings above. Ask me anything about: "{query}"**
"""
        return formatted

    def _format_error_response(self, error_msg: str, query: str) -> str:
        """Format error response in a user-friendly way."""
        return f"""## Research Engine Unavailable

**Query:** {query}

**Error:** {error_msg}

**Please check:**
1. LLM endpoint is reachable
2. SearXNG is running at the configured instance
3. Application logs for detailed error information

**Troubleshooting:**
- Test basic search: Try the web search toggle first
- Check search config: `/api/search/config`
- Review logs for initialization errors
"""

    def _handle_research_failure(self, query: str, error: str) -> str:
        """Handle research failure with fallback to basic search."""
        try:
            logger.info("Attempting fallback to basic web search...")
            from src.search import comprehensive_web_search

            search_result = comprehensive_web_search(query)

            return f"""## Research Failed - Basic Search Fallback

**Query:** {query}

**Error:** {error}

**Note:** The deep research engine encountered an error. Here are basic search results instead:

---

### Basic Web Search Results

{search_result}

---

**To fix deep research:**
1. Check that your LLM endpoint and search provider are properly configured
2. Verify network connectivity
3. Review application logs for detailed error information

Try the web search toggle for simpler queries, or fix the research engine for comprehensive analysis.
"""

        except Exception as e2:
            logger.error(f"Fallback search also failed: {e2}", exc_info=True)
            return f"""## Complete Research Failure

**Primary Error:** {error}
**Fallback Error:** {str(e2)}

**Please check:**
1. Search provider configuration in Settings -> Search Settings
2. Network connectivity to search APIs
3. Application logs for detailed error information
4. That SearXNG is running (if using SearXNG)

**Debug Info:**
- Search config endpoint: `/api/search/config`
- Test basic search toggle with a simple query first
"""
