"""Write and wikilink-aware edit operations for the Obsidian vault."""
from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.obsidian_vault import VaultConfig, _resolve_within_vault, read_vault_note
from src.vault_graph import VaultGraph
from src.vault_note_parser import parse_frontmatter, parse_note

logger = logging.getLogger(__name__)

_PROTECTED_PREFIXES = (".obsidian/", ".git/", ".trash/")


def _normalize_note_path(path: str, *, default_folder: str = "") -> str:
    rel = (path or "").strip().replace("\\", "/").lstrip("/")
    if default_folder and rel and "/" not in rel:
        rel = f"{default_folder.strip('/')}/{rel}"
    if rel and not rel.lower().endswith((".md", ".markdown", ".txt")):
        rel += ".md"
    return rel


def _resolve_write_path(config: VaultConfig, relative: str) -> Tuple[Optional[Path], Optional[str], Optional[str]]:
    """Return (absolute_path, vault_relative_path, error_message)."""
    rel = _normalize_note_path(relative)
    if not rel:
        return None, None, "path is required"
    rel_l = rel.lower()
    if rel_l.startswith(".") or any(rel_l.startswith(p) for p in _PROTECTED_PREFIXES):
        return None, None, f"Cannot write to protected path: {rel}"
    target, err = _resolve_within_vault(config, rel)
    if err:
        return None, None, err
    assert target is not None
    try:
        target.parent.relative_to(config.root)
    except ValueError:
        return None, None, "Path escapes vault root"
    return target, rel, None


def _format_wikilink(title: str, alias: str = "", heading: str = "") -> str:
    name = (title or "").strip()
    if not name:
        return ""
    if heading:
        name = f"{name}#{heading.strip()}"
    if alias and alias.strip() and alias.strip() != title.strip():
        return f"[[{name}|{alias.strip()}]]"
    return f"[[{name}]]"


def _after_write(config: VaultConfig, rel_path: str, owner: str = "") -> None:
    try:
        from src.vault_vector import reindex_vault_note

        reindex_vault_note(config, rel_path, owner=owner)
    except Exception as e:
        logger.debug(f"Post-write vector reindex skipped: {e}")


def create_vault_note(
    config: VaultConfig,
    *,
    path: str = "",
    title: str = "",
    folder: str = "",
    content: str = "",
    tags: Optional[List[str]] = None,
    owner: str = "",
) -> Dict[str, Any]:
    rel = _normalize_note_path(path or title, default_folder=folder)
    if not rel:
        return {"error": "path or title is required", "exit_code": 1}

    target, rel, err = _resolve_write_path(config, rel)
    if err:
        return {"error": err, "exit_code": 1}
    assert target is not None and rel is not None

    if target.exists():
        return {"error": f"Note already exists: {rel}", "exit_code": 1}

    body = (content or "").strip()
    if not body:
        stem = Path(rel).stem
        body = f"# {stem}\n\n"

    fm_lines: List[str] = []
    if tags:
        clean = [t.lstrip("#").strip() for t in tags if str(t).strip()]
        if clean:
            fm_lines.append("tags: [" + ", ".join(clean) + "]")
    if fm_lines:
        text = "---\n" + "\n".join(fm_lines) + "\n---\n\n" + body
    else:
        text = body

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    _after_write(config, rel, owner=owner)

    link_hint = f"Link from other notes with `{_format_wikilink(Path(rel).stem)}`."
    return {
        "output": f"Created `{rel}` ({len(text)} chars). {link_hint}",
        "exit_code": 0,
        "path": rel,
        "wikilink": _format_wikilink(Path(rel).stem),
    }


