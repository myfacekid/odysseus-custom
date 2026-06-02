"""Read-only access to a local Obsidian vault directory on disk.

Hybrid search: keyword/BM25, frontmatter/tags, wikilink graph, vector semantic,
and optional Obsidian plugin indexes (Smart Connections, Local REST API, Omnisearch).
"""
from __future__ import annotations

import logging
import math
import os
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

DEFAULT_DAILY_NOTES_FOLDER = "Daily Notes"
DEFAULT_DAILY_NOTE_FORMAT = "%Y-%m-%d.md"
DEFAULT_VAULT_PATH = os.path.expanduser("~/Documents/Vault_1/Vault_1")
READABLE_EXTENSIONS = {".md", ".markdown", ".txt"}
SKIP_DIR_NAMES = {".obsidian", ".git", ".trash", "__pycache__"}

# Shared with tool_index keyword hints — keep in sync conceptually.
VAULT_INTENT_KEYWORDS = frozenset({
    "obsidian", "my vault", "vault note", "daily note", "daily notes",
    "meeting notes", "meeting transcript", "in my notes", "my notes folder",
    "notes folder", "permanent notes", "wikilink", "wiki link", "backlink",
    "what did i write", "find my note", "read my note", "my vault",
    "in obsidian", "obsidian folder",
    "write to my vault", "add to my note", "append to", "update my note",
    "link to note", "create a note", "daily note entry",
})


def vault_intent_in_query(query: str) -> bool:
    ql = (query or "").lower()
    return any(kw in ql for kw in VAULT_INTENT_KEYWORDS)


# Strip chat/vault boilerplate before scoring — keeps topic terms like "epistasis".
_VAULT_STOPWORDS = frozenset({
    "about", "after", "also", "been", "being", "browse", "could", "daily",
    "does", "each", "file", "files", "find", "folder", "folders", "from",
    "have", "into", "link", "linked", "links", "list", "look", "looking",
    "meeting", "meetings", "mention", "more", "most", "note", "notes",
    "obsidian", "other", "permanent", "read", "say", "search", "searching",
    "show", "some", "such", "tell", "than", "that", "their", "them", "then",
    "there", "these", "they", "this", "those", "through", "transcript",
    "transcripts", "using", "vault", "what", "when", "where", "which",
    "while", "with", "would", "write", "wrote", "your",
})

_VAULT_QUERY_STRIP_RE = re.compile(
    r"(?i)\b(?:"
    r"search(?:ing)?\s+(?:my\s+)?(?:obsidian\s+)?vault(?:\s+for|\s+about)?|"
    r"(?:look|find)(?:\s+for)?\s+(?:in\s+)?(?:my\s+)?(?:obsidian\s+)?vault|"
    r"in\s+my\s+(?:obsidian\s+)?(?:vault|notes(?:\s+folder)?)|"
    r"(?:what\s+(?:do|does)\s+)?my\s+notes\s+(?:say|mention|about)|"
    r"find(?:\s+my)?\s+note(?:s)?\s+(?:about|on|for)|"
    r"read\s+my\s+note|tell\s+me\s+about|"
    r"obsidian\s+vault|daily\s+notes?|meeting\s+(?:notes?|transcripts?)"
    r")\b[:\s]*",
)


def _vault_content_tokens(text: str) -> List[str]:
    words = re.findall(r"[a-z0-9]+(?:[-_][a-z0-9]+)*", (text or "").lower())
    return [w for w in words if len(w) >= 3 and w not in _VAULT_STOPWORDS]


def extract_vault_search_query(raw: str) -> str:
    """Reduce a chat message to the topic terms we should actually search for."""
    q = (raw or "").strip()
    if not q:
        return ""
    cleaned = _VAULT_QUERY_STRIP_RE.sub(" ", q)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,.-")
    tokens = _vault_content_tokens(cleaned)
    if tokens:
        return " ".join(tokens)
    tokens = _vault_content_tokens(q)
    if tokens:
        return " ".join(tokens)
    return cleaned or q[:120]


