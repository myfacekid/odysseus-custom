"""
link_extractor.py

Background extraction of durable graph link proposals from agent sessions that
used knowledge-graph tools. Conservative — enqueues for user review only.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

LINK_EXTRACT_PROMPT = (
    "You are reviewing an AI agent conversation where the agent used knowledge "
    "graph tools (search_knowledge, compare_papers, etc.).\n\n"
    "Extract **at most 5** proposed graph edges ONLY when the session clearly "
    "established durable relationships between specific graph entities "
    "(papers, documents, tasks, research nodes) that the user would want to "
    "remember as typed links.\n\n"
    "Return the bare word null when:\n"
    "- Links are speculative, weak, or already obvious from existing graph data\n"
    "- The session was Q&A with no cross-entity relationships\n"
    "- Entities are not identifiable (no paper:KEY, document:uuid, etc.)\n"
    "- The agent failed or relationships are too vague to justify a link\n\n"
    "When proposals exist, return a JSON array of objects:\n"
    '- "from": graph node id (e.g. paper:ABCDEFGH, document:uuid)\n'
    '- "to": graph node id\n'
    '- "kind": one of derives_from, refutes, supports, relates, depends_on\n'
    '- "reason": one short sentence (required)\n'
    '- "confidence": 0.0-1.0\n\n'
    "Be conservative — if in doubt, return null.\n"
    "Return ONLY valid JSON (or the bare word null), no markdown fences."
)

MIN_CONFIDENCE = 0.7
MAX_PROPOSALS = 5
CONTEXT_WINDOW = 14

_GRAPH_TOOL_MARKERS = (
    "search_knowledge",
    "compare_papers",
    "merge_subgraph",
    "suggest_link",
    "neighbors",
)


def _session_used_graph_tools(history: List[dict]) -> bool:
    blob = json.dumps(history[-CONTEXT_WINDOW:] if len(history) > CONTEXT_WINDOW else history)
    lower = blob.lower()
    return any(marker in lower for marker in _GRAPH_TOOL_MARKERS)


def _parse_proposals(response: str) -> Optional[List[dict]]:
    if not response or response.strip().lower() == "null":
        return None
    try:
        from src.text_helpers import strip_think

        response = strip_think(response, prose=True, prompt_echo=True)
    except Exception:
        pass
    text = (response or "").strip()
    if text.startswith("```"):
        lines = text.split("\n")
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, list):
        return None
    return [p for p in parsed if isinstance(p, dict)][:MAX_PROPOSALS]


async def maybe_extract_links(
    session,
    endpoint_url: str,
    model: str,
    headers: dict,
    round_count: int,
    tool_count: int,
    *,
    owner: Optional[str] = None,
    session_id: Optional[str] = None,
):
    """Enqueue learned link proposals when a graph-heavy agent run finishes."""
    if not owner or not model:
        return None
    if round_count < 2 and tool_count < 2:
        return None

    from src.learned_link_prefs import producer_enqueue_allowed

    if not producer_enqueue_allowed(owner):
        logger.debug("[link-extract] auto_learn_links off — skipping")
        return None

    history = session.get_context_messages()
    recent = history[-CONTEXT_WINDOW:] if len(history) > CONTEXT_WINDOW else history
    if not recent or not _session_used_graph_tools(recent):
        logger.debug("[link-extract] no graph tools in recent history — skipping")
        return None

    try:
        from src.llm_core import llm_call_async

        conv_lines = []
        for msg in recent:
            role = msg.get("role", "?")
            content = msg.get("content", "")
            if isinstance(content, list):
                content = " ".join(
                    b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"
                )
            if len(content) > 600:
                content = content[:600] + "..."
            conv_lines.append(f"[{role}] {content}")
        conversation = "\n".join(conv_lines)

        response = await llm_call_async(
            endpoint_url,
            model,
            [
                {"role": "system", "content": LINK_EXTRACT_PROMPT},
                {"role": "user", "content": f"Conversation:\n{conversation}"},
            ],
            headers=headers,
            timeout=35,
        )
        proposals = _parse_proposals(response or "")
        if not proposals:
            logger.debug("[link-extract] LLM returned no proposals")
            return None

        from src.project_tool_policy import get_session_project_id

        project_id = get_session_project_id(session_id) if session_id else None
        source_session = f"chat:{session_id}" if session_id else ""

        filtered: List[dict] = []
        for raw in proposals:
            try:
                conf = float(raw.get("confidence", 0.0))
            except (TypeError, ValueError):
                conf = 0.0
            if conf < MIN_CONFIDENCE:
                continue
            row: Dict[str, Any] = {
                "from": raw.get("from"),
                "to": raw.get("to"),
                "kind": raw.get("kind") or "relates",
                "reason": raw.get("reason") or "",
                "confidence": conf,
            }
            if project_id:
                row["project_id"] = project_id
            if source_session:
                row["source_session"] = source_session
            filtered.append(row)

        if not filtered:
            return None

        from src.pending_graph_edges import enqueue_proposals

        out = enqueue_proposals(owner, filtered, source="session_extract")
        logger.info(
            "[link-extract] enqueued %d proposal(s) for %s (skipped %s)",
            out.get("added", 0),
            owner,
            out.get("skipped", 0),
        )
        return out
    except Exception as e:
        logger.warning("[link-extract] failed: %s", e)
        return None
