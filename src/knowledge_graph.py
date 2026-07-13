"""Portable knowledge graph — nodes and edges on disk, unified search.

Stores per-user ``nodes.jsonl`` and ``edges.jsonl`` under ``data/knowledge/``.
Source of truth for *links*; canonical entity data stays in SQLite / skill files.
"""
from __future__ import annotations

import json
import logging
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from src.constants import DATA_DIR, OBSIDIAN_INTEGRATION_ENABLED

from src.edge_taxonomy import (
    ALL_EDGE_KINDS,
    EDGE_OPTIONAL_FIELDS,
    INFERRED_EDGE_KINDS,
    LEGACY_MANUAL_KINDS,
    MANUAL_EDGE_KINDS,
    PIPELINE_EDGE_KINDS,
    SEMANTIC_EDGE_KINDS,
    format_edge_for_agent,
    normalize_semantic_kind,
)

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 2
KNOWLEDGE_ROOT = Path(DATA_DIR) / "knowledge"
DEBOUNCE_SEC = 0.45

_NODE_TYPES = frozenset({"task", "document", "memory", "skill", "note", "paper", "collection", "research", "project"})
_EDGE_KINDS = ALL_EDGE_KINDS
_MANUAL_EDGE_KINDS = MANUAL_EDGE_KINDS
_PIPELINE_EDGE_KINDS = PIPELINE_EDGE_KINDS
_INFERRED_EDGE_KINDS = INFERRED_EDGE_KINDS
_EDGE_OPTIONAL_FIELDS = EDGE_OPTIONAL_FIELDS

_debounce_lock = threading.Lock()
_debounce_timers: Dict[str, threading.Timer] = {}


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _owner_dir(owner: str) -> Path:
    safe = re.sub(r"[^\w.-]", "_", (owner or "default").strip()) or "default"
    return KNOWLEDGE_ROOT / "users" / safe


def _read_jsonl(path: Path) -> List[dict]:
    if not path.is_file():
        return []
    rows: List[dict] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
                if isinstance(row, dict):
                    rows.append(row)
            except json.JSONDecodeError:
                continue
    except OSError as e:
        logger.debug(f"read_jsonl {path}: {e}")
    return rows