def _note_stem(rel: str) -> str:
    return Path(rel).stem.lower().replace("-", " ").replace("_", " ")


def _snippet_from_body(body: str, query_tokens: List[str], phrase: str) -> str:
    body_l = body.lower()
    idx = -1
    if phrase and len(phrase) >= 4:
        idx = body_l.find(phrase)
    if idx < 0:
        for tok in query_tokens:
            idx = body_l.find(tok)
            if idx >= 0:
                break
    if idx < 0:
        return body[:160].replace("\n", " ").strip()
    start = max(0, idx - 60)
    end = min(len(body), idx + max(len(phrase), max((len(t) for t in query_tokens), default=0)) + 80)
    return body[start:end].replace("\n", " ").strip()


def _bm25_score(query_tokens: List[str], doc_tokens: set, doc_len: int, avg_len: float, doc_freq: Counter) -> float:
    if not query_tokens or not doc_tokens:
        return 0.0
    score = 0.0
    k1, b = 1.5, 0.75
    N = max(doc_freq.get("__N__", 1), 1)
    for qt in query_tokens:
        if qt not in doc_tokens:
            continue
        df = doc_freq.get(qt, 0)
        idf = math.log((N - df + 0.5) / (df + 0.5) + 1)
        tf = 1.0
        tf_norm = (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * doc_len / max(avg_len, 1)))
        score += idf * tf_norm
    return score


@dataclass
class VaultConfig:
    vault_path: str
    daily_notes_folder: str = DEFAULT_DAILY_NOTES_FOLDER
    daily_note_format: str = DEFAULT_DAILY_NOTE_FORMAT

    @property
    def root(self) -> Path:
        return Path(self.vault_path).expanduser().resolve()


def resolve_vault_config(owner: str = "") -> Optional[VaultConfig]:
    """Load vault settings: per-user prefs first, then global admin settings."""
    cfg: Dict[str, str] = {}
    if owner:
        try:
            from routes.prefs_routes import _load_for_user

            user_cfg = (_load_for_user(owner) or {}).get("obsidian_vault") or {}
            if isinstance(user_cfg, dict):
                cfg.update({k: str(v).strip() for k, v in user_cfg.items() if v})
        except Exception:
            pass
    if not cfg.get("vault_path"):
        try:
            from src.settings import get_setting

            g_path = (get_setting("obsidian_vault_path") or "").strip()
            if g_path:
                cfg["vault_path"] = g_path
            if not cfg.get("daily_notes_folder"):
                g_daily = (get_setting("obsidian_daily_notes_folder") or "").strip()
                if g_daily:
                    cfg["daily_notes_folder"] = g_daily
        except Exception:
            pass
    vault_path = (cfg.get("vault_path") or DEFAULT_VAULT_PATH).strip()
    vault_path = os.path.expanduser(vault_path)
    if not vault_path:
        return None
    root = Path(vault_path)
    if not root.is_dir():
        return None
    return VaultConfig(
        vault_path=str(root.resolve()),
        daily_notes_folder=(cfg.get("daily_notes_folder") or DEFAULT_DAILY_NOTES_FOLDER).strip()
        or DEFAULT_DAILY_NOTES_FOLDER,
        daily_note_format=(cfg.get("daily_note_format") or DEFAULT_DAILY_NOTE_FORMAT).strip()
        or DEFAULT_DAILY_NOTE_FORMAT,
    )


def _resolve_within_vault(config: VaultConfig, relative: str = "") -> Tuple[Optional[Path], Optional[str]]:
    """Resolve a vault-relative path; reject escapes outside the vault root."""
    root = config.root
    rel = (relative or "").strip().replace("\\", "/").lstrip("/")
    target = (root / rel).resolve() if rel else root
    try:
        target.relative_to(root)
    except ValueError:
        return None, f"Path escapes vault root: {relative!r}"
    return target, None