def append_vault_note(
    config: VaultConfig,
    path: str,
    content: str,
    *,
    owner: str = "",
    separator: str = "\n\n",
) -> Dict[str, Any]:
    target, rel, err = _resolve_write_path(config, path)
    if err or not rel:
        return {"error": err or "invalid path", "exit_code": 1}
    assert target is not None

    chunk = (content or "").rstrip()
    if not chunk:
        return {"error": "content is required", "exit_code": 1}

    if not target.exists():
        return create_vault_note(config, path=rel, content=chunk, owner=owner)

    existing = target.read_text(encoding="utf-8", errors="replace")
    updated = existing.rstrip() + separator + chunk + "\n"
    target.write_text(updated, encoding="utf-8")
    _after_write(config, rel, owner=owner)
    return {
        "output": f"Appended to `{rel}` (+{len(chunk)} chars).",
        "exit_code": 0,
        "path": rel,
    }


def patch_vault_note(
    config: VaultConfig,
    path: str,
    *,
    find: str = "",
    replace: str = "",
    edits: Optional[List[dict]] = None,
    owner: str = "",
) -> Dict[str, Any]:
    target, rel, err = _resolve_write_path(config, path)
    if err or not rel:
        return {"error": err or "invalid path", "exit_code": 1}
    if target is None or not target.is_file():
        return {"error": f"Note not found: {path}", "exit_code": 1}

    pairs: List[Tuple[str, str]] = []
    if edits:
        for ed in edits:
            if not isinstance(ed, dict):
                continue
            f = str(ed.get("find") or ed.get("old") or "")
            r = str(ed.get("replace") or ed.get("new") or "")
            if f:
                pairs.append((f, r))
    elif find:
        pairs.append((find, replace))

    if not pairs:
        return {"error": "Provide find/replace or edits list", "exit_code": 1}

    text = target.read_text(encoding="utf-8", errors="replace")
    applied = 0
    for f, r in pairs:
        if f not in text:
            continue
        text = text.replace(f, r, 1)
        applied += 1

    if applied == 0:
        return {"error": "No find strings matched — read the note first", "exit_code": 1}

    target.write_text(text, encoding="utf-8")
    _after_write(config, rel, owner=owner)
    return {
        "output": f"Patched `{rel}` — {applied} replacement(s).",
        "exit_code": 0,
        "path": rel,
        "replacements": applied,
    }


def link_vault_notes(
    config: VaultConfig,
    *,
    from_path: str,
    to: str,
    alias: str = "",
    heading: str = "",
    at: str = "end",
    owner: str = "",
) -> Dict[str, Any]:
    """Insert a wikilink from one note to another (creates graph edge)."""
    src_target, src_rel, err = _resolve_write_path(config, from_path)
    if err or not src_rel:
        return {"error": err or "invalid from_path", "exit_code": 1}
    if src_target is None or not src_target.is_file():
        return {"error": f"Source note not found: {from_path}", "exit_code": 1}

    graph = VaultGraph(config)
    to_rel = graph.resolve_link(to, src_rel)
    if not to_rel and ("/" in to or to.endswith(".md")):
        _t, to_rel, _e = _resolve_write_path(config, to)
    to_stem = Path(to_rel or to).stem
    wikilink = _format_wikilink(to_stem, alias=alias, heading=heading)
    if not wikilink:
        return {"error": "Could not resolve target note title", "exit_code": 1}

    text = src_target.read_text(encoding="utf-8", errors="replace")
    if wikilink in text or f"[[{to_stem}]]" in text:
        return {
            "output": f"Link already present in `{src_rel}` → `{to_stem}`.",
            "exit_code": 0,
            "path": src_rel,
            "wikilink": wikilink,
        }

    insertion = wikilink
    at_l = (at or "end").lower()
    if at_l == "end":
        text = text.rstrip() + f"\n\nRelated: {insertion}\n"
    elif at_l == "start":
        _fm, body = parse_frontmatter(text)
        if _fm:
            fm_block = "---\n" + "\n".join(f"{k}: {v}" for k, v in _fm.items()) + "\n---\n\n"
            text = fm_block + insertion + "\n\n" + body.lstrip()
        else:
            text = insertion + "\n\n" + text.lstrip()
    else:
        text = text.rstrip() + f"\n\n{insertion}\n"

    src_target.write_text(text, encoding="utf-8")
    _after_write(config, src_rel, owner=owner)

    if to_rel and not (config.root / to_rel).exists():
        hint = f" Target `{to_rel}` not found yet — create it or the link may stay unresolved in Obsidian."
    elif to_rel:
        hint = f" Linked to `{to_rel}`."
    else:
        hint = f" Linked to note title `{to_stem}`."
    return {
        "output": f"Added {wikilink} to `{src_rel}`.{hint}",
        "exit_code": 0,
        "path": src_rel,
        "wikilink": wikilink,
        "target": to_rel,
    }