def _write_jsonl(path: Path, rows: Iterable[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    body = "\n".join(json.dumps(r, ensure_ascii=False) for r in rows)
    if body:
        body += "\n"
    tmp.write_text(body, encoding="utf-8")
    tmp.replace(path)


def _write_manifest(owner_dir: Path, owner: str, *, node_count: int, edge_count: int) -> None:
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "owner": owner,
        "updated_at": _utc_now(),
        "node_count": node_count,
        "edge_count": edge_count,
    }
    (owner_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def node_id(node_type: str, raw_id: str) -> str:
    t = (node_type or "").strip().lower()
    rid = (raw_id or "").strip()
    if ":" in rid and rid.split(":", 1)[0] in _NODE_TYPES:
        return rid
    return f"{t}:{rid}"


def parse_node_id(full_id: str) -> Tuple[str, str]:
    raw = (full_id or "").strip()
    if ":" in raw:
        t, rest = raw.split(":", 1)
        return t.lower(), rest
    return "note", raw


@dataclass
class KnowledgeNode:
    id: str
    type: str
    title: str
    snippet: str = ""
    updated_at: str = ""
    meta: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type,
            "title": self.title,
            "snippet": self.snippet,
            "updated_at": self.updated_at or _utc_now(),
            "meta": self.meta or {},
        }


@dataclass
class KnowledgeEdge:
    fr: str
    to: str
    kind: str = "link"

    def to_dict(self) -> dict:
        return {"from": self.fr, "to": self.to, "kind": self.kind}


def load_nodes(owner: str) -> Dict[str, dict]:
    path = _owner_dir(owner) / "nodes.jsonl"
    return {n["id"]: n for n in _read_jsonl(path) if n.get("id")}


def load_edges(owner: str) -> List[dict]:
    return _read_jsonl(_owner_dir(owner) / "edges.jsonl")


def _manual_edges_path(owner: str) -> Path:
    return _owner_dir(owner) / "manual_edges.jsonl"


def _coerce_manual_edge_row(row: dict) -> Optional[dict]:
    fr, to = (row.get("from") or "").strip(), (row.get("to") or "").strip()
    if not fr or not to or fr == to:
        return None
    kind = (row.get("kind") or "relates").strip().lower()
    source = (row.get("source") or "manual").strip() or "manual"
    if kind in _PIPELINE_EDGE_KINDS:
        if kind not in _EDGE_KINDS:
            return None
    elif kind in _MANUAL_EDGE_KINDS or kind in SEMANTIC_EDGE_KINDS:
        kind = normalize_semantic_kind(kind)
    else:
        kind = "relates"
        source = "manual"
    out = {"from": fr, "to": to, "kind": kind, "source": source}
    for key in _EDGE_OPTIONAL_FIELDS:
        val = row.get(key)
        if val is not None and val != "":
            out[key] = val
    return out


def load_manual_edges(owner: str) -> List[dict]:
    rows = _read_jsonl(_manual_edges_path(owner))
    out: List[dict] = []
    for row in rows:
        coerced = _coerce_manual_edge_row(row)
        if coerced:
            out.append(coerced)
    return out


def save_manual_edges(owner: str, edges: List[dict]) -> None:
    rows = []
    seen: Set[Tuple[str, str, str]] = set()
    for row in edges:
        coerced = _coerce_manual_edge_row(row)
        if not coerced:
            continue
        key = (coerced["from"], coerced["to"], coerced["kind"])
        if key in seen:
            continue
        seen.add(key)
        rows.append(coerced)
    _write_jsonl(_manual_edges_path(owner), rows)


def _merge_edge_lists(*lists: Iterable[dict]) -> List[dict]:
    merged: List[dict] = []
    seen: Set[Tuple[str, str, str]] = set()
    for rows in lists:
        for row in rows or []:
            fr, to = (row.get("from") or "").strip(), (row.get("to") or "").strip()
            if not fr or not to or fr == to:
                continue
            kind = row.get("kind") or "relates"
            if kind not in _EDGE_KINDS:
                kind = normalize_semantic_kind(kind)
            key = (fr, to, kind)
            if key in seen:
                continue
            seen.add(key)
            merged_row = {"from": fr, "to": to, "kind": kind}
            for opt in _EDGE_OPTIONAL_FIELDS:
                if row.get(opt) not in (None, ""):
                    merged_row[opt] = row[opt]
            if row.get("source"):
                merged_row["source"] = row["source"]
            merged.append(merged_row)
    return merged


def _is_library_document(node: dict) -> bool:
    """Editor documents that appear in the Documents library (not vault markdown)."""
    if (node.get("type") or "").lower() != "document":
        return False
    meta = node.get("meta") or {}
    return meta.get("source") == "editor"


def normalize_node_id(owner: str, ref: str) -> Optional[str]:
    """Resolve a node reference to the canonical graph id."""
    raw = (ref or "").strip()
    if not raw:
        return None
    node = get_node(owner, raw)
    return node.get("id") if node else None


def _reindex_if_missing(owner: str, *refs: str) -> None:
    """Rebuild the graph when a referenced node is missing (e.g. doc just created)."""
    if not owner:
        return
    nodes = load_nodes(owner)
    if not nodes:
        rebuild_owner_graph(owner)
        return
    for ref in refs:
        if ref and not get_node(owner, ref):
            rebuild_owner_graph(owner)
            return


def _sync_edges_from_manual(owner: str) -> int:
    """Rewrite edges.jsonl from inferred edges + manual list without reloading nodes."""
    manual = load_manual_edges(owner)
    edges = load_edges(owner)
    inferred = [e for e in edges if e.get("kind") in _INFERRED_EDGE_KINDS]
    merged = _merge_edge_lists(inferred, manual)
    owner_dir = _owner_dir(owner)
    _write_jsonl(owner_dir / "edges.jsonl", merged)
    node_count = 0
    manifest_path = owner_dir / "manifest.json"
    if manifest_path.is_file():
        try:
            node_count = int(json.loads(manifest_path.read_text(encoding="utf-8")).get("node_count") or 0)
        except (json.JSONDecodeError, OSError, TypeError, ValueError):
            node_count = len(load_nodes(owner))
    else:
        node_count = len(load_nodes(owner))
    _write_manifest(owner_dir, owner, node_count=node_count, edge_count=len(merged))
    return len(merged)


def add_graph_link(
    owner: str,
    from_ref: str,
    to_ref: str,
    *,
    kind: str = "relates",
    reason: str = "",
    confidence: Optional[float] = None,
    source: str = "manual",
) -> Dict[str, Any]:
    kind = normalize_semantic_kind(kind)
    if kind not in SEMANTIC_EDGE_KINDS:
        kind = "relates"
    fr = normalize_node_id(owner, from_ref)
    to = normalize_node_id(owner, to_ref)
    if not fr or not to:
        _reindex_if_missing(owner, from_ref, to_ref)
        fr = normalize_node_id(owner, from_ref)
        to = normalize_node_id(owner, to_ref)
    if not fr or not to:
        return {"ok": False, "error": "Both nodes must exist in the graph — try Rebuild links first."}
    if fr == to:
        return {"ok": False, "error": "Cannot link a node to itself."}
    manual = load_manual_edges(owner)
    key = (fr, to, kind)
    if any((e.get("from"), e.get("to"), e.get("kind")) == key for e in manual):
        return {"ok": True, "from": fr, "to": to, "kind": kind, "duplicate": True}
    row: Dict[str, Any] = {
        "from": fr,
        "to": to,
        "kind": kind,
        "source": (source or "manual").strip() or "manual",
        "created_at": _utc_now(),
        "updated_at": _utc_now(),
    }
    reason_t = (reason or "").strip()
    if reason_t:
        row["reason"] = reason_t[:280]
    if confidence is not None:
        try:
            row["confidence"] = max(0.0, min(1.0, float(confidence)))
        except (TypeError, ValueError):
            pass
    manual.append(row)
    save_manual_edges(owner, manual)
    _sync_edges_from_manual(owner)
    _refresh_project_nodes_for_link(owner, fr, to)
    return {"ok": True, "from": fr, "to": to, "kind": kind, "reason": reason_t}


def update_graph_link(
    owner: str,
    from_ref: str,
    to_ref: str,
    *,
    kind: str = "relates",
    reason: Optional[str] = None,
    confidence: Optional[float] = None,
) -> Dict[str, Any]:
    """Update reason/confidence on an existing manual edge (same from/to/kind)."""
    kind = normalize_semantic_kind(kind)
    fr = normalize_node_id(owner, from_ref)
    to = normalize_node_id(owner, to_ref)
    if not fr or not to:
        return {"ok": False, "error": "Both nodes must exist in the graph."}
    manual = load_manual_edges(owner)
    found = False
    for row in manual:
        if row.get("from") != fr or row.get("to") != to:
            continue
        if normalize_semantic_kind(row.get("kind")) != kind:
            continue
        if reason is not None:
            reason_t = (reason or "").strip()
            if reason_t:
                row["reason"] = reason_t[:280]
            elif "reason" in row:
                del row["reason"]
        if confidence is not None:
            try:
                row["confidence"] = max(0.0, min(1.0, float(confidence)))
            except (TypeError, ValueError):
                pass
        row["updated_at"] = _utc_now()
        found = True
        break
    if not found:
        return {"ok": False, "error": "Manual link not found for update"}
    save_manual_edges(owner, manual)
    _sync_edges_from_manual(owner)
    _refresh_project_nodes_for_link(owner, fr, to)
    return {"ok": True, "from": fr, "to": to, "kind": kind, "updated": True}


def add_pipeline_edge(
    owner: str,
    from_ref: str,
    to_ref: str,
    *,
    kind: str,
    source: str,
    **metadata: Any,
) -> Dict[str, Any]:
    """Append a pipeline-maintained edge (e.g. paper → summary document)."""
    kind = (kind or "").strip().lower()
    if kind not in _PIPELINE_EDGE_KINDS:
        return {"ok": False, "error": f"Unsupported pipeline edge kind: {kind}"}
    fr = normalize_node_id(owner, from_ref)
    to = normalize_node_id(owner, to_ref)
    if not fr or not to:
        _reindex_if_missing(owner, from_ref, to_ref)
        fr = normalize_node_id(owner, from_ref)
        to = normalize_node_id(owner, to_ref)
    if not fr or not to:
        return {"ok": False, "error": "Both nodes must exist in the graph — try Rebuild links first."}
    if fr == to:
        return {"ok": False, "error": "Cannot link a node to itself."}
    row = {
        "from": fr,
        "to": to,
        "kind": kind,
        "source": (source or "").strip() or "pipeline",
    }
    for key in _EDGE_OPTIONAL_FIELDS:
        val = metadata.get(key)
        if val is not None and val != "":
            row[key] = val
    manual = load_manual_edges(owner)
    manual = [
        e for e in manual
        if not (
            e.get("from") == fr
            and e.get("to") == to
            and e.get("kind") == kind
            and (e.get("source") or "") == row["source"]
        )
    ]
    manual.append(row)
    save_manual_edges(owner, manual)
    _sync_edges_from_manual(owner)
    _refresh_project_nodes_for_link(owner, fr, to)
    return {"ok": True, "from": fr, "to": to, "kind": kind}


def find_pipeline_edge(
    owner: str,
    from_ref: str,
    *,
    kind: str,
    source: str,
) -> Optional[dict]:
    fr = normalize_node_id(owner, from_ref) or (from_ref or "").strip()
    kind_l = (kind or "").strip().lower()
    src = (source or "").strip()
    for edge in load_manual_edges(owner):
        if edge.get("from") != fr:
            continue
        if edge.get("kind") != kind_l:
            continue
        if src and (edge.get("source") or "") != src:
            continue
        return edge
    return None


def _refresh_project_nodes_for_link(owner: str, fr: str, to: str) -> None:
    """Update project graph snippets when link counts change."""
    try:
        from src.project_graph import upsert_project_node
        from src.project_workspace import get_project

        for ref in (fr, to):
            ntype, rid = parse_node_id(ref)
            if ntype != "project":
                continue
            project = get_project(owner, rid)
            if project:
                upsert_project_node(owner, project)
    except Exception as exc:
        logger.debug("Project node refresh after link change skipped: %s", exc)


def remove_graph_link(
    owner: str,
    from_ref: str,
    to_ref: str,
    *,
    kind: Optional[str] = None,
) -> Dict[str, Any]:
    fr = normalize_node_id(owner, from_ref)
    to = normalize_node_id(owner, to_ref)
    if not fr or not to:
        return {"ok": False, "error": "Node not found"}
    kind_l = (kind or "").strip().lower() or None
    if kind_l:
        kind_l = normalize_semantic_kind(kind_l)
    manual = load_manual_edges(owner)
    before = len(manual)
    manual = [
        e
        for e in manual
        if not (
            e.get("from") == fr
            and e.get("to") == to
            and (kind_l is None or normalize_semantic_kind(e.get("kind")) == kind_l)
        )
    ]
    if len(manual) == before:
        return {"ok": False, "error": "Manual link not found"}
    save_manual_edges(owner, manual)
    _sync_edges_from_manual(owner)
    _refresh_project_nodes_for_link(owner, fr, to)
    return {"ok": True, "removed": True}


def suggest_graph_link(
    owner: str,
    from_ref: str,
    to_ref: str,
    *,
    kind: str = "relates",
    reason: str = "",
) -> Dict[str, Any]:
    """Propose a manual graph link for user approval — does not write edges."""
    kind = normalize_semantic_kind(kind)
    if kind not in SEMANTIC_EDGE_KINDS:
        kind = "relates"
    reason_t = (reason or "").strip()
    if not reason_t:
        return {
            "ok": False,
            "error": "reason is required for suggest_link — one short sentence explaining the relationship.",
        }
    _reindex_if_missing(owner, from_ref, to_ref)
    fr = normalize_node_id(owner, from_ref)
    to = normalize_node_id(owner, to_ref)
    if not fr or not to:
        return {"ok": False, "error": "Both nodes must exist in the graph — search first, then suggest."}
    if fr == to:
        return {"ok": False, "error": "Cannot link a node to itself."}
    from_node = get_node(owner, fr) or {}
    to_node = get_node(owner, to) or {}
    edges = load_edges(owner)
    already = any(
        e.get("from") == fr and e.get("to") == to and e.get("kind") == kind
        for e in edges
    )
    from_title = (from_node.get("title") or fr).strip()
    to_title = (to_node.get("title") or to).strip()
    return {
        "ok": True,
        "action": "suggest_link",
        "from": fr,
        "to": to,
        "from_title": from_title,
        "to_title": to_title,
        "from_type": from_node.get("type") or "",
        "to_type": to_node.get("type") or "",
        "kind": kind,
        "reason": reason_t,
        "suggestion_id": f"{fr}|{to}|{kind}",
        "already_linked": already,
        "output": (
            f"Suggested link ({kind}): {from_title} → {to_title}"
            + (f" — {reason_t}" if reason_t else "")
            + (" (already linked)" if already else "")
        ),
    }


def save_graph(owner: str, nodes: Dict[str, dict], edges: List[dict]) -> None:
    owner_dir = _owner_dir(owner)
    _write_jsonl(owner_dir / "nodes.jsonl", nodes.values())
    _write_jsonl(owner_dir / "edges.jsonl", edges)
    _write_manifest(owner_dir, owner, node_count=len(nodes), edge_count=len(edges))


def _snippet(text: str, limit: int = 280) -> str:
    t = (text or "").strip()
    if t.startswith("---"):
        parts = t.split("---", 2)
        if len(parts) >= 3:
            t = parts[2]
    t = re.sub(r"```[\s\S]*?```", " ", t)
    t = re.sub(r"`[^`]+`", " ", t)
    t = re.sub(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]", r"\1", t)
    t = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", t)
    t = re.sub(r"^#{1,6}\s+", "", t, flags=re.M)
    t = re.sub(r"[*_~>|`-]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    if len(t) <= limit:
        return t
    return t[: limit - 1].rstrip() + "…"


def _matches_type_filter(node: dict, type_filter: Optional[str]) -> bool:
    if not type_filter:
        return True
    ntype = (node.get("type") or "").lower()
    want = type_filter.lower()
    if want == "document":
        return ntype in ("document", "note") and _is_library_document(node)
    return ntype == want


def _tokenize(query: str) -> List[str]:
    return [w for w in re.findall(r"[a-z0-9]+", (query or "").lower()) if len(w) >= 2]


def _score_node(node: dict, tokens: List[str], phrase: str) -> float:
    if not tokens and not phrase:
        return 0.0
    title = (node.get("title") or "").lower()
    snippet = (node.get("snippet") or "").lower()
    meta_s = json.dumps(node.get("meta") or {}, ensure_ascii=False).lower()
    hay = f"{title} {snippet} {meta_s}"
    score = 0.0
    if phrase and phrase in hay:
        score += 3.0
    if phrase and phrase in title:
        score += 2.0
    for tok in tokens:
        if tok in title:
            score += 2.0
        elif tok in hay:
            score += 1.0
    return score


def rebuild_owner_graph(owner: str) -> dict:
    """Full re-index from DB + skills."""
    if not owner:
        return {"ok": False, "error": "owner required"}

    nodes: Dict[str, dict] = {}
    edges: List[dict] = []
    edge_keys: Set[Tuple[str, str, str]] = set()

    def add_edge(fr: str, to: str, kind: str = "link") -> None:
        fr, to = fr.strip(), to.strip()
        if not fr or not to or fr == to:
            return
        k = kind if kind in _EDGE_KINDS else "link"
        key = (fr, to, k)
        if key in edge_keys:
            return
        edge_keys.add(key)
        edges.append(KnowledgeEdge(fr, to, k).to_dict())

    # --- Tasks ---
    try:
        from core.database import SessionLocal
        from src.one_thing import HORIZON_LABELS, list_tasks

        db = SessionLocal()
        try:
            tasks = list_tasks(db, owner, include_done=True, include_archived=False)
            for task in tasks:
                nid = node_id("task", task.id)
                meta = {
                    "horizon": task.horizon,
                    "horizon_label": HORIZON_LABELS.get(task.horizon, task.horizon),
                    "priority": task.priority,
                    "done": task.done,
                    "due_date": task.due_date,
                }
                parts = [task.text]
                if task.due_date:
                    parts.append(f"due {task.due_date}")
                nodes[nid] = KnowledgeNode(
                    id=nid,
                    type="task",
                    title=task.text,
                    snippet=_snippet(" · ".join(parts)),
                    meta=meta,
                ).to_dict()
                for pid in task.parent_ids or []:
                    add_edge(nid, node_id("task", pid), "parent")
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"Knowledge graph task index failed for {owner}: {e}")

    # --- Documents (match Documents library: active, not archived) ---
    try:
        from sqlalchemy import or_

        from core.database import Document, SessionLocal

        db = SessionLocal()
        try:
            _arch_cond = or_(Document.archived == False, Document.archived.is_(None))  # noqa: E712
            docs = (
                db.query(Document)
                .filter(Document.owner == owner)
                .filter(Document.is_active == True)  # noqa: E712
                .filter(_arch_cond)
                .order_by(Document.updated_at.desc())
                .limit(2000)
                .all()
            )
            for doc in docs:
                nid = node_id("document", doc.id)
                nodes[nid] = KnowledgeNode(
                    id=nid,
                    type="document",
                    title=(doc.title or "Untitled").strip(),
                    snippet=_snippet(doc.current_content or ""),
                    meta={
                        "source": "editor",
                        "document_id": doc.id,
                        "language": doc.language or "text",
                        "archived": bool(doc.archived),
                    },
                ).to_dict()
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"Knowledge graph document index failed for {owner}: {e}")

    # --- Memories ---
    try:
        from core.database import Memory, SessionLocal

        db = SessionLocal()
        try:
            mems = (
                db.query(Memory)
                .filter(Memory.owner == owner)
                .order_by(Memory.timestamp.desc())
                .limit(500)
                .all()
            )
            for mem in mems:
                nid = node_id("memory", mem.id)
                nodes[nid] = KnowledgeNode(
                    id=nid,
                    type="memory",
                    title=_snippet(mem.text, 80) or "Memory",
                    snippet=_snippet(mem.text),
                    meta={"category": mem.category or "fact"},
                ).to_dict()
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"Knowledge graph memory index failed for {owner}: {e}")

    # --- Skills ---
    try:
        from services.memory.skills import SkillsManager

        sm = SkillsManager(str(DATA_DIR))
        for sk in sm.load(owner):
            name = (sk.get("name") or sk.get("title") or "").strip()
            if not name:
                continue
            slug = name.lower().replace(" ", "-")
            nid = node_id("skill", slug)
            desc = (sk.get("description") or sk.get("when_to_use") or sk.get("problem") or "")
            nodes[nid] = KnowledgeNode(
                id=nid,
                type="skill",
                title=name,
                snippet=_snippet(desc),
                meta={"category": sk.get("category") or "general", "status": sk.get("status") or "draft"},
            ).to_dict()
    except Exception as e:
        logger.warning(f"Knowledge graph skill index failed for {owner}: {e}")

    # --- Vault markdown (optional — off when OBSIDIAN_INTEGRATION_ENABLED is False) ---
    if OBSIDIAN_INTEGRATION_ENABLED:
        try:
            from src.obsidian_vault import resolve_vault_config, _iter_notes
            from src.vault_note_parser import parse_note

            cfg = resolve_vault_config(owner)
            if cfg:
                note_links: Dict[str, Set[str]] = {}
                for rel, full in _iter_notes(cfg):
                    nid = node_id("document", f"vault:{rel}")
                    try:
                        text = full.read_text(encoding="utf-8", errors="replace")
                    except OSError:
                        continue
                    parsed = parse_note(rel, text)
                    title = Path(rel).stem.replace("-", " ").replace("_", " ")
                    nodes[nid] = KnowledgeNode(
                        id=nid,
                        type="document",
                        title=title,
                        snippet=_snippet(parsed.body or text),
                        meta={"source": "vault", "path": rel, "language": "markdown"},
                    ).to_dict()
                    note_links[nid] = set(parsed.wikilinks)

                stems = {
                    Path(n.get("meta", {}).get("path", "")).stem.lower(): nid
                    for nid, n in nodes.items()
                    if n.get("meta", {}).get("source") == "vault"
                }
                for src, targets in note_links.items():
                    for target in targets:
                        stem = Path(target).stem.lower() if target else ""
                        dst = stems.get(stem) or stems.get(target.lower().replace(" ", "-"))
                        if dst:
                            add_edge(src, dst, "wikilink")
        except Exception as e:
            logger.debug(f"Vault note index skipped for {owner}: {e}")

    # --- Zotero papers + collections (local metadata catalog) ---
    try:
        from src.zotero_catalog import load_catalog, load_collections

        catalog = load_catalog(owner)
        collections = load_collections(owner)
        for col in collections:
            ckey = (col.get("key") or "").strip()
            if not ckey:
                continue
            cid = node_id("collection", ckey)
            nodes[cid] = KnowledgeNode(
                id=cid,
                type="collection",
                title=(col.get("path") or col.get("name") or "Collection").strip(),
                snippet=_snippet(f"Zotero folder · {col.get('name') or ckey}"),
                meta={
                    "source": "zotero",
                    "collection_key": ckey,
                    "path": col.get("path") or "",
                    "parent": col.get("parent") or "",
                },
            ).to_dict()

        for row in catalog:
            zkey = (row.get("zotero_key") or "").strip()
            if not zkey:
                continue
            pid = node_id("paper", zkey)
            authors = (row.get("authors") or "").strip()
            year = (row.get("year") or "").strip()
            col_paths = row.get("collection_paths") or []
            byline_parts = [p for p in (authors, year) if p]
            snippet_parts = []
            if byline_parts:
                snippet_parts.append(" · ".join(byline_parts))
            if col_paths:
                snippet_parts.append(", ".join(col_paths[:3]))
            abstract = (row.get("abstract") or "").strip()
            if abstract:
                snippet_parts.append(_snippet(abstract, 120))
            nodes[pid] = KnowledgeNode(
                id=pid,
                type="paper",
                title=(row.get("title") or "Untitled").strip(),
                snippet=_snippet(" · ".join(snippet_parts) or abstract or "Zotero paper"),
                meta={
                    "source": "zotero",
                    "zotero_key": zkey,
                    "authors": authors,
                    "year": year,
                    "doi": row.get("doi") or "",
                    "item_type": row.get("item_type") or "",
                    "collection_paths": col_paths,
                    "collection_keys": row.get("collection_keys") or [],
                    "has_pdf": bool(row.get("has_pdf")),
                    "url": row.get("url") or "",
                },
            ).to_dict()
            for ckey in row.get("collection_keys") or []:
                cid = node_id("collection", ckey)
                if cid in nodes:
                    add_edge(pid, cid, "in_collection")
    except Exception as e:
        logger.debug(f"Zotero catalog index skipped for {owner}: {e}")

    try:
        from src.research_graph import index_research_nodes

        index_research_nodes(owner, nodes)
    except Exception as e:
        logger.debug(f"Research index skipped for {owner}: {e}")

    try:
        from src.project_graph import index_project_nodes

        index_project_nodes(owner, nodes)
    except Exception as e:
        logger.debug(f"Project index skipped for {owner}: {e}")

    manual = load_manual_edges(owner)
    all_edges = _merge_edge_lists(edges, manual)
    save_graph(owner, nodes, all_edges)
    return {
        "ok": True,
        "nodes": len(nodes),
        "edges": len(all_edges),
        "manual_edges": len(manual),
        "owner": owner,
    }