def list_vault(config: VaultConfig, folder: str = "", *, include_files: bool = True) -> Dict[str, Any]:
    """List immediate children of a vault folder."""
    target, err = _resolve_within_vault(config, folder)
    if err:
        return {"error": err, "exit_code": 1}
    assert target is not None
    if not target.is_dir():
        return {"error": f"Not a folder: {folder or '/'}", "exit_code": 1}

    dirs: List[str] = []
    files: List[str] = []
    for entry in sorted(target.iterdir(), key=lambda p: p.name.lower()):
        name = entry.name
        if name.startswith(".") or name in SKIP_DIR_NAMES:
            continue
        rel = entry.relative_to(config.root).as_posix()
        if entry.is_dir():
            dirs.append(rel)
        elif include_files and entry.is_file() and entry.suffix.lower() in READABLE_EXTENSIONS:
            files.append(rel)

    prefix = folder.strip("/") if folder else "(vault root)"
    lines = [f"Vault folder: {prefix}", ""]
    if dirs:
        lines.append("**Folders:**")
        lines.extend(f"- `{d}/`" for d in dirs)
    if files:
        if dirs:
            lines.append("")
        lines.append("**Notes:**")
        lines.extend(f"- `{f}`" for f in files)
    if not dirs and not files:
        lines.append("(empty or no readable notes here)")
    return {"output": "\n".join(lines), "exit_code": 0}


def read_vault_note(config: VaultConfig, path: str, *, max_chars: int = 12000) -> Dict[str, Any]:
    """Read a single note by vault-relative path."""
    rel = (path or "").strip()
    if not rel:
        return {"error": "path is required (vault-relative, e.g. Meetings/2025-05-01.md)", "exit_code": 1}

    target, err = _resolve_within_vault(config, rel)
    if err:
        return {"error": err, "exit_code": 1}
    assert target is not None
    if not target.is_file():
        return {"error": f"Note not found: {rel}", "exit_code": 1}
    if target.suffix.lower() not in READABLE_EXTENSIONS:
        return {"error": f"Unsupported file type: {target.suffix}", "exit_code": 1}

    try:
        text = target.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return {"error": f"Could not read {rel}: {e}", "exit_code": 1}

    truncated = False
    if len(text) > max_chars:
        text = text[:max_chars]
        truncated = True

    header = f"# {rel}\n\n"
    body = header + text
    if truncated:
        body += f"\n\n… (truncated at {max_chars} characters)"
    return {"output": body, "exit_code": 0, "path": rel}


def _iter_notes(config: VaultConfig, folder: str = ""):
    root, err = _resolve_within_vault(config, folder)
    if err or root is None or not root.is_dir():
        return
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d for d in dirnames
            if not d.startswith(".") and d not in SKIP_DIR_NAMES
        ]
        for fname in filenames:
            ext = Path(fname).suffix.lower()
            if ext not in READABLE_EXTENSIONS:
                continue
            full = Path(dirpath) / fname
            try:
                rel = full.relative_to(config.root).as_posix()
            except ValueError:
                continue
            yield rel, full


