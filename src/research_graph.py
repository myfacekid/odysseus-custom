"""Link completed Deep Research sessions into the knowledge graph (Phase 5b)."""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

RESEARCH_DATA_DIR = Path("data/deep_research")
RESEARCH_EDGE_SOURCE = "research_auto"
_TOP_CITED_CAP = 20
_ZOTERO_KEY_RE = re.compile(r"^[A-Z0-9]{8}$", re.I)

_MODE_LABELS = {
    "literature_review": "Literature review",
    "compare": "Compare",
    "gap_analysis": "Gap analysis",
    "similar_papers": "Similar papers",
}


def compute_source_breakdown(data: dict) -> Dict[str, int]:
    """Count registry sources by coarse type (web / zotero / graph / seeds)."""
    registry = (data or {}).get("evidence_registry") or {}
    sources = registry.get("sources") or []
    breakdown = {"web": 0, "zotero": 0, "graph": 0, "seeds": 0, "total": len(sources)}
    for src in sources:
        if not isinstance(src, dict):
            continue
        if src.get("is_seed"):
            breakdown["seeds"] += 1
        st = (src.get("source_type") or "web").strip().lower()
        if st == "zotero":
            breakdown["zotero"] += 1
        elif st in ("knowledge", "graph"):
            breakdown["graph"] += 1
        else:
            breakdown["web"] += 1
    return breakdown


def _mode_label(mode: str) -> str:
    key = (mode or "literature_review").strip().lower()
    return _MODE_LABELS.get(key, key.replace("_", " ").title() or "Research")


def _paper_id_from_registry_source(src: dict) -> Optional[str]:
    from src.knowledge_graph import node_id

    sid = (src.get("source_id") or "").strip()
    if sid.startswith("src:zotero:"):
        key = sid.rsplit(":", 1)[-1].strip().upper()
        return node_id("paper", key) if key else None
    if sid.startswith("src:paper:"):
        key = sid.rsplit(":", 1)[-1].strip().upper()
        return node_id("paper", key) if key else None
    doi_or = (src.get("doi_or_id") or "").strip()
    if _ZOTERO_KEY_RE.match(doi_or):
        return node_id("paper", doi_or.upper())
    return None


def collect_research_link_targets(data: dict, *, cap: int = _TOP_CITED_CAP) -> List[str]:
    """Paper node ids to link from a research session (seeds first, then top cited)."""
    from src.knowledge_graph import node_id

    ordered: List[str] = []
    seen: Set[str] = set()

    def add(pid: Optional[str]) -> None:
        if not pid or pid in seen:
            return
        seen.add(pid)
        ordered.append(pid)

    for row in (data or {}).get("seed_paper_details") or []:
        if not isinstance(row, dict):
            continue
        key = (row.get("zotero_key") or "").strip().upper()
        if key:
            add(node_id("paper", key))

    for ref in (data or {}).get("seed_papers") or []:
        raw = (ref or "").strip()
        if not raw:
            continue
        if raw.lower().startswith("paper:"):
            key = raw.split(":", 1)[1].strip().upper()
        elif _ZOTERO_KEY_RE.match(raw):
            key = raw.upper()
        else:
            key = ""
        if key:
            add(node_id("paper", key))

    registry = (data or {}).get("evidence_registry") or {}
    cited = sorted(
        [s for s in (registry.get("sources") or []) if isinstance(s, dict)],
        key=lambda s: int(s.get("citation_num") or 0),
    )
    for src in cited:
        if len(ordered) >= cap:
            break
        add(_paper_id_from_registry_source(src))

    return ordered[:cap]


def research_node_dict(session_id: str, data: dict) -> dict:
    from src.knowledge_graph import KnowledgeNode, _snippet, node_id

    sid = (session_id or "").strip()
    query = ((data or {}).get("query") or "Research").strip()
    mode = (data or {}).get("research_mode") or "literature_review"
    breakdown = compute_source_breakdown(data)
    seeds = (data or {}).get("seed_paper_details") or []
    stats = (data or {}).get("stats") or {}
    snippet_parts = [_mode_label(mode)]
    if breakdown.get("total"):
        snippet_parts.append(f"{breakdown['total']} sources")
    if seeds:
        snippet_parts.append(f"{len(seeds)} seed(s)")
    if stats.get("Rounds"):
        snippet_parts.append(f"{stats.get('Rounds')} rounds")

    return KnowledgeNode(
        id=node_id("research", sid),
        type="research",
        title=query[:200] or "Research",
        snippet=_snippet(" · ".join(snippet_parts)),
        meta={
            "source": "deep_research",
            "session_id": sid,
            "research_mode": mode,
            "research_mode_label": _mode_label(mode),
            "source_breakdown": breakdown,
            "seed_count": len((data or {}).get("seed_papers") or []),
            "report_url": f"/api/research/report/{sid}",
            "completed_at": (data or {}).get("completed_at") or 0,
        },
    ).to_dict()