def schedule_rebuild(owner: str) -> None:
    """Debounced background rebuild."""
    if not owner:
        return

    def _run() -> None:
        try:
            rebuild_owner_graph(owner)
        except Exception as e:
            logger.warning(f"Knowledge graph rebuild failed for {owner}: {e}")

    with _debounce_lock:
        old = _debounce_timers.pop(owner, None)
        if old:
            old.cancel()
        timer = threading.Timer(DEBOUNCE_SEC, _run)
        _debounce_timers[owner] = timer
        timer.daemon = True
        timer.start()


def search_knowledge(
    owner: str,
    query: str = "",
    *,
    types: Optional[List[str]] = None,
    limit: int = 12,
    expand_hops: int = 0,
) -> Dict[str, Any]:
    limit = min(max(limit, 1), 30)
    type_filter = {t.lower() for t in types} if types else None
    nodes = load_nodes(owner)
    if not nodes:
        rebuild_owner_graph(owner)
        nodes = load_nodes(owner)

    tokens = _tokenize(query)
    phrase = (query or "").lower().strip()

    scored: List[Tuple[float, dict]] = []
    for node in nodes.values():
        if type_filter and not any(_matches_type_filter(node, t) for t in type_filter):
            continue
        s = _score_node(node, tokens, phrase) if (tokens or phrase) else 0.5
        if not tokens and not phrase:
            s = 0.5
        if s > 0:
            scored.append((s, node))

    scored.sort(key=lambda x: (-x[0], (x[1].get("title") or "").lower()))
    hits = [n for _, n in scored[:limit]]

    neighbor_rows: List[dict] = []
    expanded_links: List[dict] = []
    if expand_hops > 0 and hits:
        edges = load_edges(owner)
        hit_ids = {h["id"] for h in hits}
        related_ids: Set[str] = set()
        for e in edges:
            fr, to = e.get("from"), e.get("to")
            if fr in hit_ids:
                related_ids.add(to)
                expanded_links.append({
                    "node_id": to,
                    "via": fr,
                    "direction": "out",
                    "kind": e.get("kind") or "relates",
                    "reason": e.get("reason") or "",
                })
            if to in hit_ids:
                related_ids.add(fr)
                expanded_links.append({
                    "node_id": fr,
                    "via": to,
                    "direction": "in",
                    "kind": e.get("kind") or "relates",
                    "reason": e.get("reason") or "",
                })
        seen_link_nodes: Set[str] = set()
        for link in expanded_links:
            rid = link.get("node_id") or ""
            if not rid or rid in hit_ids or rid in seen_link_nodes:
                continue
            seen_link_nodes.add(rid)
            n = nodes.get(rid)
            if n:
                neighbor_rows.append(n)

    return {
        "query": query,
        "hits": hits,
        "neighbors": neighbor_rows,
        "expanded_links": expanded_links[: limit * 3],
        "total_nodes": len(nodes),
    }