def _keyword_search_vault(
    config: VaultConfig,
    query_tokens: List[str],
    phrase: str,
    folder: str,
    note_list: List[Tuple[str, Path]],
) -> Tuple[List[Tuple[float, str, str]], Dict[str, Any]]:
    """BM25 + filename scoring with frontmatter/tag/Dataview boosts."""
    from src.vault_note_parser import parse_note

    filename_scores: Dict[str, float] = {}
    full_by_rel: Dict[str, Path] = {rel: full for rel, full in note_list}
    tag_hits: Dict[str, float] = {}

    for rel, full in note_list:
        stem = _note_stem(rel)
        rel_l = rel.lower()
        score = 0.0
        if phrase and len(phrase) >= 4 and phrase in stem:
            score += 120.0
        if phrase and len(phrase) >= 4 and phrase in rel_l:
            score += 80.0
        for tok in query_tokens:
            if tok.startswith("#"):
                tok = tok[1:]
            if tok in stem:
                score += 35.0
            elif tok in rel_l:
                score += 12.0
        if query_tokens and all(t.lstrip("#") in stem or t.lstrip("#") in rel_l for t in query_tokens):
            score += 50.0
        if score > 0:
            filename_scores[rel] = score

        try:
            body = full.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        parsed = parse_note(rel, body)
        for tok in query_tokens:
            t = tok.lstrip("#").lower()
            if t in parsed.tags:
                tag_hits[rel] = tag_hits.get(rel, 0.0) + 45.0
            if any(t in _norm_alias(a) for a in parsed.aliases):
                tag_hits[rel] = tag_hits.get(rel, 0.0) + 35.0
            for fk, fv in parsed.dataview_fields.items():
                if t in fk.lower() or t in fv.lower():
                    tag_hits[rel] = tag_hits.get(rel, 0.0) + 20.0

    if len(note_list) <= 250:
        scan_rels = [rel for rel, _ in note_list]
    else:
        ranked = sorted(filename_scores.items(), key=lambda x: (-x[1], x[0].lower()))
        scan_rels = [rel for rel, _ in ranked[:80]]
        for rel, _full in note_list:
            rel_l = rel.lower()
            if any(t.lstrip("#") in rel_l for t in query_tokens):
                if rel not in scan_rels:
                    scan_rels.append(rel)
        scan_rels.extend(tag_hits.keys())
        scan_rels = list(dict.fromkeys(scan_rels))

    doc_tokens: Dict[str, set] = {}
    doc_bodies: Dict[str, str] = {}
    doc_freq: Counter = Counter()
    total_len = 0
    for rel in scan_rels:
        full = full_by_rel.get(rel)
        if full is None:
            continue
        try:
            body = full.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        parsed = parse_note(rel, body)
        tokens = set(_vault_content_tokens(f"{parsed.title} {' '.join(parsed.tags)} {parsed.body[:12000]}"))
        if not tokens:
            continue
        doc_tokens[rel] = tokens
        doc_bodies[rel] = body
        total_len += len(tokens)
        for tok in tokens:
            doc_freq[tok] += 1

    N = max(len(doc_tokens), 1)
    doc_freq["__N__"] = N
    avg_len = max(total_len / N, 1.0)

    matches: List[Tuple[float, str, str]] = []
    for rel in scan_rels:
        tokens = doc_tokens.get(rel)
        body = doc_bodies.get(rel, "")
        if not tokens:
            continue
        stem = _note_stem(rel)
        rel_l = rel.lower()
        score = filename_scores.get(rel, 0.0) + tag_hits.get(rel, 0.0)
        score += _bm25_score(query_tokens, tokens, len(tokens), avg_len, doc_freq) * 8.0

        matched = [
            t for t in query_tokens
            if t.lstrip("#") in stem or t.lstrip("#") in rel_l or t.lstrip("#") in tokens
        ]
        if not matched:
            continue
        if len(matched) < len(query_tokens):
            score *= 0.65 + 0.35 * (len(matched) / len(query_tokens))

        snippet = _snippet_from_body(body, [t.lstrip("#") for t in query_tokens], phrase) if body else ""
        matches.append((score, rel, snippet))

    aux = {"doc_bodies": doc_bodies, "tag_hits": tag_hits}
    return matches, aux


def _norm_alias(name: str) -> str:
    return name.strip().lower()


