"""Parse Obsidian markdown notes: frontmatter, tags, wikilinks, Dataview fields."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Set, Tuple

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|[^\]]+)?\]\]")
_TAG_RE = re.compile(r"(?<![\[`])#([a-zA-Z][\w/-]*)")
_DATAVIEW_INLINE_RE = re.compile(
    r"(?:\[(?P<key>[^\]:]+)::(?P<val>[^\]]+)\]|(?P<key2>[\w-]+)::(?P<val2>[^\n]+))",
)
_LIST_ITEM_RE = re.compile(r"^\s*-\s+(.+)$")


def _parse_scalar_list(raw: str) -> List[str]:
    raw = (raw or "").strip()
    if not raw:
        return []
    if raw.startswith("[") and raw.endswith("]"):
        inner = raw[1:-1].strip()
        if not inner:
            return []
        return [p.strip().strip("'\"") for p in inner.split(",") if p.strip()]
    if raw.startswith('"') and raw.endswith('"'):
        return [raw[1:-1]]
    if raw.startswith("'") and raw.endswith("'"):
        return [raw[1:-1]]
    return [raw]


def parse_frontmatter(text: str) -> Tuple[Dict[str, str], str]:
    """Return (frontmatter dict, body). Minimal YAML — no PyYAML dependency."""
    fm: Dict[str, str] = {}
    body = text or ""
    m = _FRONTMATTER_RE.match(body)
    if not m:
        return fm, body
    block = m.group(1)
    body = body[m.end():]
    current_key = None
    for line in block.splitlines():
        if not line.strip():
            continue
        li = _LIST_ITEM_RE.match(line)
        if li and current_key:
            existing = fm.get(current_key, "")
            val = li.group(1).strip().strip("'\"")
            fm[current_key] = (existing + "," + val) if existing else val
            continue
        if ":" not in line:
            continue
        key, val = line.split(":", 1)
        key = key.strip()
        val = val.strip()
        if not key:
            continue
        fm[key] = val
        current_key = key if not val else None
    return fm, body


@dataclass
class ParsedNote:
    rel_path: str
    frontmatter: Dict[str, str] = field(default_factory=dict)
    body: str = ""
    tags: Set[str] = field(default_factory=set)
    aliases: Set[str] = field(default_factory=set)
    wikilinks: Set[str] = field(default_factory=set)
    dataview_fields: Dict[str, str] = field(default_factory=dict)

    @property
    def title(self) -> str:
        from pathlib import Path
        return Path(self.rel_path).stem

    @property
    def search_blob(self) -> str:
        parts = [
            self.title,
            " ".join(sorted(self.tags)),
            " ".join(sorted(self.aliases)),
            " ".join(f"{k} {v}" for k, v in self.dataview_fields.items()),
            self.body,
        ]
        return "\n".join(p for p in parts if p)


def parse_note(rel_path: str, text: str) -> ParsedNote:
    fm, body = parse_frontmatter(text)
    tags: Set[str] = set()
    aliases: Set[str] = set()

    for key in ("tags", "tag"):
        if key in fm:
            for t in _parse_scalar_list(fm[key]):
                tags.add(t.lstrip("#").lower())
    if "aliases" in fm:
        for a in _parse_scalar_list(fm["aliases"]):
            aliases.add(a.strip())
    elif "alias" in fm:
        for a in _parse_scalar_list(fm["alias"]):
            aliases.add(a.strip())

    for m in _TAG_RE.finditer(body):
        tags.add(m.group(1).lower())

    wikilinks: Set[str] = set()
    for m in _WIKILINK_RE.finditer(text):
        target = m.group(1).strip()
        if target:
            wikilinks.add(target)

    dataview_fields: Dict[str, str] = {}
    for m in _DATAVIEW_INLINE_RE.finditer(body):
        key = (m.group("key") or m.group("key2") or "").strip().lower()
        val = (m.group("val") or m.group("val2") or "").strip()
        if key and val:
            dataview_fields[key] = val

    for key, val in fm.items():
        kl = key.lower()
        if kl in {"tags", "tag", "aliases", "alias", "cssclass", "cssclasses"}:
            continue
        if val:
            dataview_fields.setdefault(kl, val)

    return ParsedNote(
        rel_path=rel_path,
        frontmatter=fm,
        body=body,
        tags=tags,
        aliases=aliases,
        wikilinks=wikilinks,
        dataview_fields=dataview_fields,
    )