def get_node(owner: str, full_id: str) -> Optional[dict]:
    raw = (full_id or "").strip()
    if not raw:
        return None
    nodes = load_nodes(owner)
    n = nodes.get(raw)
    if n:
        return n
    ntype, rid = parse_node_id(raw)
    n = nodes.get(node_id(ntype, rid))
    if n:
        return n
    # Legacy rows may omit the type prefix in stored ids.
    for candidate in nodes.values():
        cid = candidate.get("id") or ""
        if cid == raw or cid.endswith(f":{raw}") or raw.endswith(f":{cid}"):
            return candidate
    return None


def get_neighbors(
    owner: str,
    full_id: str,
    *,
    direction: str = "both",
    kinds: Optional[List[str]] = None,
) -> Dict[str, Any]:
    nodes = load_nodes(owner)
    if not nodes:
        rebuild_owner_graph(owner)
        nodes = load_nodes(owner)

    node = get_node(owner, (full_id or "").strip())
    if not node:
        return {"node": None, "outgoing": [], "incoming": []}

    kind_filter: Optional[Set[str]] = None
    if kinds:
        kind_filter = {normalize_semantic_kind(k) for k in kinds if (k or "").strip()}
        kind_filter = {k for k in kind_filter if k in SEMANTIC_EDGE_KINDS or k in _PIPELINE_EDGE_KINDS or k in LEGACY_MANUAL_KINDS or k in _INFERRED_EDGE_KINDS}

    fid = node.get("id") or node_id(*parse_node_id(full_id))
    edges = load_edges(owner)
    outgoing: List[dict] = []
    incoming: List[dict] = []

    for e in edges:
        fr, to, kind = e.get("from"), e.get("to"), e.get("kind", "relates")
        kind_norm = normalize_semantic_kind(kind, default=kind or "relates")
        if kind_filter and kind_norm not in kind_filter and (kind or "") not in kind_filter:
            continue
        if direction in ("both", "out") and fr == fid:
            target = nodes.get(to)
            outgoing.append({"edge": e, "node": target})
        if direction in ("both", "in") and to == fid:
            source = nodes.get(fr)
            incoming.append({"edge": e, "node": source})

    return {"node": node, "outgoing": outgoing, "incoming": incoming}