def _merge_vault_search_results(
    keyword_matches: List[Tuple[float, str, str]],
    vector_hits: List[Tuple[str, float, str]],
    plugin_hits: Dict[str, List[Tuple[str, float, str]]],
    graph_bonus: Dict[str, float],
    *,
    limit: int,
) -> List[Tuple[float, str, str, List[str]]]:
    """Merge ranked lists; return (score, rel, snippet, reasons)."""
    combined: Dict[str, Dict[str, Any]] = {}

    max_kw = max((s for s, _, _ in keyword_matches), default=1.0) or 1.0
    for score, rel, snippet in keyword_matches:
        combined.setdefault(rel, {"score": 0.0, "snippet": snippet, "reasons": []})
        combined[rel]["score"] += (score / max_kw) * 1.0
        combined[rel]["reasons"].append("keyword")
        if snippet:
            combined[rel]["snippet"] = snippet

    for rel, score, snippet in vector_hits:
        combined.setdefault(rel, {"score": 0.0, "snippet": snippet, "reasons": []})
        combined[rel]["score"] += score * 0.85
        combined[rel]["reasons"].append("semantic")
        if snippet and not combined[rel].get("snippet"):
            combined[rel]["snippet"] = snippet

    plugin_weights = {
        "smart_connections": 0.9,
        "local_rest_api": 0.95,
        "omnisearch": 0.95,
    }
    for source, hits in plugin_hits.items():
        weight = plugin_weights.get(source, 0.8)
        for rel, score, snippet in hits:
            combined.setdefault(rel, {"score": 0.0, "snippet": snippet, "reasons": []})
            combined[rel]["score"] += score * weight
            combined[rel]["reasons"].append(source.replace("_", " "))
            if snippet and not combined[rel].get("snippet"):
                combined[rel]["snippet"] = snippet

    for rel, bonus in graph_bonus.items():
        if rel not in combined:
            combined[rel] = {"score": 0.0, "snippet": "", "reasons": ["linked note"]}
        combined[rel]["score"] += bonus

    ranked = sorted(
        (
            (v["score"], rel, v.get("snippet") or "", sorted(set(v.get("reasons") or [])))
            for rel, v in combined.items()
        ),
        key=lambda x: (-x[0], x[1].lower()),
    )
    return ranked[:limit]