def follow_vault_links(
    config: VaultConfig,
    path: str,
    *,
    depth: int = 1,
    max_notes: int = 5,
    max_chars: int = 10000,
    owner: str = "",
) -> Dict[str, Any]:
    """Read a note and follow wikilinks — graph-aware context for the agent."""
    rel = _normalize_note_path(path)
    if not rel:
        return {"error": "path is required", "exit_code": 1}

    read_root = read_vault_note(config, rel, max_chars=max_chars)
    if read_root.get("exit_code") != 0:
        return read_root

    graph = VaultGraph(config)
    depth = min(max(depth, 0), 3)
    max_notes = min(max(max_notes, 1), 12)

    visited: List[str] = [rel]
    frontier = [rel]
    sections = [read_root.get("output") or ""]

    for _ in range(depth):
        nxt: List[str] = []
        for cur in frontier:
            for linked in graph.outgoing(cur):
                if linked in visited or len(visited) >= max_notes:
                    continue
                sub = read_vault_note(config, linked, max_chars=max(2000, max_chars // max_notes))
                if sub.get("exit_code") == 0:
                    visited.append(linked)
                    sections.append(sub.get("output") or "")
                    nxt.append(linked)
            if len(visited) >= max_notes:
                break
        frontier = nxt
        if not frontier:
            break

    back = graph.backlinks(rel)
    out_links = graph.outgoing(rel)
    nav_lines = [
        f"# Link map for `{rel}`",
        "",
        "**Outgoing:** " + (", ".join(f"`[[{Path(p).stem}]]`" for p in out_links) if out_links else "(none)"),
        "**Backlinks:** " + (", ".join(f"`[[{Path(p).stem}]]`" for p in back) if back else "(none)"),
        "",
        f"Followed {len(visited)} note(s) (depth={depth}). Use `action=link` to connect notes, `action=append`/`patch` to write.",
        "",
        "---",
        "",
    ]
    body = "\n\n---\n\n".join(sections)
    return {
        "output": "\n".join(nav_lines) + body,
        "exit_code": 0,
        "path": rel,
        "visited": visited,
        "outgoing": out_links,
        "backlinks": back,
    }


def daily_vault_note_path(config: VaultConfig, date: Optional[str] = None) -> str:
    fmt = config.daily_note_format or "%Y-%m-%d.md"
    folder = (config.daily_notes_folder or "Daily Notes").strip("/")
    if date:
        try:
            dt = datetime.fromisoformat(date.replace("Z", "+00:00")[:10])
        except ValueError:
            dt = datetime.strptime(date[:10], "%Y-%m-%d")
    else:
        dt = datetime.now()
    fname = dt.strftime(fmt)
    if not fname.lower().endswith(".md"):
        fname += ".md"
    return f"{folder}/{fname}"


def append_daily_note(
    config: VaultConfig,
    content: str,
    *,
    date: str = "",
    owner: str = "",
) -> Dict[str, Any]:
    rel = daily_vault_note_path(config, date or None)
    target, resolved, err = _resolve_write_path(config, rel)
    if err or not resolved:
        return {"error": err or "invalid daily note path", "exit_code": 1}
    assert target is not None
    if not target.exists():
        stem = Path(resolved).stem
        create = create_vault_note(
            config,
            path=resolved,
            content=f"# {stem}\n\n{content.strip()}\n",
            owner=owner,
        )
        return create
    return append_vault_note(config, resolved, content, owner=owner)