def read_knowledge_content(
    owner: str,
    full_id: str,
    *,
    max_chars: int = 8000,
    include_pdf: bool = False,
    section: Optional[str] = None,
) -> Dict[str, Any]:
    """Load full body for a node (from canonical store)."""
    from src.paper_retrieval import PAPER_PDF_MAX_CHARS, PAPER_SECTION_DEFAULT_MAX_CHARS

    ntype, rid = parse_node_id(full_id)
    fid = node_id(ntype, rid)
    node = get_node(owner, fid)
    if not node:
        return {"error": f"Node not found: {fid}", "exit_code": 1}

    max_chars = min(max(max_chars, 500), 50000)
    body = ""
    meta: Dict[str, Any] = {}

    if ntype == "task":
        from core.database import SessionLocal
        from src.one_thing import enrich_task_item, get_task, list_tasks

        db = SessionLocal()
        try:
            task = get_task(db, owner, rid)
            if task:
                all_tasks = list_tasks(db, owner, include_done=True, include_archived=True)
                item = enrich_task_item(task, all_tasks)
                body = json.dumps(item, indent=2, ensure_ascii=False)
        finally:
            db.close()
    elif ntype == "document":
        if rid.startswith("vault:"):
            from src.obsidian_vault import read_vault_note, resolve_vault_config

            cfg = resolve_vault_config(owner)
            vpath = rid[len("vault:"):]
            if cfg and vpath:
                read = read_vault_note(cfg, vpath, max_chars=max_chars)
                body = read.get("output") or ""
                meta = {"source": "vault", "path": vpath, "language": "markdown"}
        else:
            from core.database import Document, SessionLocal

            db = SessionLocal()
            try:
                doc = db.query(Document).filter(Document.id == rid, Document.owner == owner).first()
                if doc:
                    body = doc.current_content or ""
                    meta = {
                        "title": doc.title,
                        "language": doc.language,
                        "source": "editor",
                        "document_id": doc.id,
                    }
            finally:
                db.close()
    elif ntype == "memory":
        from core.database import Memory, SessionLocal

        db = SessionLocal()
        try:
            mem = db.query(Memory).filter(Memory.id == rid, Memory.owner == owner).first()
            if mem:
                body = mem.text or ""
                meta = {"category": mem.category}
        finally:
            db.close()
    elif ntype == "skill":
        from services.memory.skills import SkillsManager

        sm = SkillsManager(str(DATA_DIR))
        for sk in sm.load(owner):
            name = (sk.get("name") or "").strip().lower().replace(" ", "-")
            if name == rid.lower() or (sk.get("name") or "").lower().replace(" ", "-") == rid.lower():
                body = sk.get("body_extra") or sk.get("solution") or json.dumps(sk, indent=2)
                break
    elif ntype == "note":
        # Legacy index entries — treat as vault documents.
        from src.obsidian_vault import read_vault_note, resolve_vault_config

        cfg = resolve_vault_config(owner)
        if cfg:
            read = read_vault_note(cfg, rid, max_chars=max_chars)
            body = read.get("output") or ""
            meta = {"source": "vault", "path": rid, "language": "markdown"}
    elif ntype == "paper":
        from src.zotero_catalog import load_catalog
        from src.zotero_client import fetch_paper_pdf_text, fetch_paper_section_text

        row = next(
            (r for r in load_catalog(owner) if (r.get("zotero_key") or "") == rid),
            None,
        )
        if row:
            parts = [
                f"Title: {row.get('title') or 'Untitled'}",
                f"Authors: {row.get('authors') or 'Unknown'}",
                f"Year: {row.get('year') or 'n/a'}",
                f"Type: {row.get('item_type') or 'unknown'}",
                f"Zotero key: {rid}",
            ]
            if row.get("doi"):
                parts.append(f"DOI: {row['doi']}")
            if row.get("collection_paths"):
                parts.append(f"Collections: {', '.join(row['collection_paths'])}")
            if row.get("abstract"):
                parts.extend(["", "Abstract:", row["abstract"]])

            meta = {
                "source": "zotero",
                "zotero_key": rid,
                "url": row.get("url") or "",
                "has_pdf": bool(row.get("has_pdf")),
            }

            section_query = (section or "").strip()
            if not section_query and not include_pdf:
                try:
                    from src.paper_summaries import load_cached_paper_summary_body

                    cached = load_cached_paper_summary_body(owner, rid)
                    if cached and cached.get("body"):
                        parts.extend([
                            "",
                            "--- Research summary (cached from Deep Research) ---",
                            f"_Generated: {cached.get('generated_at') or 'unknown'}_",
                            "",
                            cached["body"],
                        ])
                        meta["summary_document_id"] = cached.get("document_id")
                        meta["summary_generated_at"] = cached.get("generated_at")
                        meta["summary_research_session"] = cached.get("research_session_id")
                except Exception as exc:
                    logger.debug("Cached paper summary load skipped: %s", exc)

            if section_query:
                sec_budget = max_chars if max_chars != 8000 else PAPER_SECTION_DEFAULT_MAX_CHARS
                sec_text, sec_note, sec_meta = fetch_paper_section_text(
                    owner, rid, section_query, max_chars=sec_budget,
                )
                if sec_text:
                    label = sec_meta.get("matched_label") or section_query
                    parts.extend(["", f"--- Section: {label} ---", "", sec_text])
                    meta["section"] = sec_meta.get("matched_slug") or section_query
                    meta["pdf_extracted"] = True
                    if sec_meta.get("available_sections"):
                        meta["available_sections"] = sec_meta["available_sections"]
                elif sec_note:
                    parts.extend(["", f"Section extraction: {sec_note}"])
                    meta["section_failed"] = True
                    if sec_meta.get("available_sections"):
                        meta["available_sections"] = sec_meta["available_sections"]
            elif include_pdf:
                pdf_budget = min(max(max_chars, 500), PAPER_PDF_MAX_CHARS)
                pdf_text, pdf_note = fetch_paper_pdf_text(owner, rid, max_chars=pdf_budget)
                if pdf_text:
                    parts.extend(["", "--- PDF text (from your Zotero library) ---", "", pdf_text])
                    meta["pdf_extracted"] = True
                elif pdf_note:
                    parts.extend(["", f"PDF status: {pdf_note}"])
                    meta["pdf_extracted"] = False
            else:
                parts.extend([
                    "",
                    "PDF extraction skipped (Tier 1 — abstract + metadata only). "
                    "A cached Deep Research summary appears above when available. "
                    "For a section, pass section=methods|introduction|results|discussion. "
                    "For full text, call search_knowledge read with include_pdf=true "
                    f"or search_zotero with zotero_key={rid!r} and include_pdf=true.",
                ])

            body = "\n".join(parts)
            if len(body) > max_chars:
                body = body[:max_chars] + "\n… [truncated]"
    elif ntype == "collection":
        from src.zotero_catalog import load_catalog, load_collections

        col = next((c for c in load_collections(owner) if c.get("key") == rid), None)
        papers = [
            r for r in load_catalog(owner)
            if rid in (r.get("collection_keys") or [])
        ]
        title = (col or {}).get("path") or node.get("title") or rid
        lines = [f"Zotero collection: {title}", f"Papers ({len(papers)}):", ""]
        for row in papers[:40]:
            byline = row.get("authors") or "Unknown author"
            yr = row.get("year") or ""
            lines.append(f"- {row.get('title') or 'Untitled'} ({byline}{', ' + yr if yr else ''})")
        if len(papers) > 40:
            lines.append(f"… and {len(papers) - 40} more")
        body = "\n".join(lines)
        meta = {"source": "zotero", "collection_key": rid, "path": title}
    elif ntype == "project":
        from src.project_graph import read_project_node_content

        out = read_project_node_content(owner, rid, max_chars=max_chars)
        if out.get("exit_code") != 0:
            return out
        body = out.get("output") or ""
        meta = out.get("meta") or {"type": "project", "project_id": rid}

    if not body:
        body = node.get("snippet") or ""
    if len(body) > max_chars:
        body = body[:max_chars] + "\n… [truncated]"

    return {
        "exit_code": 0,
        "id": fid,
        "type": ntype,
        "title": node.get("title"),
        "body": body,
        "meta": meta,
        "anchor": _anchor_for(node),
    }