def search_vault_notes(
    config: VaultConfig,
    query: str = "",
    folder: str = "",
    *,
    limit: int = 15,
    owner: str = "",
    use_semantic: bool = True,
    use_plugins: bool = True,
    expand_links: bool = True,
) -> Dict[str, Any]:
    """Hybrid vault search: keyword, tags/frontmatter, semantic, plugins, wikilinks."""
    raw_q = (query or "").strip()
    if not raw_q and not folder:
        return {
            "error": "Provide a search `query` and/or a `folder` to browse.",
            "exit_code": 1,
        }

    limit = min(max(limit, 1), 30)
    search_q = extract_vault_search_query(raw_q) if raw_q else ""
    query_tokens = _vault_content_tokens(search_q or raw_q)
    phrase = (search_q or raw_q).lower().strip()

    if raw_q.startswith("#"):
        query_tokens = [raw_q.lower().lstrip("#")] + query_tokens

    if raw_q and not query_tokens:
        query_tokens = [
            t for t in re.split(r"\W+", raw_q.lower())
            if len(t) >= 4 and t not in _VAULT_STOPWORDS
        ]

    note_list = list(_iter_notes(config, folder))
    if not note_list and folder:
        scope = folder.strip("/")
        return {"output": f"No notes found — scope: {scope}", "exit_code": 0}

    if not query_tokens and not raw_q:
        matches = [(1.0, rel, "") for rel, _full in note_list]
        matches.sort(key=lambda x: x[1].lower())
        scope = folder.strip("/") if folder else "entire vault"
        lines = [f"Vault search — scope: {scope}", ""]
        for _, rel, _ in matches[:limit]:
            lines.append(f"- `{rel}`")
        return {"output": "\n".join(lines), "exit_code": 0}

    keyword_matches, _aux = _keyword_search_vault(
        config, query_tokens, phrase, folder, note_list,
    )

    vector_hits: List[Tuple[str, float, str]] = []
    if use_semantic and search_q:
        try:
            from src.vault_vector import ensure_vault_index, get_vault_vector_index

            ensure_vault_index(config, owner=owner)
            idx = get_vault_vector_index()
            if idx.healthy:
                vector_hits = idx.search(
                    search_q, config, k=limit, owner=owner, folder=folder,
                )
        except Exception as e:
            logger.debug(f"Vault semantic search skipped: {e}")

    plugin_hits: Dict[str, List[Tuple[str, float, str]]] = {}
    if use_plugins and search_q:
        try:
            from src.vault_plugins import search_plugin_sources

            plugin_hits = search_plugin_sources(config, search_q, limit=limit)
        except Exception as e:
            logger.debug(f"Vault plugin search skipped: {e}")

    graph_bonus: Dict[str, float] = {}
    if expand_links and keyword_matches:
        try:
            from src.vault_graph import VaultGraph

            graph = VaultGraph(config)
            seed_paths = [rel for _, rel, _ in keyword_matches[:5]]
            seed_paths.extend(rel for rel, _, _ in vector_hits[:3])
            neighbors = graph.neighborhood(seed_paths, hops=1)
            for rel in neighbors:
                if rel not in seed_paths:
                    graph_bonus[rel] = graph_bonus.get(rel, 0.0) + 0.25
        except Exception as e:
            logger.debug(f"Vault graph expansion skipped: {e}")

    merged = _merge_vault_search_results(
        keyword_matches, vector_hits, plugin_hits, graph_bonus, limit=limit,
    )

    scope = folder.strip("/") if folder else "entire vault"
    if not merged:
        msg = f"No notes found — scope: {scope}"
        if raw_q:
            msg += f" | query: {raw_q}"
            if search_q and search_q != raw_q:
                msg += f" (searched: {search_q})"
        return {"output": msg, "exit_code": 0}

    display_q = search_q if search_q and search_q != raw_q else raw_q
    lines = [f"Vault search — scope: {scope}"]
    if display_q:
        lines.append(f"query: {display_q}")
    sources_used = []
    if vector_hits:
        sources_used.append("semantic index")
    if plugin_hits:
        sources_used.extend(plugin_hits.keys())
    if sources_used:
        lines.append(f"sources: {', '.join(sorted(set(sources_used)))}")
    lines.append("")
    for score, rel, snippet, reasons in merged:
        line = f"- `{rel}`"
        if reasons:
            line += f" ({', '.join(reasons)})"
        if snippet:
            line += f" — …{snippet[:140]}…" if len(snippet) > 140 else f" — {snippet}"
        lines.append(line)
    return {"output": "\n".join(lines), "exit_code": 0}


def search_vault_backlinks(
    config: VaultConfig,
    path: str,
    *,
    limit: int = 20,
) -> Dict[str, Any]:
    from src.vault_graph import VaultGraph

    rel = (path or "").strip()
    if not rel:
        return {"error": "path is required", "exit_code": 1}
    graph = VaultGraph(config)
    incoming = graph.backlinks(rel)
    outgoing = graph.outgoing(rel)
    lines = [f"Links for `{rel}`", ""]
    if incoming:
        lines.append("**Backlinks:**")
        lines.extend(f"- `{p}`" for p in incoming[:limit])
    if outgoing:
        if incoming:
            lines.append("")
        lines.append("**Outgoing links:**")
        lines.extend(f"- `{p}`" for p in outgoing[:limit])
    if not incoming and not outgoing:
        lines.append("(no wikilinks found)")
    return {"output": "\n".join(lines), "exit_code": 0}


def reindex_vault_semantic(config: VaultConfig, owner: str = "") -> Dict[str, Any]:
    from src.vault_vector import get_vault_vector_index

    idx = get_vault_vector_index()
    if not idx.healthy:
        return {
            "success": False,
            "message": "Semantic index unavailable — start ChromaDB and configure embeddings.",
        }
    return idx.index_vault(config, owner=owner)