def index_research_nodes(owner: str, nodes: Dict[str, dict]) -> None:
    """Merge completed research JSON files into *nodes* during graph rebuild."""
    if not owner or not RESEARCH_DATA_DIR.is_dir():
        return
    for path in RESEARCH_DATA_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("owner") != owner:
                continue
            if data.get("status") not in ("done", "complete", "completed", "success"):
                if not (data.get("result") or data.get("raw_report")):
                    continue
            node = research_node_dict(path.stem, data)
            nodes[node["id"]] = node
        except Exception as e:
            logger.debug("Skip research index %s: %s", path.name, e)


def upsert_research_node(owner: str, session_id: str, data: dict) -> None:
    from src.knowledge_graph import load_edges, load_nodes, save_graph

    if not owner or not session_id:
        return
    nodes = load_nodes(owner)
    edges = load_edges(owner)
    node = research_node_dict(session_id, data)
    nodes[node["id"]] = node
    save_graph(owner, nodes, edges)


def propose_research_graph_links(owner: str, session_id: str, data: dict) -> Dict[str, Any]:
    """Upsert research node and enqueue typed edge proposals for user review (L2)."""
    from src.knowledge_graph import get_node, node_id
    from src.pending_graph_edges import enqueue_proposals
    from src.research_typed_edges import build_research_graph_edges

    if not owner or not session_id:
        return {"ok": False, "error": "owner and session_id required", "proposals": []}

    upsert_research_node(owner, session_id, data)
    rid = node_id("research", session_id)
    raw_edges = build_research_graph_edges(session_id, data)
    proposals: List[dict] = []
    skipped_missing: List[str] = []

    project_id = ((data or {}).get("project_id") or "").strip()
    for edge in raw_edges:
        fr = edge.get("from") or ""
        to = edge.get("to") or ""
        if not get_node(owner, fr) or not get_node(owner, to):
            if to:
                skipped_missing.append(to)
            elif fr:
                skipped_missing.append(fr)
            continue
        proposals.append({
            **edge,
            "source": "research",
            "source_session": session_id,
            **({"project_id": project_id} if project_id else {}),
        })

    from src.learned_link_prefs import producer_enqueue_allowed

    enqueue_out = (
        enqueue_proposals(owner, proposals, source="research")
        if proposals and producer_enqueue_allowed(owner)
        else {
            "ok": True,
            "added": 0,
            "skipped": len(proposals),
            "rows": [],
            "gated": proposals and not producer_enqueue_allowed(owner),
        }
    )
    rows = enqueue_out.get("rows") or []
    return {
        "ok": True,
        "research_id": rid,
        "proposals": rows,
        "proposal_count": len(rows),
        "skipped_missing": skipped_missing,
        "added": enqueue_out.get("added", 0),
        "skipped_duplicates": enqueue_out.get("skipped", 0),
    }


def sync_research_graph_links(owner: str, session_id: str, data: dict) -> Dict[str, Any]:
    """Backward-compatible alias — research edges are proposals until accepted."""
    return propose_research_graph_links(owner, session_id, data)


def link_research_on_complete(owner: str, session_id: str, data: dict) -> Dict[str, Any]:
    """Hook after research JSON is written — graph node, pending edges, paper summaries."""
    if not owner:
        return {"ok": False, "error": "owner required", "proposals": []}

    graph_out: Dict[str, Any] = {"ok": False, "proposals": [], "proposal_count": 0}
    try:
        graph_out = propose_research_graph_links(owner, session_id, data)
        logger.info(
            "Research graph proposals for %s: %d enqueued, %d target(s) missing from graph",
            session_id,
            graph_out.get("proposal_count") or 0,
            len(graph_out.get("skipped_missing") or []),
        )
    except Exception as e:
        logger.warning("Research graph linking failed for %s: %s", session_id, e)
        graph_out = {"ok": False, "error": str(e), "proposals": [], "proposal_count": 0}

    summary_out: Dict[str, Any] = {"ok": True, "summaries": [], "proposals": []}
    try:
        from src.paper_summaries import sync_paper_summaries_on_complete

        summary_out = sync_paper_summaries_on_complete(owner, session_id, data)
        if summary_out.get("summaries"):
            logger.info(
                "Paper summaries for %s: %d document(s)",
                session_id,
                len(summary_out.get("summaries") or []),
            )
    except Exception as e:
        logger.warning("Paper summary pipeline failed for %s: %s", session_id, e)
        summary_out = {"ok": False, "error": str(e), "summaries": [], "proposals": []}

    all_proposals = list(graph_out.get("proposals") or []) + list(summary_out.get("proposals") or [])
    return {
        "ok": graph_out.get("ok", False) or summary_out.get("ok", False),
        "research_id": graph_out.get("research_id"),
        "proposals": all_proposals,
        "proposal_count": len(all_proposals),
        "graph": graph_out,
        "summaries": summary_out.get("summaries") or [],
        "skipped_missing": graph_out.get("skipped_missing") or [],
    }