def _anchor_for(node: dict) -> str:
    ntype = node.get("type", "")
    nid = node.get("id", "")
    _, rid = parse_node_id(nid)
    if ntype == "task":
        return f"#task-{rid}"
    if ntype == "document":
        return f"#document-{rid}"
    if ntype == "memory":
        return f"#memory-{rid}"
    if ntype == "skill":
        return f"#skill-{rid}"
    if ntype == "paper":
        return f"#paper-{rid}"
    if ntype == "collection":
        return f"#collection-{rid}"
    if ntype == "project":
        return f"#project-{rid}"
    return ""


def list_graph_summary(owner: str, *, type_filter: Optional[str] = None, limit: int = 200) -> dict:
    nodes = load_nodes(owner)
    edges = load_edges(owner)
    if not nodes:
        rebuild_owner_graph(owner)
        nodes = load_nodes(owner)
        edges = load_edges(owner)

    type_counts: dict[str, int] = {}
    for n in nodes.values():
        t = n.get("type") or "document"
        type_counts[t] = type_counts.get(t, 0) + 1

    rows = list(nodes.values())
    if type_filter:
        rows = [n for n in rows if _matches_type_filter(n, type_filter)]
    rows.sort(key=lambda n: (n.get("type", ""), (n.get("title") or "").lower()))
    rows = rows[:limit]

    return {
        "nodes": rows,
        "edge_count": len(edges),
        "node_count": len(nodes),
        "type_counts": type_counts,
        "edges_sample": edges[: min(len(edges), 500)],
    }