def test_vault_connection(config: VaultConfig) -> Tuple[bool, str, Optional[dict]]:
    """Verify the vault path exists and count readable notes."""
    root = config.root
    if not root.is_dir():
        return False, f"Vault folder not found: {root}", None
    note_count = 0
    folder_names: List[str] = []
    try:
        for entry in sorted(root.iterdir(), key=lambda p: p.name.lower()):
            if entry.name.startswith(".") or entry.name in SKIP_DIR_NAMES:
                continue
            if entry.is_dir():
                folder_names.append(entry.name)
        for _rel, _full in _iter_notes(config):
            note_count += 1
            if note_count >= 5000:
                break
    except OSError as e:
        return False, f"Could not scan vault: {e}", None
    sample = ", ".join(folder_names[:6])
    if len(folder_names) > 6:
        sample += ", …"
    msg = f"Vault reachable — {note_count}+ readable note(s)"
    if sample:
        msg += f" — top folders: {sample}"

    info: Dict[str, Any] = {"note_count": note_count, "folders": folder_names[:20]}
    try:
        from src.vault_plugins import detect_obsidian_plugins

        info["plugins"] = detect_obsidian_plugins(config)
    except Exception:
        pass
    try:
        from src.vault_vector import get_vault_vector_index

        info["semantic_index"] = get_vault_vector_index().stats(config)
    except Exception:
        pass
    return True, msg, info


