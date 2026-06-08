"""Knowledge graph integration for project workspaces (Phase A)."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from src.project_paths import WORKING_DIR_OK
from src.project_workspace import PROJECTS_ROOT, _safe_owner

logger = logging.getLogger(__name__)


def project_node_id(project_id: str) -> str:
    from src.knowledge_graph import node_id

    return node_id("project", (project_id or "").strip())


def project_node_dict(project: dict, *, link_count: int = 0) -> dict:
    from src.knowledge_graph import KnowledgeNode, _snippet, node_id

    pid = (project.get("id") or "").strip()
    title = (project.get("title") or "Untitled project").strip()
    status = (project.get("working_dir_status") or "").strip()
    wd = (project.get("working_dir") or "").strip()
    snippet_parts = []
    if status and status != WORKING_DIR_OK:
        snippet_parts.append(f"cwd {status}")
    elif wd:
        snippet_parts.append(wd)
    if link_count:
        snippet_parts.append(f"{link_count} link(s)")

    return KnowledgeNode(
        id=node_id("project", pid),
        type="project",
        title=title[:200],
        snippet=_snippet(" · ".join(snippet_parts) or "Project workspace"),
        meta={
            "source": "user",
            "project_id": pid,
            "working_dir": wd,
            "working_dir_status": status,
            "description": (project.get("description") or "").strip()[:500],
            "created_at": project.get("created_at") or 0,
            "updated_at": project.get("updated_at") or 0,
        },
    ).to_dict()


def _count_outgoing_links(owner: str, full_id: str) -> int:
    from src.knowledge_graph import load_edges

    return sum(1 for e in load_edges(owner) if e.get("from") == full_id)


def upsert_project_node(owner: str, project: dict) -> None:
    """Upsert a project node into the owner's knowledge graph."""
    from src.knowledge_graph import load_edges, load_nodes, save_graph

    if not owner or not project:
        return
    pid = (project.get("id") or "").strip()
    if not pid or project.get("archived"):
        return

    nid = project_node_id(pid)
    link_count = _count_outgoing_links(owner, nid)
    node = project_node_dict(project, link_count=link_count)
    nodes = load_nodes(owner)
    edges = load_edges(owner)
    nodes[nid] = node
    save_graph(owner, nodes, edges)


def delete_project_node(owner: str, project_id: str) -> None:
    """Remove a project node from the knowledge graph."""
    from src.knowledge_graph import load_edges, load_nodes, save_graph

    if not owner or not project_id:
        return
    nid = project_node_id(project_id)
    nodes = load_nodes(owner)
    if nid not in nodes:
        return
    nodes.pop(nid, None)
    edges = [e for e in load_edges(owner) if e.get("from") != nid and e.get("to") != nid]
    save_graph(owner, nodes, edges)


def index_project_nodes(owner: str, nodes: Dict[str, dict]) -> None:
    """Merge project records into *nodes* during graph rebuild."""
    if not owner or not PROJECTS_ROOT.is_dir():
        return
    owner_dir = PROJECTS_ROOT / _safe_owner(owner)
    if not owner_dir.is_dir():
        return
    for path in owner_dir.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        if (data.get("owner") or "") != (owner or ""):
            continue
        if data.get("archived"):
            continue
        pid = (data.get("id") or path.stem).strip()
        if not pid:
            continue
        nid = project_node_id(pid)
        link_count = _count_outgoing_links(owner, nid)
        nodes[nid] = project_node_dict({**data, "id": pid}, link_count=link_count)


def get_project_graph_links(owner: str, project_id: str) -> Dict[str, Any]:
    """Return neighbors for a project node (breadth links).

    Outgoing and incoming manual links are both surfaced so research linked
    from either direction appears in the workspace links rail.
    """
    from src.knowledge_graph import get_neighbors

    assert_project_exists(owner, project_id)
    return get_neighbors(owner, project_node_id(project_id))


def ensure_graph_node_for_link(owner: str, ref: str) -> None:
    """Ensure a link target exists in the graph (research JSON → node upsert)."""
    from src.knowledge_graph import get_node, parse_node_id

    raw = (ref or "").strip()
    if not raw or get_node(owner, raw):
        return
    ntype, rid = parse_node_id(raw)
    if ntype != "research" or not rid:
        return
    import json
    from src.research_handler import RESEARCH_DATA_DIR

    path = RESEARCH_DATA_DIR / f"{rid}.json"
    if not path.is_file():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if (data.get("owner") or "") != owner:
        return
    from src.research_graph import upsert_research_node

    upsert_research_node(owner, rid, data)


def assert_project_exists(owner: str, project_id: str) -> None:
    from src.project_workspace import ProjectNotFoundError, assert_project_owner

    assert_project_owner(owner, project_id)


def read_project_node_content(owner: str, project_id: str, *, max_chars: int = 8000) -> Dict[str, Any]:
    """Summarize a project for agent/knowledge content reads."""
    from src.project_paths import working_dir_warning
    from src.project_workspace import assert_project_owner, refresh_working_dir_status

    project = refresh_working_dir_status(assert_project_owner(owner, project_id))
    nid = project_node_id(project_id)
    body = json.dumps(
        {
            "id": project.get("id"),
            "title": project.get("title"),
            "description": project.get("description"),
            "working_dir": project.get("working_dir"),
            "working_dir_status": project.get("working_dir_status"),
            "working_dir_warning": working_dir_warning(project.get("working_dir") or ""),
        },
        indent=2,
        ensure_ascii=False,
    )
    if len(body) > max_chars:
        body = body[: max_chars - 20] + "\n… [truncated]"
    return {
        "output": body,
        "exit_code": 0,
        "node_id": nid,
        "meta": {"type": "project", "project_id": project_id},
    }