def format_search_for_agent(result: dict, *, include_neighbors: bool = True) -> str:
    hits = result.get("hits") or []
    neighbors = result.get("neighbors") or [] if include_neighbors else []
    if not hits and not neighbors:
        return "No knowledge graph hits."

    lines = [f"Knowledge graph — {result.get('total_nodes', '?')} nodes indexed", ""]
    for i, n in enumerate(hits, 1):
        anchor = _anchor_for(n)
        kind = n.get("type", "?")
        title = n.get("title") or n.get("id")
        snip = (n.get("snippet") or "")[:160]
        meta = n.get("meta") or {}
        extra = ""
        if kind == "task" and meta.get("horizon_label"):
            extra = f" ({meta['horizon_label']}"
            if meta.get("due_date"):
                extra += f", due {meta['due_date']}"
            extra += ")"
        link = f"[{title}]({anchor})" if anchor else title
        lines.append(f"{i}. {kind}: {link}{extra}")
        if kind == "paper":
            zkey = meta.get("zotero_key") or (n.get("id") or "").split(":", 1)[-1]
            pdf_bit = (
                "abstract/summary on read; section= or include_pdf for more"
                if meta.get("has_pdf")
                else "metadata only"
            )
            lines.append(f"   id: paper:{zkey} ({pdf_bit})")
        if snip:
            lines.append(f"   {snip}")

    if neighbors:
        lines.append("")
        lines.append("Linked neighbors:")
        expanded = result.get("expanded_links") or []
        link_by_node = {ln.get("node_id"): ln for ln in expanded if ln.get("node_id")}
        for n in neighbors[:8]:
            anchor = _anchor_for(n)
            title = n.get("title") or n.get("id")
            link = f"[{title}]({anchor})" if anchor else title
            meta = link_by_node.get(n.get("id") or "")
            if meta:
                label = format_edge_for_agent(
                    meta.get("kind"),
                    reason=meta.get("reason") or "",
                    direction=meta.get("direction") or "out",
                )
                lines.append(f"- {n.get('type')}: {link} ({label})")
            else:
                lines.append(f"- {n.get('type')}: {link}")

    lines.append("")
    lines.append(
        "For paper:… nodes, use read (abstract + cached Deep Research summary when available), "
        "section=methods|results|… for one PDF section, or include_pdf=true for full text."
    )
    return "\n".join(lines)