def execute_search_vault_tool(args: dict, owner: str = "") -> Dict[str, Any]:
    """Agent tool entry: list, read, or search the user's Obsidian vault."""
    if not isinstance(args, dict):
        args = {}

    config = resolve_vault_config(owner)
    if not config:
        return {
            "output": (
                "Obsidian vault is not configured or the path does not exist. "
                "Ask the user to set the vault path under Settings → Search → Obsidian Vault "
                f"(default: {DEFAULT_VAULT_PATH})."
            ),
            "exit_code": 1,
        }

    action = (args.get("action") or "search").strip().lower().replace("-", "_")
    _ALIASES = {
        "list_folders": "list",
        "browse": "list",
        "read_note": "read",
        "get": "read",
        "find": "search",
        "write": "create",
        "new": "create",
        "add": "append",
        "edit": "patch",
        "update": "patch",
        "replace": "patch",
        "connect": "link",
        "wikilink": "link",
        "traverse": "follow",
        "graph": "follow",
        "daily": "append_daily",
    }
    action = _ALIASES.get(action, action)

    if action == "list":
        return list_vault(config, folder=(args.get("folder") or args.get("path") or ""))

    if action == "read":
        path = (args.get("path") or args.get("note") or args.get("file") or "").strip()
        try:
            max_chars = int(args.get("max_chars", 12000))
        except (TypeError, ValueError):
            max_chars = 12000
        max_chars = min(max(max_chars, 500), 50000)
        return read_vault_note(config, path, max_chars=max_chars)

    if action == "search":
        try:
            limit = int(args.get("limit", 15))
        except (TypeError, ValueError):
            limit = 15
        return search_vault_notes(
            config,
            query=(args.get("query") or args.get("q") or "").strip(),
            folder=(args.get("folder") or args.get("path") or "").strip(),
            limit=limit,
            owner=owner,
            use_semantic=str(args.get("semantic", "true")).lower() != "false",
            use_plugins=str(args.get("plugins", "true")).lower() != "false",
        )

    if action in ("backlinks", "links"):
        path = (args.get("path") or args.get("note") or args.get("file") or "").strip()
        try:
            limit = int(args.get("limit", 20))
        except (TypeError, ValueError):
            limit = 20
        return search_vault_backlinks(config, path, limit=limit)

    from src.vault_write import (
        append_daily_note,
        append_vault_note,
        create_vault_note,
        follow_vault_links,
        link_vault_notes,
        patch_vault_note,
    )

    if action == "create":
        tags = args.get("tags")
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",") if t.strip()]
        return create_vault_note(
            config,
            path=(args.get("path") or args.get("note") or "").strip(),
            title=(args.get("title") or "").strip(),
            folder=(args.get("folder") or "").strip(),
            content=(args.get("content") or args.get("body") or args.get("text") or ""),
            tags=tags if isinstance(tags, list) else None,
            owner=owner,
        )

    if action == "append":
        return append_vault_note(
            config,
            path=(args.get("path") or args.get("note") or args.get("file") or "").strip(),
            content=(args.get("content") or args.get("body") or args.get("text") or ""),
            owner=owner,
        )

    if action == "append_daily":
        return append_daily_note(
            config,
            content=(args.get("content") or args.get("body") or args.get("text") or ""),
            date=(args.get("date") or "").strip(),
            owner=owner,
        )

    if action == "patch":
        edits = args.get("edits")
        if not isinstance(edits, list):
            edits = None
        return patch_vault_note(
            config,
            path=(args.get("path") or args.get("note") or args.get("file") or "").strip(),
            find=(args.get("find") or args.get("old") or ""),
            replace=(args.get("replace") or args.get("new") or ""),
            edits=edits,
            owner=owner,
        )

    if action == "link":
        return link_vault_notes(
            config,
            from_path=(args.get("from") or args.get("from_path") or args.get("path") or "").strip(),
            to=(args.get("to") or args.get("target") or args.get("note") or "").strip(),
            alias=(args.get("alias") or "").strip(),
            heading=(args.get("heading") or "").strip(),
            at=(args.get("at") or args.get("placement") or "end"),
            owner=owner,
        )

    if action == "follow":
        try:
            depth = int(args.get("depth", 1))
        except (TypeError, ValueError):
            depth = 1
        try:
            max_notes = int(args.get("max_notes", 5))
        except (TypeError, ValueError):
            max_notes = 5
        try:
            max_chars = int(args.get("max_chars", 10000))
        except (TypeError, ValueError):
            max_chars = 10000
        return follow_vault_links(
            config,
            path=(args.get("path") or args.get("note") or args.get("file") or "").strip(),
            depth=depth,
            max_notes=max_notes,
            max_chars=max_chars,
            owner=owner,
        )

    return {
        "output": (
            "Unknown action. Use list, read, search, backlinks, follow, "
            "create, append, append_daily, patch, or link."
        ),
        "exit_code": 1,
    }


def search_vault_for_chat(query: str, owner: str = "", limit: int = 5) -> Tuple[str, List[dict]]:
    """Inject vault search hits into chat/agent preface (like search_zotero_for_chat)."""
    config = resolve_vault_config(owner)
    if not config:
        return (
            "Obsidian vault is not configured or the folder was not found. "
            "Set the vault path under Settings → Search → Obsidian Vault.",
            [],
        )
    q = (query or "").strip()
    if not q:
        listed = list_vault(config, folder="")
        return listed.get("output", ""), []

    search_q = extract_vault_search_query(q) or q
    result = search_vault_notes(config, query=search_q, limit=limit, owner=owner)
    output = result.get("output") or result.get("error") or ""
    sources: List[dict] = []
    for line in output.splitlines():
        m = re.match(r"^- `([^`]+)`", line.strip())
        if m:
            sources.append({"path": m.group(1), "title": Path(m.group(1)).name, "source": "vault"})

    # Include short excerpts from top hits so local models see actual note content.
    excerpt_parts: List[str] = []
    for src in sources[:3]:
        read = read_vault_note(config, src["path"], max_chars=2200)
        if read.get("exit_code") == 0 and read.get("output"):
            excerpt_parts.append(read["output"])
    if excerpt_parts:
        output = output + "\n\n---\n\n" + "\n\n---\n\n".join(excerpt_parts)

    return output, sources
