"""Project session agent context — cwd record + linked graph summaries (Phase D4)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

DEFAULT_MAX_LINKS = 24
DEFAULT_MAX_CHARS = 4000
DEFAULT_MAX_RELATES = 8
DEFAULT_ACTIVE_FILE_CHARS = 6000

# Prefer literature/research at the top of the injected link list.
_TYPE_ORDER = {
    "research": 0,
    "paper": 1,
    "document": 2,
    "collection": 3,
    "task": 4,
    "memory": 5,
    "skill": 6,
    "note": 7,
    "project": 8,
}

# Semantic edge kinds — stronger signals first; weak `relates` capped separately.
_EDGE_KIND_ORDER = {
    "refutes": 0,
    "derives_from": 1,
    "supports": 2,
    "depends_on": 3,
    "summarizes": 4,
    "parent": 5,
    "wikilink": 6,
    "in_collection": 7,
    "relates": 8,
    "related": 8,
    "link": 9,
}


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(limit - 20, 0)].rstrip() + "\n… [truncated]"


def sanitize_active_project_file_path(raw: Optional[str]) -> Optional[str]:
    """Reject traversal / absolute paths from client-supplied editor focus."""
    if not raw or not isinstance(raw, str):
        return None
    path = raw.strip().replace("\\", "/")
    if not path or path in (".", "/"):
        return None
    if path.startswith("/"):
        return None
    parts = [p for p in path.split("/") if p]
    if any(p == ".." for p in parts):
        return None
    return "/".join(parts)


def build_project_description_block(project: dict) -> str:
    """Optional project description from the project record."""
    desc = (project.get("description") or "").strip()
    if not desc:
        return ""
    return f"**Description:** {_truncate(desc, 500)}\n\n"


def _format_link_row(edge: dict, node: Optional[dict]) -> str:
    from src.edge_taxonomy import edge_kind_label, is_inhibitory_kind, normalize_semantic_kind

    raw_kind = (edge.get("kind") or "relates").strip()
    kind = normalize_semantic_kind(raw_kind)
    kind_label = edge_kind_label(kind)
    reason = (edge.get("reason") or "").strip()
    if not node:
        to_id = (edge.get("to") or "?").strip()
        line = f"- _(missing from graph)_ `{to_id}` · _{kind_label}_"
        if reason:
            line += f" — {reason[:200]}"
        return line

    ntype = (node.get("type") or "unknown").strip()
    title = (node.get("title") or "Untitled").strip()
    nid = (node.get("id") or "").strip()
    snippet = (node.get("snippet") or "").strip()
    meta = node.get("meta") if isinstance(node.get("meta"), dict) else {}

    inhibitory = "INHIBITORY · " if is_inhibitory_kind(kind) else ""
    parts = [f"- **{title}** · `{ntype}` · `{nid}` · _{inhibitory}{kind_label}_"]
    if reason:
        parts.append(f"  _Reason:_ {reason[:240]}")
    if ntype == "research" and meta.get("research_mode_label"):
        parts[0] += f" · {meta['research_mode_label']}"
    if snippet:
        parts.append(f"  {snippet}")
    if ntype == "paper":
        zkey = meta.get("zotero_key") or meta.get("key")
        if zkey:
            parts.append(f"  Zotero key: `{zkey}`")
    return "\n".join(parts)


def _link_sort_key(row: dict) -> tuple:
    edge = row.get("edge") or {}
    node = row.get("node") or {}
    from src.edge_taxonomy import normalize_semantic_kind

    ntype = (node.get("type") or "zzz").strip()
    kind = normalize_semantic_kind(edge.get("kind"))
    title = (node.get("title") or "").lower()
    return (_EDGE_KIND_ORDER.get(kind, 50), _TYPE_ORDER.get(ntype, 99), title)


def _cap_weak_relates(rows: List[dict], *, max_relates: int = DEFAULT_MAX_RELATES) -> List[dict]:
    from src.edge_taxonomy import normalize_semantic_kind

    out: List[dict] = []
    relates_seen = 0
    for row in rows:
        kind = normalize_semantic_kind((row.get("edge") or {}).get("kind"))
        if kind == "relates":
            if relates_seen >= max_relates:
                continue
            relates_seen += 1
        out.append(row)
    return out


DEFAULT_MAX_PROPOSED = 16


def _format_proposed_row(row: dict) -> str:
    from src.edge_taxonomy import edge_kind_label

    fr = (row.get("from_title") or row.get("from") or "?").strip()
    to = (row.get("to_title") or row.get("to") or "?").strip()
    kind = edge_kind_label(row.get("kind"))
    reason = (row.get("reason") or "").strip()
    line = f"- **[PROPOSED]** `{row.get('from', '')}` → `{row.get('to', '')}` · _{kind}_ · {fr} → {to}"
    if reason:
        line += f"\n  _Reason:_ {reason[:240]}"
    src = (row.get("source") or "").strip()
    if src:
        line += f" _(source: {src})_"
    return line


def build_proposed_connections_block(
    owner: str,
    project_id: str,
    *,
    max_rows: int = DEFAULT_MAX_PROPOSED,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> str:
    """Project-linked pending edges awaiting user approval (L4 preamble)."""
    from src.pending_graph_edges import filter_pending_for_project, load_pending_edges

    rows = filter_pending_for_project(owner, project_id, load_pending_edges(owner))
    if not rows:
        return ""

    lines: List[str] = [
        "### Proposed connections (awaiting user approval)",
        "These edges are **not** in Links until the user accepts them in Connections "
        "or the Projects Links rail. Do **not** call `link` or `merge_subgraph` phase=apply to "
        "publish them — use `suggest_link` / `merge_subgraph` preview only unless the user "
        "explicitly asks to save links.\n",
    ]
    shown = rows[: max(1, max_rows)]
    for row in shown:
        lines.append(_format_proposed_row(row))
    if len(rows) > len(shown):
        lines.append(
            f"\n… and {len(rows) - len(shown)} more proposed connection(s) "
            "(Connections or Projects Links rail)."
        )
    lines.append("")
    return _truncate("\n".join(lines), max_chars)


def build_linked_knowledge_block(
    owner: str,
    project_id: str,
    *,
    max_links: int = DEFAULT_MAX_LINKS,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> str:
    """Summarize explicit graph links (breadth boundary) for the system preamble."""
    from src.project_graph import get_project_graph_links

    links = get_project_graph_links(owner, project_id)
    outgoing: List[dict] = links.get("outgoing") or []
    incoming: List[dict] = links.get("incoming") or []

    # Surface links from either direction (project→research or research→project).
    merged: List[dict] = []
    seen: set = set()
    pid = f"project:{project_id}"

    def _add(row: dict, linked_id: str) -> None:
        if not linked_id or linked_id == pid or linked_id in seen:
            return
        seen.add(linked_id)
        merged.append(row)

    for row in outgoing:
        edge = row.get("edge") or {}
        linked = (row.get("node") or {}).get("id") or edge.get("to") or ""
        _add(row, linked)
    for row in incoming:
        edge = row.get("edge") or {}
        linked = (row.get("node") or {}).get("id") or edge.get("from") or ""
        _add(row, linked)

    if not merged:
        return (
            "### Linked knowledge (breadth boundary)\n"
            "No explicit graph links yet. Use the Links rail or `search_knowledge` "
            "to connect papers, research, and documents — do not auto-import.\n\n"
        )

    def _sort_key(row: dict) -> tuple:
        return _link_sort_key(row)

    rows = _cap_weak_relates(sorted(merged, key=_sort_key))
    total_after_cap = len(rows)
    lines: List[str] = [
        "### Linked knowledge (breadth boundary)",
        "Curated graph links for this project. Typed edges include a one-line reason when set. "
        "Use `search_knowledge` read/neighbors for full bodies — linked entities below are in scope "
        "for breadth tools; unlisted disk files are not.\n",
    ]
    missing = 0
    shown = rows[: max(1, max_links)]
    for row in shown:
        edge = row.get("edge") or {}
        node = row.get("node")
        if not node:
            missing += 1
        lines.append(_format_link_row(edge, node))

    if len(rows) > max_links:
        lines.append(
            f"\n… and {len(rows) - max_links} more linked node(s) (use search_knowledge)."
        )
    elif total_after_cap < len(merged):
        skipped = len(merged) - total_after_cap
        lines.append(
            f"\n_{skipped} weak `relates` link(s) omitted from preamble (cap {DEFAULT_MAX_RELATES}). "
            "Use search_knowledge neighbors for the full list._"
        )
    if missing:
        lines.append(
            f"\n_{missing} link(s) point to nodes missing from the graph — treat as stale._"
        )

    return _truncate("\n".join(lines) + "\n\n", max_chars)


def build_project_tool_routing_block() -> str:
    """Action-oriented tool guide — which tools apply in project workspace chats."""
    return (
        "### Tool routing (project chat — follow this)\n"
        "Generic shell and unscoped file tools are **blocked** here. "
        "Use the project-scoped tools below.\n\n"
        "| User intent | Use | Do NOT use |\n"
        "|-------------|-----|------------|\n"
        "| Edit / fix / create code or text **under the project folder** | "
        "`write_project_file` | `write_file`, `edit_document`, `bash`, `python` |\n"
        "| Read a script, config, or output in the project folder | "
        "`read_project_file` | `read_file`, MCP filesystem |\n"
        "| Run a Python script in the project | `run_project_script` | `python`, `bash` |\n"
        "| Read / summarize a **linked paper** or graph item | "
        "`search_knowledge` (`action=read`, id from links below) | `web_search` for saved papers |\n"
        "| Deep research on a topic | `trigger_research` | `web_search` for \"research X\" |\n"
        "| New **Library** note, report, or article | `create_document` | `write_project_file` "
        "(unless user wants it on disk in cwd) |\n"
        "| Edit an **open Library document** (not a cwd file) | `edit_document` | "
        "`write_project_file` |\n\n"
        "**Disambiguation:**\n"
        "- \"This file\" / \"the script\" / \"fix the code\" with an **active project file** "
        "below → that relative path via `write_project_file`.\n"
        "- Project cwd = scripts, analysis code, run outputs. Library = long-form docs in "
        "Documents + Links.\n"
        "- `run_project_script` runs **saved disk content** — call `write_project_file` "
        "first if you changed the script this turn.\n"
        "- Chat attachments are for context; to change project files on disk, still use "
        "`write_project_file`.\n\n"
    )


def build_active_project_file_block(
    owner: str,
    project_id: str,
    rel_path: str,
    *,
    max_chars: int = DEFAULT_ACTIVE_FILE_CHARS,
) -> str:
    """Editor focus: which cwd file the user is looking at + optional disk preview."""
    path = (rel_path or "").strip().replace("\\", "/")
    if not path or path == ".":
        return ""

    lines: List[str] = [
        "### Active project file (editor)",
        f"The user has **`{path}`** open in the project editor.",
        "- Treat \"this file\", \"here\", \"the script\", and similar as "
        f"**`{path}`** unless they name another path under the project cwd.",
        "- Edit with **`write_project_file`** (first line = relative path, rest = full "
        "file content). Do **NOT** use `edit_document` for cwd files.",
        "- To run it: **`run_project_script`** with that path (after `write_project_file` "
        "if you edited it this turn).",
        "",
    ]

    try:
        from src.project_files import ProjectFileError, read_text_file

        payload = read_text_file(owner, project_id, path)
        content = payload.get("content") or ""
        numbered = "\n".join(
            f"{i}\t{ln}" for i, ln in enumerate(content.split("\n"), 1)
        )
        preview = _truncate(numbered, max_chars - 200)
        lines.extend([
            "Preview (from disk; line numbers for reference):",
            f"```\n{preview}\n```",
            "",
        ])
    except Exception as exc:
        lines.append(
            f"_(Could not load preview for `{path}`: {exc}. "
            "Use `read_project_file` before editing.)_"
        )
        lines.append("")

    return "\n".join(lines)


def build_project_session_preamble(
    owner: str,
    project_id: str,
    project: dict,
    *,
    active_file_path: Optional[str] = None,
) -> str:
    """Full project workspace block for agent system prompt (dynamic per request)."""
    title = (project.get("title") or project_id).strip()
    wd = (project.get("working_dir") or "").strip() or "(unknown)"
    status = (project.get("working_dir_status") or "ok").strip()

    header = (
        "## Project workspace session\n"
        f"Project: **{title}** (`{project_id}`)\n"
        f"Working directory (depth boundary): `{wd}`"
        + (f" — status: {status}" if status != "ok" else "")
        + "\n\n"
        + build_project_description_block(project)
        + build_linked_knowledge_block(owner, project_id)
        + build_proposed_connections_block(owner, project_id)
        + build_project_tool_routing_block()
        + build_active_project_file_block(owner, project_id, active_file_path or "")
        + "### Three file paradigms (follow strictly)\n"
        "| Kind | Boundary | Agent tools |\n"
        "|------|----------|-------------|\n"
        "| Project cwd files | Depth | `read_project_file`, `write_project_file`, "
        "`run_project_script` |\n"
        "| Library documents | Breadth | `create_document`, `edit_document` — "
        "for notes/reports/articles in the Library |\n"
        "| Graph links | Breadth | `search_knowledge`, research tools, Zotero — "
        "literature and linked entities |\n\n"
        "**Rule of thumb:** scripts, analysis code, and generated outputs → cwd "
        "(`write_project_file`). Long-form Library content → document tools "
        "(optionally link the doc to this project). Literature → graph / Zotero / "
        "research tools.\n\n"
        "**Run discipline:** `run_project_script` executes the saved file on disk — "
        "always `write_project_file` first if you changed the script in this turn. "
        "The user's Run panel prompts on unsaved editor buffers; you must save via "
        "the write tool.\n\n"
        "Do NOT use `bash`, `python`, `read_file`, `write_file`, or MCP filesystem "
        "tools for project files — they are blocked in project chats.\n\n"
    )
    return header
