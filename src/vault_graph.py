"""Obsidian wikilink graph: resolve links, backlinks, neighborhood expansion."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, Any

from src.obsidian_vault import VaultConfig, _iter_notes
from src.vault_note_parser import parse_note

logger = logging.getLogger(__name__)


def _norm_name(name: str) -> str:
    return name.strip().lower().replace("-", " ").replace("_", " ")


class VaultGraph:
    """In-memory wikilink graph for one vault."""

    def __init__(self, config: VaultConfig):
        self.config = config
        self._by_stem: Dict[str, str] = {}
        self._by_norm: Dict[str, List[str]] = {}
        self._outgoing: Dict[str, Set[str]] = {}
        self._incoming: Dict[str, Set[str]] = {}
        self._aliases: Dict[str, str] = {}
        self._built = False

    def build(self) -> None:
        if self._built:
            return
        parsed_by_rel: Dict[str, Any] = {}
        for rel, full in _iter_notes(self.config):
            stem = Path(rel).stem
            norm = _norm_name(stem)
            self._by_stem[stem.lower()] = rel
            self._by_norm.setdefault(norm, []).append(rel)
            self._outgoing.setdefault(rel, set())
            self._incoming.setdefault(rel, set())
            try:
                text = full.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            parsed = parse_note(rel, text)
            parsed_by_rel[rel] = parsed
            for alias in parsed.aliases:
                self._aliases[_norm_name(alias)] = rel

        for rel, parsed in parsed_by_rel.items():
            for target in parsed.wikilinks:
                resolved = self._resolve_link(target, rel)
                if resolved and resolved != rel:
                    self._outgoing.setdefault(rel, set()).add(resolved)
                    self._incoming.setdefault(resolved, set()).add(rel)
        self._built = True

    def resolve_link(self, target: str, source_rel: str = "") -> Optional[str]:
        self.build()
        return self._resolve_link(target, source_rel)

    def _resolve_link(self, target: str, source_rel: str = "") -> Optional[str]:
        raw = (target or "").strip()
        if not raw:
            return None
        if raw.endswith(".md"):
            candidate = raw.replace("\\", "/").lstrip("/")
            full = self.config.root / candidate
            if full.is_file():
                try:
                    return full.relative_to(self.config.root).as_posix()
                except ValueError:
                    pass
        stem = Path(raw).stem if "/" in raw else raw
        norm = _norm_name(stem)
        if norm in self._aliases:
            return self._aliases[norm]
        hits = self._by_norm.get(norm) or []
        if len(hits) == 1:
            return hits[0]
        if len(hits) > 1 and source_rel:
            src_dir = str(Path(source_rel).parent)
            same_folder = [h for h in hits if str(Path(h).parent) == src_dir]
            if len(same_folder) == 1:
                return same_folder[0]
        if stem.lower() in self._by_stem:
            return self._by_stem[stem.lower()]
        return hits[0] if hits else None

    def backlinks(self, rel_path: str) -> List[str]:
        self.build()
        return sorted(self._incoming.get(rel_path, set()))

    def outgoing(self, rel_path: str) -> List[str]:
        self.build()
        return sorted(self._outgoing.get(rel_path, set()))

    def neighborhood(self, rel_paths: List[str], *, hops: int = 1) -> Set[str]:
        self.build()
        seen = set(rel_paths)
        frontier = list(rel_paths)
        for _ in range(max(hops, 0)):
            nxt: List[str] = []
            for rel in frontier:
                for linked in self._outgoing.get(rel, set()):
                    if linked not in seen:
                        seen.add(linked)
                        nxt.append(linked)
                for src in self._incoming.get(rel, set()):
                    if src not in seen:
                        seen.add(src)
                        nxt.append(src)
            frontier = nxt
        return seen