def execute_knowledge_tool(args: dict, owner: str = "") -> Dict[str, Any]:
    if not isinstance(args, dict):
        args = {}
    action = (args.get("action") or "search").strip().lower().replace("-", "_")

    if action == "search":
        types = args.get("types")
        if isinstance(types, str):
            types = [t.strip() for t in types.split(",") if t.strip()]
        try:
            limit = int(args.get("limit", 12))
        except (TypeError, ValueError):
            limit = 12
        try:
            hops = int(args.get("expand_hops", args.get("hops", 1)))
        except (TypeError, ValueError):
            hops = 1
        result = search_knowledge(
            owner,
            query=(args.get("query") or args.get("q") or "").strip(),
            types=types,
            limit=limit,
            expand_hops=hops,
        )
        return {"output": format_search_for_agent(result), "exit_code": 0, "result": result}

    if action in ("read", "get"):
        nid = (args.get("id") or args.get("node") or "").strip()
        if not nid:
            return {"error": "Provide id (e.g. task:uuid or document:abc)", "exit_code": 1}
        ntype, _ = parse_node_id(nid)
        is_paper = ntype == "paper"
        from src.paper_retrieval import (
            NON_PAPER_READ_DEFAULT_MAX_CHARS,
            PAPER_READ_DEFAULT_INCLUDE_PDF,
            PAPER_READ_DEFAULT_MAX_CHARS,
            PAPER_SECTION_DEFAULT_MAX_CHARS,
        )
        section_query = (args.get("section") or "").strip()
        default_max = (
            PAPER_SECTION_DEFAULT_MAX_CHARS
            if is_paper and section_query
            else (PAPER_READ_DEFAULT_MAX_CHARS if is_paper else NON_PAPER_READ_DEFAULT_MAX_CHARS)
        )
        try:
            max_chars = int(args.get("max_chars", default_max))
        except (TypeError, ValueError):
            max_chars = default_max
        raw_pdf = args.get("include_pdf")
        if raw_pdf is None:
            include_pdf = is_paper and PAPER_READ_DEFAULT_INCLUDE_PDF
        elif isinstance(raw_pdf, str):
            include_pdf = raw_pdf.lower() not in ("false", "0", "no")
        else:
            include_pdf = bool(raw_pdf)
        out = read_knowledge_content(
            owner,
            nid,
            max_chars=max_chars,
            include_pdf=include_pdf and is_paper and not section_query,
            section=section_query or None,
        )
        if out.get("exit_code") != 0:
            return out
        title = out.get("title") or nid
        body = out.get("body") or ""
        return {"output": f"# {title}\n\n{body}", "exit_code": 0}

    if action in ("neighbors", "links", "graph"):
        nid = (args.get("id") or args.get("node") or "").strip()
        if not nid:
            return {"error": "Provide id for neighbors/links", "exit_code": 1}
        kinds_arg = args.get("kinds") or args.get("kind_filter")
        kinds_list: Optional[List[str]] = None
        if isinstance(kinds_arg, str):
            kinds_list = [k.strip() for k in kinds_arg.split(",") if k.strip()]
        elif isinstance(kinds_arg, list):
            kinds_list = [str(k).strip() for k in kinds_arg if str(k).strip()]
        nb = get_neighbors(owner, nid, kinds=kinds_list)
        node = nb.get("node")
        if not node:
            return {"error": f"Node not found: {nid}", "exit_code": 1}
        include_proposed = args.get("include_proposed")
        if isinstance(include_proposed, str):
            include_proposed = include_proposed.lower() not in ("false", "0", "no")
        else:
            include_proposed = bool(include_proposed)
        lines = [f"# Links for {node.get('title')} ({node.get('id')})", ""]
        if kinds_list:
            lines.append(f"Filter: {', '.join(kinds_list)}")
            lines.append("")
        lines.append("Outgoing:")
        for row in nb.get("outgoing") or []:
            tgt = row.get("node") or {}
            edge = row.get("edge") or {}
            kind = edge.get("kind", "relates")
            reason = edge.get("reason") or ""
            anchor = _anchor_for(tgt) if tgt else ""
            title = tgt.get("title") or tgt.get("id", "?")
            label = format_edge_for_agent(kind, reason=reason, direction="out")
            if anchor:
                lines.append(f"- {label} [{title}]({anchor})")
            else:
                lines.append(f"- {label} {title}")
        lines.append("")
        lines.append("Incoming:")
        for row in nb.get("incoming") or []:
            src = row.get("node") or {}
            edge = row.get("edge") or {}
            kind = edge.get("kind", "relates")
            reason = edge.get("reason") or ""
            anchor = _anchor_for(src) if src else ""
            title = src.get("title") or src.get("id", "?")
            label = format_edge_for_agent(kind, reason=reason, direction="in")
            if anchor:
                lines.append(f"- {label} [{title}]({anchor})")
            else:
                lines.append(f"- {label} {title}")
        if include_proposed:
            from src.pending_graph_edges import format_pending_rows_for_agent, get_pending_neighbors

            pending_nb = get_pending_neighbors(owner, nid)
            prop_out = pending_nb.get("outgoing") or []
            prop_in = pending_nb.get("incoming") or []
            if prop_out or prop_in:
                lines.append("")
                lines.append("Proposed (awaiting user approval — NOT in graph yet):")
                for row in prop_out:
                    lines.extend(format_pending_rows_for_agent([row.get("proposal") or row.get("edge") or {}]))
                for row in prop_in:
                    lines.extend(format_pending_rows_for_agent([row.get("proposal") or row.get("edge") or {}]))
        lines.append("")
        lines.append(
            "Typed edges: derives_from (lineage), refutes (INHIBITORY/contradiction), "
            "supports (evidence), relates (weak), depends_on (prerequisite). "
            "Confirmed links use suggest_link with kind + reason. "
            "Set include_proposed=true to see [PROPOSED] rows still in the review queue."
        )
        return {"output": "\n".join(lines), "exit_code": 0}

    if action in ("list_pending", "manage_graph_proposals", "manage_proposals"):
        from src.pending_graph_edges import filter_pending_for_project, format_pending_rows_for_agent, load_pending_edges

        sub = (args.get("phase") or args.get("sub_action") or "list").strip().lower()
        if sub in ("clear", "dismiss_all", "reject_all"):
            rows = load_pending_edges(owner)
            project_id = (args.get("project_id") or "").strip()
            if project_id:
                rows = filter_pending_for_project(owner, project_id, rows)
            from src.pending_graph_edges import reject_proposals

            result = reject_proposals(owner, rows)
            return {
                "output": f"Dismissed {result.get('rejected', 0)} proposed connection(s) from review queue.",
                "exit_code": 0,
                **result,
            }
        rows = load_pending_edges(owner)
        project_id = (args.get("project_id") or "").strip()
        if project_id:
            rows = filter_pending_for_project(owner, project_id, rows)
        node_filter = (args.get("id") or args.get("node") or "").strip()
        if node_filter:
            rows = [r for r in rows if r.get("from") == node_filter or r.get("to") == node_filter]
        if not rows:
            return {"output": "No pending graph connection proposals.", "exit_code": 0}
        lines = [f"# Pending graph proposals ({len(rows)})", ""]
        lines.extend(format_pending_rows_for_agent(rows))
        lines.append("")
        lines.append(
            "User must accept in Connections before these become Links. "
            "Do not call link or merge_subgraph apply unless the user explicitly asks to save."
        )
        return {"output": "\n".join(lines), "exit_code": 0, "rows": rows, "count": len(rows)}

    if action == "rebuild":
        stats = rebuild_owner_graph(owner)
        if not stats.get("ok"):
            return {"error": stats.get("error", "rebuild failed"), "exit_code": 1}
        return {
            "output": f"Rebuilt knowledge graph — {stats['nodes']} nodes, {stats['edges']} edges.",
            "exit_code": 0,
        }

    if action in ("link", "add_link", "connect"):
        fr = (args.get("from") or args.get("from_id") or args.get("source") or "").strip()
        to = (args.get("to") or args.get("to_id") or args.get("target") or "").strip()
        if not fr or not to:
            return {"error": "Provide from and to node ids (e.g. task:uuid → document:uuid)", "exit_code": 1}
        kind = (args.get("kind") or "relates").strip().lower()
        reason = (args.get("reason") or "").strip()
        result = add_graph_link(owner, fr, to, kind=kind, reason=reason, source="agent")
        if not result.get("ok"):
            return {"error": result.get("error", "link failed"), "exit_code": 1}
        return {
            "output": f"Linked {result['from']} → {result['to']} ({result['kind']})",
            "exit_code": 0,
        }

    if action in ("suggest_link", "propose_link"):
        fr = (args.get("from") or args.get("from_id") or args.get("source") or "").strip()
        to = (args.get("to") or args.get("to_id") or args.get("target") or "").strip()
        if not fr or not to:
            return {"error": "Provide from and to node ids to suggest a link", "exit_code": 1}
        kind = (args.get("kind") or "relates").strip().lower()
        reason = (args.get("reason") or args.get("why") or "").strip()
        if not reason:
            return {
                "error": "reason is required for suggest_link — one short sentence explaining the relationship.",
                "exit_code": 1,
            }
        result = suggest_graph_link(owner, fr, to, kind=kind, reason=reason)
        if not result.get("ok"):
            return {"error": result.get("error", "suggest failed"), "exit_code": 1}
        if result.get("already_linked"):
            return {
                "output": result.get("output") or "Already linked.",
                "exit_code": 0,
            }
        return {
            **result,
            "output": result.get("output") or f"Suggested link: {result.get('from_title')} → {result.get('to_title')}",
            "exit_code": 0,
        }

    if action in ("unlink", "remove_link", "disconnect"):
        fr = (args.get("from") or args.get("from_id") or "").strip()
        to = (args.get("to") or args.get("to_id") or "").strip()
        if not fr or not to:
            return {"error": "Provide from and to node ids to remove the link", "exit_code": 1}
        kind = args.get("kind")
        result = remove_graph_link(owner, fr, to, kind=kind)
        if not result.get("ok"):
            return {"error": result.get("error", "unlink failed"), "exit_code": 1}
        return {"output": "Link removed.", "exit_code": 0}

    if action in ("merge_subgraph", "merge", "merge_proposals"):
        from src.graph_merge import apply_merge_proposals, format_merge_preview_for_agent, preview_merge_proposals

        phase = (args.get("phase") or args.get("sub_action") or "preview").strip().lower()
        if phase in ("apply", "confirm", "write"):
            accepted = args.get("accepted") or args.get("proposals") or args.get("rows") or []
            result = apply_merge_proposals(owner, accepted)
            if not result.get("ok"):
                return {"error": result.get("error", "merge apply failed"), "exit_code": 1}
            return {
                "output": (
                    f"Merge apply — added {result.get('applied', 0)}, "
                    f"updated {result.get('updated', 0)}, skipped {result.get('skipped', 0)}."
                ),
                "exit_code": 0,
                **result,
            }
        proposals = args.get("proposals") or args.get("edges") or args.get("links") or []
        preview = preview_merge_proposals(owner, proposals)
        if not preview.get("ok"):
            return {"error": preview.get("error", "merge preview failed"), "exit_code": 1}
        return {
            "output": format_merge_preview_for_agent(preview),
            "exit_code": 0,
            "action": "merge_subgraph",
            "phase": "preview",
            **preview,
        }

    return {
        "error": "Unknown action. Use search, read, neighbors, suggest_link, link, unlink, rebuild, merge_subgraph, list_pending.",
        "exit_code": 1,
    }
