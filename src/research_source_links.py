"""Resolve Deep Research evidence sources to navigable hrefs."""
from __future__ import annotations

import re
from typing import Any, Dict, Optional
from urllib.parse import urlparse

_LINKS_SCHEME_RE = re.compile(r"^links://(.+)$", re.I)


def graph_node_id_from_source(url: str = "", source_id: str = "") -> str:
    """Return a knowledge node id (e.g. document:abc, paper:KEY) when known."""
    url = (url or "").strip()
    source_id = (source_id or "").strip()

    match = _LINKS_SCHEME_RE.match(url)
    if match:
        return match.group(1).strip()

    if source_id.startswith("src:graph:"):
        return source_id[len("src:graph:") :].strip()
    if source_id.startswith("src:paper:"):
        return f"paper:{source_id[len('src:paper:'):].strip()}"
    if source_id.startswith("src:zotero:"):
        return f"paper:{source_id[len('src:zotero:'):].strip()}"

    return ""


def resolve_source_href(
    url: str = "",
    source_id: str = "",
    *,
    citation_num: Optional[int] = None,
    for_visual_report: bool = False,
) -> Dict[str, Any]:
    """Build navigation metadata for a registry source row."""
    url = (url or "").strip()
    source_id = (source_id or "").strip()
    anchor = f"#source-{citation_num}" if citation_num else ""

    if url.startswith(("http://", "https://")):
        return {"href": url, "external": True, "node_id": ""}

    node_id = graph_node_id_from_source(url, source_id)
    if node_id:
        ntype, _, raw = node_id.partition(":")
        raw = raw.strip()
        if ntype == "document" and raw:
            hash_href = f"#document-{raw}"
            return {
                "href": f"/{hash_href}" if for_visual_report else hash_href,
                "external": False,
                "node_id": node_id,
            }
        if ntype == "paper" and raw:
            hash_href = f"#paper-{raw.upper()}"
            return {
                "href": f"/{hash_href}" if for_visual_report else hash_href,
                "external": False,
                "node_id": node_id,
            }
        if ntype == "task" and raw:
            hash_href = f"#task-{raw}"
            return {
                "href": f"/{hash_href}" if for_visual_report else hash_href,
                "external": False,
                "node_id": node_id,
            }

    if url.startswith("#document-") or url.startswith("#paper-") or url.startswith("#task-"):
        return {
            "href": f"/{url.lstrip('/')}" if for_visual_report else url,
            "external": False,
            "node_id": node_id,
        }

    if url.startswith("src:web:"):
        web_url = url[len("src:web:") :]
        if web_url.startswith(("http://", "https://")):
            return {"href": web_url, "external": True, "node_id": ""}

    if source_id.startswith("src:web:"):
        parsed = urlparse(source_id[len("src:web:") :])
        if parsed.scheme in ("http", "https"):
            return {"href": source_id[len("src:web:") :], "external": True, "node_id": ""}

    if url and not url.startswith("links://"):
        return {"href": url, "external": url.startswith("http"), "node_id": node_id}

    return {"href": anchor, "external": False, "node_id": node_id}


def enrich_registry_source_row(row: dict, *, for_visual_report: bool = False) -> dict:
    """Attach href/external/node_id to a normalized registry source dict."""
    nav = resolve_source_href(
        row.get("url") or "",
        row.get("source_id") or "",
        citation_num=row.get("citation_num"),
        for_visual_report=for_visual_report,
    )
    enriched = dict(row)
    enriched.update(nav)
    return enriched


_CITE_PLACEHOLDER_RE = re.compile(r"%%CITE:(\d+)%%")
_BRACKET_CITE_RE = re.compile(r"\[(\d+)\](?!\()")
_ANCHOR_SPLIT_RE = re.compile(r"(<a\b[^>]*>.*?</a>)", re.I | re.S)


def linkify_bracket_citations_html(
    html_text: str,
    *,
    anchor_prefix: str = "source",
    link_class: str = "cite-link",
) -> str:
    """Turn bare [N] markers into citation anchors, skipping existing <a> tags."""
    if not html_text:
        return html_text

    def repl(match: re.Match) -> str:
        num = match.group(1)
        return (
            f'<a href="#{anchor_prefix}-{num}" class="{link_class}" '
            f'data-cite="{num}">[{num}]</a>'
        )

    parts = _ANCHOR_SPLIT_RE.split(html_text)
    out: list[str] = []
    for idx, part in enumerate(parts):
        if idx % 2 == 1:
            out.append(part)
        else:
            out.append(_BRACKET_CITE_RE.sub(repl, part))
    return "".join(out)


def linkify_citation_placeholders_html(
    html_text: str,
    *,
    anchor_prefix: str = "source",
    link_class: str = "cite-link",
) -> str:
    """Turn %%CITE:N%% placeholders and leftover [N] markers into citation anchors."""
    if not html_text:
        return html_text
    html_text = _CITE_PLACEHOLDER_RE.sub(
        rf'<a href="#{anchor_prefix}-\1" class="{link_class}" data-cite="\1">[\1]</a>',
        html_text,
    )
    return linkify_bracket_citations_html(
        html_text,
        anchor_prefix=anchor_prefix,
        link_class=link_class,
    )


def inject_citation_placeholders(markdown: str) -> str:
    """Replace inline [N] markers with placeholders safe for markdown rendering."""
    if not markdown:
        return markdown
    lines = []
    for line in markdown.split("\n"):
        stripped = line.strip()
        if re.match(r"^\[\d+\]:\s", stripped):
            lines.append(line)
            continue
        lines.append(re.sub(r"\[(\d+)\](?!\()(?!:)", r"%%CITE:\1%%", line))
    return "\n".join(lines)
