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

from src.constants import DATA_DIR

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
KNOWLEDGE_ROOT = Path(DATA_DIR) / "knowledge"
DEBOUNCE_SEC = 0.45

_NODE_TYPES = frozenset({"task", "document", "memory", "skill", "note"})
_EDGE_KINDS = frozenset({"parent", "link", "wikilink", "related", "supports"})

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
        return ntype in ("document", "note")
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
    """Full re-index from DB + skills (+ optional vault notes)."""
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

    # --- Documents ---
    try:
        from core.database import Document, SessionLocal

        db = SessionLocal()
        try:
            docs = (
                db.query(Document)
                .filter(Document.owner == owner, Document.archived == False)  # noqa: E712
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
                    meta={"language": doc.language or "text", "archived": bool(doc.archived)},
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

    # --- Vault markdown (indexed as documents — same conceptual bucket as editor docs) ---
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

    save_graph(owner, nodes, edges)
    return {"ok": True, "nodes": len(nodes), "edges": len(edges), "owner": owner}


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
    if expand_hops > 0 and hits:
        edges = load_edges(owner)
        hit_ids = {h["id"] for h in hits}
        related_ids: Set[str] = set()
        for e in edges:
            fr, to = e.get("from"), e.get("to")
            if fr in hit_ids:
                related_ids.add(to)
            if to in hit_ids:
                related_ids.add(fr)
        for rid in sorted(related_ids - hit_ids)[: limit * 2]:
            n = nodes.get(rid)
            if n:
                neighbor_rows.append(n)

    return {
        "query": query,
        "hits": hits,
        "neighbors": neighbor_rows,
        "total_nodes": len(nodes),
    }


def get_node(owner: str, full_id: str) -> Optional[dict]:
    nodes = load_nodes(owner)
    n = nodes.get(full_id)
    if n:
        return n
    ntype, rid = parse_node_id(full_id)
    return nodes.get(node_id(ntype, rid))


def get_neighbors(
    owner: str,
    full_id: str,
    *,
    direction: str = "both",
) -> Dict[str, Any]:
    ntype, rid = parse_node_id(full_id)
    fid = node_id(ntype, rid)
    nodes = load_nodes(owner)
    node = nodes.get(fid)
    if not node:
        return {"node": None, "outgoing": [], "incoming": []}

    edges = load_edges(owner)
    outgoing: List[dict] = []
    incoming: List[dict] = []

    for e in edges:
        fr, to, kind = e.get("from"), e.get("to"), e.get("kind", "link")
        if direction in ("both", "out") and fr == fid:
            target = nodes.get(to)
            outgoing.append({"edge": e, "node": target})
        if direction in ("both", "in") and to == fid:
            source = nodes.get(fr)
            incoming.append({"edge": e, "node": source})

    return {"node": node, "outgoing": outgoing, "incoming": incoming}


def read_knowledge_content(owner: str, full_id: str, *, max_chars: int = 8000) -> Dict[str, Any]:
    """Load full body for a node (from canonical store)."""
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
                    meta = {"title": doc.title, "language": doc.language, "source": "editor"}
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
    return ""


def list_graph_summary(owner: str, *, type_filter: Optional[str] = None, limit: int = 200) -> dict:
    nodes = load_nodes(owner)
    edges = load_edges(owner)
    if not nodes:
        rebuild_owner_graph(owner)
        nodes = load_nodes(owner)
        edges = load_edges(owner)

    rows = list(nodes.values())
    if type_filter:
        rows = [n for n in rows if _matches_type_filter(n, type_filter)]
    rows.sort(key=lambda n: (n.get("type", ""), (n.get("title") or "").lower()))
    rows = rows[:limit]

    return {
        "nodes": rows,
        "edge_count": len(edges),
        "node_count": len(nodes),
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
        if snip:
            lines.append(f"   {snip}")

    if neighbors:
        lines.append("")
        lines.append("Linked neighbors:")
        for n in neighbors[:8]:
            anchor = _anchor_for(n)
            title = n.get("title") or n.get("id")
            link = f"[{title}]({anchor})" if anchor else title
            lines.append(f"- {n.get('type')}: {link}")

    lines.append("")
    lines.append("Use read_knowledge with id for full content.")
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
        try:
            max_chars = int(args.get("max_chars", 8000))
        except (TypeError, ValueError):
            max_chars = 8000
        out = read_knowledge_content(owner, nid, max_chars=max_chars)
        if out.get("exit_code") != 0:
            return out
        title = out.get("title") or nid
        body = out.get("body") or ""
        return {"output": f"# {title}\n\n{body}", "exit_code": 0}

    if action in ("neighbors", "links", "graph"):
        nid = (args.get("id") or args.get("node") or "").strip()
        if not nid:
            return {"error": "Provide id for neighbors/links", "exit_code": 1}
        nb = get_neighbors(owner, nid)
        node = nb.get("node")
        if not node:
            return {"error": f"Node not found: {nid}", "exit_code": 1}
        lines = [f"# Links for {node.get('title')} ({node.get('id')})", ""]
        lines.append("Outgoing:")
        for row in nb.get("outgoing") or []:
            tgt = row.get("node") or {}
            kind = (row.get("edge") or {}).get("kind", "link")
            anchor = _anchor_for(tgt) if tgt else ""
            title = tgt.get("title") or tgt.get("id", "?")
            lines.append(f"- [{kind}] [{title}]({anchor})" if anchor else f"- [{kind}] {title}")
        lines.append("")
        lines.append("Incoming:")
        for row in nb.get("incoming") or []:
            src = row.get("node") or {}
            kind = (row.get("edge") or {}).get("kind", "link")
            anchor = _anchor_for(src) if src else ""
            title = src.get("title") or src.get("id", "?")
            lines.append(f"- [{kind}] [{title}]({anchor})" if anchor else f"- [{kind}] {title}")
        return {"output": "\n".join(lines), "exit_code": 0}

    if action == "rebuild":
        stats = rebuild_owner_graph(owner)
        if not stats.get("ok"):
            return {"error": stats.get("error", "rebuild failed"), "exit_code": 1}
        return {
            "output": f"Rebuilt knowledge graph — {stats['nodes']} nodes, {stats['edges']} edges.",
            "exit_code": 0,
        }

    return {
        "error": "Unknown action. Use search, read, neighbors, rebuild.",
        "exit_code": 1,
    }
