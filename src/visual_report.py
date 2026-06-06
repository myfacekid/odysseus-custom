# src/visual_report.py
"""
Generate a self-contained, styled HTML page from deep research results.

Takes the markdown report, sources, and stats produced by DeepResearcher
and wraps them in an editorial-quality HTML document with:
- System/local typography, no remote font provider
- Dark/light theme via prefers-color-scheme
- Hero section with animated gradient
- Auto-generated table of contents from headings
- Collapsible compact sources list
- Print/Share toolbar
"""
import html
import json
import logging
import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from bs4 import BeautifulSoup

from src.research_utils import strip_thinking
from urllib.parse import urlparse

import markdown

logger = logging.getLogger(__name__)

# Research reports are text-only — no hero/section OG images scraped or rendered.
REPORT_IMAGES_ENABLED = False

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _autolink_urls(md_text: str) -> str:
    """Convert bare URLs to markdown links before processing.

    Skips URLs already inside markdown link syntax [text](url).
    """
    if not isinstance(md_text, str):
        return md_text
    # Match bare URLs not already inside ](...)
    return re.sub(
        r'(?<!\]\()(?<!\()(https?://[^\s\)<>]+)',
        r'[\1](\1)',
        md_text,
    )


def _md_to_html(md_text: str) -> str:
    """Convert markdown to HTML with common extensions."""
    md_text = _autolink_urls(md_text)
    result = markdown.markdown(
        md_text,
        extensions=["extra", "codehilite", "toc", "tables", "sane_lists"],
        extension_configs={
            "codehilite": {"css_class": "code", "guess_lang": False},
            "toc": {"marker": "", "toc_depth": "2-3"},
        },
    )
    # Make external links open in new tab
    result = re.sub(
        r'<a href="(https?://)',
        r'<a target="_blank" rel="noopener noreferrer" href="\1',
        result,
    )
    return result


def _extract_headings(md_text: str) -> List[Dict[str, str]]:
    """Pull h2/h3 headings from markdown for table of contents."""
    if not isinstance(md_text, str):
        return []
    headings = []
    seen_slugs: Dict[str, int] = {}

    def _plain_heading_text(text: str) -> str:
        text = text.strip().rstrip("#").strip()
        text = re.sub(r'!\[([^\]]*)\]\([^)]+\)', r'\1', text)
        text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
        text = re.sub(r'\[([^\]]+)\]\[[^\]]+\]', r'\1', text)
        text = re.sub(r'<[^>]+>', '', text)
        text = re.sub(r'[`*_~]+', '', text)
        text = html.unescape(text)
        return re.sub(r'\s+', ' ', text).strip()

    def _make_slug(text: str) -> str:
        slug = re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')
        if not slug:
            slug = "section"
        if slug in seen_slugs:
            seen_slugs[slug] += 1
            slug = f"{slug}-{seen_slugs[slug]}"
        else:
            seen_slugs[slug] = 0
        return slug

    for m in re.finditer(r'^(#{2,3})\s+(.+)$', md_text, re.MULTILINE):
        level = len(m.group(1))
        text = _plain_heading_text(m.group(2))
        if not text:
            continue
        headings.append({"level": level, "text": text, "slug": _make_slug(text)})
    if not headings:
        for m in re.finditer(r'^\*\*([^*]+)\*\*\s*$', md_text, re.MULTILINE):
            text = _plain_heading_text(m.group(1)).rstrip(':')
            if 3 < len(text) < 80:
                headings.append({"level": 2, "text": text, "slug": _make_slug(text)})
    return headings


def _apply_heading_ids(report_html: str, headings: List[Dict[str, str]]) -> str:
    """Force rendered h2/h3 IDs to match the generated sidebar links."""
    if not headings:
        return report_html

    soup = BeautifulSoup(report_html, "html.parser")
    rendered_headings = soup.find_all(["h2", "h3"])
    for element, heading in zip(rendered_headings, headings):
        expected_name = f"h{heading['level']}"
        if element.name != expected_name:
            logger.debug(
                "Visual report heading level mismatch: rendered %s for TOC %s",
                element.name,
                expected_name,
            )
        element["id"] = heading["slug"]
    if len(rendered_headings) != len(headings):
        logger.debug(
            "Visual report heading count mismatch: rendered=%s toc=%s",
            len(rendered_headings),
            len(headings),
        )
    return str(soup)


def split_executive_summary(markdown: str) -> Tuple[str, str]:
    """Split an Executive Summary section from the rest of the report body."""
    if not markdown:
        return "", markdown
    match = re.search(r"^##\s+Executive Summary\s*$", markdown, re.I | re.M)
    if not match:
        return "", markdown
    start = match.end()
    rest = markdown[start:]
    next_match = re.search(r"^##\s+", rest, re.M)
    summary = (rest[: next_match.start()] if next_match else rest).strip()
    prefix = markdown[: match.start()].rstrip()
    suffix = (rest[next_match.start() :] if next_match else "").lstrip()
    body_parts = [part for part in (prefix, suffix) if part]
    body = "\n\n".join(body_parts)
    return summary, body


def strip_references_section(markdown: str) -> str:
    """Remove the trailing ## References block from report markdown."""
    from src.research_evidence import split_references_section

    body, _refs = split_references_section(markdown or "")
    return body


def build_toc_html(
    headings: List[Dict[str, str]],
    registry_sources: Optional[List[Dict]] = None,
) -> str:
    """Build a nested TOC: h3 items collapsed under h2; sources collapsed as one group."""
    lines: List[str] = []
    i = 0
    while i < len(headings):
        heading = headings[i]
        if heading["level"] != 2:
            lines.append(
                f'<a href="#{heading["slug"]}" class="depth-{heading["level"]}">'
                f'{html.escape(heading["text"])}</a>'
            )
            i += 1
            continue

        children: List[Dict[str, str]] = []
        j = i + 1
        while j < len(headings) and headings[j]["level"] == 3:
            children.append(headings[j])
            j += 1

        title = html.escape(heading["text"])
        if children:
            child_links = "\n".join(
                f'<a href="#{child["slug"]}" class="depth-3">{html.escape(child["text"])}</a>'
                for child in children
            )
            lines.append(
                '<details class="toc-group">'
                f'<summary><a href="#{heading["slug"]}" class="toc-group-title">{title}</a></summary>'
                f'<div class="toc-group-children">{child_links}</div>'
                "</details>"
            )
        else:
            lines.append(f'<a href="#{heading["slug"]}" class="depth-2">{title}</a>')
        i = j

    if registry_sources:
        source_links = "\n".join(
            (
                f'<a href="#source-{src.get("citation_num")}" class="depth-3 toc-source-link">'
                f'[{src.get("citation_num")}] '
                f'{html.escape(((src.get("title") or src.get("url") or "Untitled").strip())[:42])}'
                f'{"…" if len((src.get("title") or src.get("url") or "Untitled").strip()) > 42 else ""}'
                f"</a>"
            )
            for src in registry_sources[:40]
        )
        lines.append(
            f'<details class="toc-group toc-sources-group">'
            f"<summary>Sources ({len(registry_sources)})</summary>"
            f'<div class="toc-group-children">{source_links}</div>'
            "</details>"
        )

    return "\n      ".join(lines)


def linkify_citation_markers(html_text: str) -> str:
    """Turn inline [N] markers into in-page source jumps (not markdown links)."""
    from src.research_source_links import linkify_citation_placeholders_html

    return linkify_citation_placeholders_html(html_text or "")


def prepare_markdown_for_report_html(markdown: str) -> str:
    """Inject citation placeholders before markdown → HTML conversion."""
    from src.research_source_links import inject_citation_placeholders

    return inject_citation_placeholders(markdown or "")


def sources_from_registry(
    evidence_registry: Optional[dict],
    legacy_sources: Optional[List[Dict]] = None,
    *,
    for_visual_report: bool = False,
) -> List[Dict]:
    """Normalize registry + legacy source lists for report UI/export."""
    from src.research_source_links import enrich_registry_source_row

    if evidence_registry and evidence_registry.get("sources"):
        from src.research_evidence import EvidenceRegistry

        reg = EvidenceRegistry.from_dict(evidence_registry)
        rows: List[Dict] = []
        for src in reg.sources():
            row = {
                "citation_num": src.citation_num,
                "title": src.title,
                "url": src.url,
                "authors": src.authors,
                "year": src.year,
                "doi_or_id": src.doi_or_id,
                "source_id": src.source_id,
                "peer_review_status": src.peer_review_status,
                "study_type": src.study_type,
                "source_type": src.source_type,
                "is_seed": src.is_seed,
                "sourcing_tier": src.sourcing_tier,
                "sourcing_note": src.sourcing_note,
                "content_excerpt": src.content_excerpt,
                "zotero_key": zotero_key_from_source_row(src.to_dict()),
            }
            rows.append(enrich_registry_source_row(row, for_visual_report=for_visual_report))
        return rows
    rows = []
    for i, src in enumerate(legacy_sources or [], 1):
        if not isinstance(src, dict):
            continue
        row = {**src, "citation_num": src.get("citation_num") or i}
        row["zotero_key"] = zotero_key_from_source_row(row)
        rows.append(enrich_registry_source_row(row, for_visual_report=for_visual_report))
    return rows


_ZOTERO_KEY_RE = re.compile(r"^[A-Z0-9]{8}$", re.I)


def zotero_key_from_source_row(row: dict) -> str:
    """Extract a Zotero item key from a registry source row when known."""
    sid = (row.get("source_id") or "").strip()
    if sid.startswith("src:zotero:"):
        return sid.rsplit(":", 1)[-1].strip().upper()
    if sid.startswith("src:paper:"):
        return sid.rsplit(":", 1)[-1].strip().upper()
    doi_or = (row.get("doi_or_id") or "").strip()
    if _ZOTERO_KEY_RE.match(doi_or):
        return doi_or.upper()
    return ""


def build_sourcing_disclosure_html(registry_sources: List[Dict]) -> str:
    """Compact retrieval-tier summary for the report header."""
    from src.research_sourcing import compute_sourcing_tier_counts, tier_badge_class

    counts = compute_sourcing_tier_counts(registry_sources)
    if not counts["total"]:
        return ""
    chips = []
    if counts["adequate"]:
        chips.append(
            f'<span class="sourcing-chip sourcing-chip-{tier_badge_class("adequate")}">'
            f'{counts["adequate"]} full text</span>'
        )
    if counts["abstract_only"]:
        chips.append(
            f'<span class="sourcing-chip sourcing-chip-{tier_badge_class("abstract_only")}">'
            f'{counts["abstract_only"]} abstract only</span>'
        )
    if counts["thin"]:
        chips.append(
            f'<span class="sourcing-chip sourcing-chip-{tier_badge_class("metadata_only")}">'
            f'{counts["thin"]} limited retrieval</span>'
        )
    if not chips:
        return ""
    return (
        '<div class="sourcing-disclosure" aria-label="Source retrieval summary">'
        + "".join(chips)
        + "</div>"
    )


def build_sources_sidebar_html(registry_sources: List[Dict]) -> str:
    """Right-hand source panel with filters and expandable excerpts."""
    from src.research_sourcing import (
        SOURCING_TIER_ADEQUATE,
        tier_badge_class,
        tier_display_label,
    )

    if not registry_sources:
        return ""

    cards: List[str] = []
    for src in registry_sources:
        num = src.get("citation_num")
        title = html.escape((src.get("title") or src.get("url") or "Untitled").strip())
        tier = (src.get("sourcing_tier") or "").strip().lower()
        tier_label = html.escape(tier_display_label(tier))
        tier_cls = tier_badge_class(tier)
        is_seed = bool(src.get("is_seed"))
        filter_tier = "adequate" if tier == SOURCING_TIER_ADEQUATE else "thin"
        seed_attr = "1" if is_seed else "0"

        meta_bits = []
        if src.get("authors"):
            meta_bits.append(html.escape(str(src["authors"])))
        if src.get("year"):
            meta_bits.append(html.escape(str(src["year"])))
        meta_line = " · ".join(meta_bits)

        detail_rows: List[str] = []
        zkey = (src.get("zotero_key") or zotero_key_from_source_row(src)).strip()
        if zkey:
            detail_rows.append(
                f'<div class="source-detail-row"><span class="source-detail-label">Zotero</span>'
                f'<code class="source-detail-value">{html.escape(zkey)}</code></div>'
            )
        doi_or = (src.get("doi_or_id") or "").strip()
        if doi_or.startswith("10."):
            doi_url = f"https://doi.org/{doi_or}"
            detail_rows.append(
                f'<div class="source-detail-row"><span class="source-detail-label">DOI</span>'
                f'<a class="source-detail-link" href="{html.escape(doi_url)}" '
                f'target="_blank" rel="noopener noreferrer">{html.escape(doi_or)}</a></div>'
            )
        elif doi_or:
            detail_rows.append(
                f'<div class="source-detail-row"><span class="source-detail-label">ID</span>'
                f'<span class="source-detail-value">{html.escape(doi_or)}</span></div>'
            )

        raw_url = (src.get("url") or "").strip()
        href = (src.get("href") or "").strip()
        external = bool(src.get("external"))
        if raw_url.startswith(("http://", "https://")):
            detail_rows.append(
                f'<div class="source-detail-row"><span class="source-detail-label">URL</span>'
                f'<a class="source-detail-link" href="{html.escape(raw_url)}" '
                f'target="_blank" rel="noopener noreferrer">{html.escape(raw_url[:72])}'
                f'{"…" if len(raw_url) > 72 else ""}</a></div>'
            )
        elif href and not href.startswith("#"):
            detail_rows.append(
                f'<div class="source-detail-row"><span class="source-detail-label">Link</span>'
                f'<a class="source-detail-link source-internal" href="{html.escape(href)}" '
                f'data-node-id="{html.escape(src.get("node_id") or "")}">Open in app</a></div>'
            )

        note = (src.get("sourcing_note") or "").strip()
        if note:
            detail_rows.append(
                f'<p class="source-tier-note">{html.escape(note)}</p>'
            )

        excerpt = (src.get("content_excerpt") or "").strip()
        excerpt_html = ""
        if excerpt:
            excerpt_html = (
                f'<details class="source-excerpt"><summary>Abstract / excerpt</summary>'
                f'<p>{html.escape(excerpt)}</p></details>'
            )

        seed_badge = (
            '<span class="source-seed-badge">Seed</span>' if is_seed else ""
        )
        meta_html = (
            f'<div class="source-card-meta">{meta_line}</div>' if meta_line else ""
        )
        cards.append(
            f'<article class="source-card" id="source-{num}" data-cite="{num}" '
            f'data-tier="{filter_tier}" data-seed="{seed_attr}">'
            f'<div class="source-card-head">'
            f'<span class="snum">[{num}]</span>'
            f'<div class="source-card-title-wrap">'
            f'<div class="source-card-title">{title}</div>'
            f'{meta_html}'
            f'</div>'
            f'<div class="source-card-badges">{seed_badge}'
            f'<span class="tier-badge tier-{tier_cls}">{tier_label}</span></div>'
            f'</div>'
            f'<div class="source-card-body">{"".join(detail_rows)}{excerpt_html}</div>'
            f'</article>'
        )

    return (
        '<aside class="sources-sidebar" aria-label="Reference sources">'
        '<div class="sources-sidebar-header">'
        f'<h2>Sources <span class="sources-count">({len(registry_sources)})</span></h2>'
        '<div class="source-filters" role="toolbar" aria-label="Filter sources">'
        '<button type="button" class="source-filter active" data-filter="all">All</button>'
        '<button type="button" class="source-filter" data-filter="seed">Seeds</button>'
        '<button type="button" class="source-filter" data-filter="adequate">Full text</button>'
        '<button type="button" class="source-filter" data-filter="thin">Limited</button>'
        '</div>'
        '</div>'
        '<div class="sources-sidebar-list">'
        + "\n".join(cards)
        + "</div></aside>"
    )


def _wrap_executive_summary_html(summary_html: str) -> str:
    if not summary_html.strip():
        return ""
    return (
        '<details class="exec-summary-panel" open>'
        "<summary>Executive Summary</summary>"
        f'<div class="exec-summary-body">{summary_html}</div>'
        "</details>"
    )

# scraped image) + hide (remove and skip on future renders). Reroll is
# wired up in the page script using the embedded spare-image pool.
_IMG_OVERLAY_BTNS = (
    '<button class="img-reroll-btn" type="button" title="Swap for another image">'
    '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 11-2.12-9.36L23 10"/></svg>'
    '</button>'
    '<button class="img-hide-btn" type="button" title="Hide image">'
    '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>'
    '</button>'
)


def _inject_images(report_html: str, images: List[str]) -> Tuple[str, int]:
    """Insert OG images between h2 sections as figures.

    Returns (html, consumed) where ``consumed`` is how many of ``images``
    were actually placed — the rest become the spare pool for reroll.
    """
    if not images:
        return report_html, 0

    # Find positions after closing </h2> + following paragraph
    h2_positions = [m.end() for m in re.finditer(r'</h2>', report_html)]
    if not h2_positions:
        return report_html, 0

    # Insert an image after every 2nd heading (skip first heading = title)
    img_idx = 0
    insert_after = h2_positions[1::2]  # every 2nd h2
    # Work backwards to preserve positions
    for pos in reversed(insert_after):
        if img_idx >= len(images):
            break
        img_url = images[img_idx]
        img_idx += 1
        url_esc = html.escape(img_url)
        figure = (
            f'\n<figure class="section-image" data-img-url="{url_esc}">'
            f'<img src="{url_esc}" alt="" loading="lazy" '
            f'onerror="this.parentElement.style.display=\'none\'">'
            f'{_IMG_OVERLAY_BTNS}'
            f'</figure>\n'
        )
        report_html = report_html[:pos] + figure + report_html[pos:]

    return report_html, img_idx


# ---------------------------------------------------------------------------
# HTML template
# ---------------------------------------------------------------------------

_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<meta name="description" content="{description}">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{description}">
<meta property="og:type" content="article">
{og_image_meta}
<meta name="theme-color" content="#b8543a" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#131214" media="(prefers-color-scheme: dark)">
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='75' font-size='75'>N</text></svg>">
<style>
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

:root {{
  --font-display: 'Charter', 'Iowan Old Style', Georgia, serif;
  --font-body: system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  --font-mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  --bg: #fbf9f4;
  --bg-surface: #ffffff;
  --bg-surface-alt: #f1ede4;
  --border: rgba(0,0,0,0.08);
  --border-strong: rgba(0,0,0,0.16);
  --text: #1a1817;
  --text-dim: #5a5651;
  --text-muted: #8a8580;
  --accent: #b8543a;
  --accent-light: #d97a5e;
  --accent-bg: rgba(184,84,58,0.06);
  --gold: #c9952e;
  --gold-bg: rgba(201,149,46,0.09);
  --aurora-a: rgba(184,84,58,0.10);
  --aurora-b: rgba(201,149,46,0.08);
  --aurora-c: rgba(64,98,128,0.07);
  --radius: 12px;
  --shadow-sm: 0 1px 3px rgba(0,0,0,0.05);
  --shadow-md: 0 4px 24px rgba(0,0,0,0.07);
  --max-w: 760px;
}}

@media (prefers-color-scheme: dark) {{
  :root {{
    --bg: #131214; --bg-surface: #1c1a1e; --bg-surface-alt: #25232a;
    --border: rgba(255,255,255,0.07); --border-strong: rgba(255,255,255,0.16);
    --text: #ece8e2; --text-dim: #a8a39c; --text-muted: #6f6b66;
    --accent: #e88f73; --accent-light: #f4ad95; --accent-bg: rgba(232,143,115,0.09);
    --gold: #e8c05a; --gold-bg: rgba(232,192,90,0.09);
    --aurora-a: rgba(232,143,115,0.13);
    --aurora-b: rgba(232,192,90,0.09);
    --aurora-c: rgba(125,180,224,0.10);
    --shadow-sm: 0 1px 3px rgba(0,0,0,0.4); --shadow-md: 0 4px 28px rgba(0,0,0,0.55);
  }}
}}

html {{
  scroll-behavior: smooth;
  /* Give smooth-scroll some breathing room so anchors land below the
     fixed toolbar instead of being shoved straight under it. */
  scroll-padding-top: 4rem;
}}
body {{
  font-family: var(--font-body);
  background: var(--bg);
  color: var(--text);
  line-height: 1.75;
  font-size: 17px;
  font-feature-settings: 'ss01', 'cv11';
  -webkit-font-smoothing: antialiased;
  text-rendering: optimizeLegibility;
  position: relative;
  min-height: 100vh;
}}

/* ── Aurora background ─────────────────────────────────
   Slowly-drifting layered blobs in the accent palette. Sits behind
   the content, fixed to the viewport so scrolling doesn't reset the
   composition. Subtle grain on top stops it reading as 'flat CSS'. */
body::before {{
  content: '';
  position: fixed;
  inset: -20vh -20vw;
  z-index: -2;
  background:
    radial-gradient(40vw 50vh at 18% 22%, var(--aurora-a) 0%, transparent 60%),
    radial-gradient(45vw 55vh at 82% 12%, var(--aurora-b) 0%, transparent 65%),
    radial-gradient(55vw 60vh at 50% 88%, var(--aurora-c) 0%, transparent 70%);
  filter: blur(20px);
  animation: aurora-drift 28s ease-in-out infinite alternate;
  pointer-events: none;
}}
body::after {{
  content: '';
  position: fixed;
  inset: 0;
  z-index: -1;
  pointer-events: none;
  /* Subtle film-grain — SVG turbulence baked to a data-URL. */
  background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 200 200'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2' stitchTiles='stitch'/><feColorMatrix values='0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 0.32 0'/></filter><rect width='100%25' height='100%25' filter='url(%23n)'/></svg>");
  opacity: 0.045;
  mix-blend-mode: overlay;
}}
@keyframes aurora-drift {{
  0%   {{ transform: translate3d(0,0,0) scale(1);     }}
  50%  {{ transform: translate3d(2vw,-1vh,0) scale(1.04); }}
  100% {{ transform: translate3d(-1vw,1.5vh,0) scale(1.02); }}
}}
@media (prefers-reduced-motion: reduce) {{
  body::before {{ animation: none; }}
}}

/* ── Toolbar (top-right) ──────────────────────────── */
.toolbar {{
  position: fixed;
  top: 1rem;
  right: 1rem;
  z-index: 100;
  display: flex;
  gap: 0.4rem;
  opacity: 0.7;
  transition: opacity 0.2s;
}}
.toolbar:hover {{ opacity: 1; }}
.toolbar button {{
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 6px 14px;
  border: 1px solid var(--border-strong);
  border-radius: 8px;
  background: var(--bg-surface);
  color: var(--text);
  font-family: inherit;
  font-size: 0.78rem;
  font-weight: 500;
  cursor: pointer;
  box-shadow: var(--shadow-sm);
  transition: background 0.15s;
  position: relative;
}}
.toolbar button:hover {{ background: var(--bg-surface-alt); }}
.toolbar button svg {{ width: 14px; height: 14px; flex-shrink: 0; }}
.toolbar .toast {{
  position: absolute;
  top: calc(100% + 6px);
  right: 0;
  background: var(--text);
  color: var(--bg);
  padding: 4px 10px;
  border-radius: 6px;
  font-size: 0.72rem;
  white-space: nowrap;
  opacity: 0;
  transition: opacity 0.15s;
  pointer-events: none;
}}
.toolbar .toast.show {{ opacity: 1; }}
.dropdown {{ position: relative; }}
.dropdown-menu {{
  display: none;
  position: absolute;
  top: calc(100% + 4px);
  right: 0;
  background: var(--bg-surface);
  border: 1px solid var(--border-strong);
  border-radius: 8px;
  box-shadow: var(--shadow-md);
  overflow: hidden;
  min-width: 140px;
}}
.dropdown-menu.open {{ display: block; }}
.dropdown-menu button {{
  display: block;
  width: 100%;
  padding: 8px 14px;
  border: none;
  background: none;
  color: var(--text);
  font-family: inherit;
  font-size: 0.8rem;
  text-align: left;
  cursor: pointer;
}}
.dropdown-menu button:hover {{ background: var(--bg-surface-alt); }}

/* ── Hero ──────────────────────────────────────────── */
.hero {{
  position: relative;
  background: transparent;
  color: var(--text);
  padding: 5.5rem 2rem 2.5rem;
  text-align: center;
  overflow: hidden;
}}
.hero::before {{
  content: '';
  position: absolute;
  inset: 0;
  background:
    radial-gradient(ellipse 70% 60% at 50% 40%, color-mix(in srgb, var(--accent) 10%, transparent) 0%, transparent 70%);
  pointer-events: none;
}}
/* A hair-thin gradient hairline divider under the hero to anchor it
   without putting it on a heavy boxed background. */
.hero::after {{
  content: '';
  position: absolute;
  left: 50%; bottom: 0;
  width: min(60%, 320px);
  height: 1px;
  transform: translateX(-50%);
  background: linear-gradient(90deg, transparent, var(--border-strong), transparent);
}}
.hero-label {{
  position: relative;
  text-transform: uppercase;
  letter-spacing: 0.28em;
  font-size: 0.68rem;
  font-weight: 600;
  color: var(--accent);
  opacity: 0.85;
  margin-bottom: 1.4rem;
  font-family: var(--font-body);
}}
.hero h1 {{
  position: relative;
  font-family: var(--font-display);
  font-size: clamp(2rem, 4.5vw, 3rem);
  font-weight: 600;
  font-variation-settings: 'opsz' 120, 'SOFT' 50;
  line-height: 1.15;
  max-width: 720px;
  margin: 0 auto;
  letter-spacing: -0.02em;
  color: var(--text);
}}

/* ── Hero image ───────────────────────────────────── */
.hero-image {{
  max-width: var(--max-w);
  margin: -2rem auto 0;
  position: relative;
  z-index: 1;
  padding: 0 2rem;
}}
.hero-image img {{
  width: 100%;
  max-height: 360px;
  object-fit: cover;
  border-radius: var(--radius);
  box-shadow: var(--shadow-md);
  display: block;
}}

/* ── Section images ───────────────────────────────── */
.section-image {{
  margin: 1.5rem 0;
  position: relative;
}}
.section-image img {{
  width: 100%;
  max-height: 300px;
  object-fit: cover;
  border-radius: var(--radius);
  box-shadow: var(--shadow-sm);
  display: block;
}}

/* ── Per-image hide button ────────────────────────────
   A small X that appears on hover (or always on touch) so users can
   remove irrelevant OG images. Click POSTs the URL to the backend so
   the next render skips it. */
.img-hide-btn {{
  position: absolute;
  top: 10px; right: 10px;
  width: 28px; height: 28px;
  display: inline-flex; align-items: center; justify-content: center;
  background: rgba(0,0,0,0.55);
  color: #fff;
  border: none;
  border-radius: 50%;
  cursor: pointer;
  opacity: 0;
  transition: opacity 0.15s ease, background 0.15s ease, transform 0.05s ease;
  z-index: 2;
  padding: 0;
}}
.hero-image .img-hide-btn {{ top: 14px; right: 2.5rem; }}
/* Reroll sits just to the left of the hide button. */
.img-reroll-btn {{
  position: absolute;
  top: 10px; right: 46px;
  width: 28px; height: 28px;
  display: inline-flex; align-items: center; justify-content: center;
  background: rgba(0,0,0,0.55);
  color: #fff;
  border: none;
  border-radius: 50%;
  cursor: pointer;
  opacity: 0;
  transition: opacity 0.15s ease, background 0.15s ease, transform 0.05s ease;
  z-index: 2;
  padding: 0;
}}
.hero-image .img-reroll-btn {{ top: 14px; right: calc(2.5rem + 36px); }}
.section-image:hover .img-hide-btn,
.section-image:hover .img-reroll-btn,
.hero-image:hover .img-hide-btn,
.hero-image:hover .img-reroll-btn {{ opacity: 1; }}
.img-hide-btn:hover {{ background: var(--accent); }}
.img-reroll-btn:hover {{ background: var(--accent); }}
.img-hide-btn:active,
.img-reroll-btn:active {{ transform: scale(0.92); }}
.img-reroll-btn.spinning svg {{ animation: img-reroll-spin 0.6s linear infinite; }}
.img-reroll-btn:disabled {{ display: none; }}
@keyframes img-reroll-spin {{ to {{ transform: rotate(360deg); }} }}
@media (hover: none) {{
  /* Touch devices have no hover — show the buttons at low opacity always. */
  .img-hide-btn, .img-reroll-btn {{ opacity: 0.7; }}
}}
.section-image.fading,
.hero-image.fading {{
  opacity: 0;
  transform: scale(0.96);
  transition: opacity 0.25s ease, transform 0.25s ease;
}}

/* ── Stats bar ─────────────────────────────────────── */
.stats-bar {{
  display: flex;
  justify-content: center;
  gap: 1.5rem;
  flex-wrap: wrap;
  padding: 0.9rem 2rem;
  background: var(--bg-surface);
  border-bottom: 1px solid var(--border);
  font-size: 0.82rem;
  color: var(--text-dim);
}}
.stat {{ display: flex; align-items: center; gap: 0.35rem; }}
.stat-value {{ font-weight: 600; color: var(--text); }}

.sourcing-disclosure {{
  display: flex;
  justify-content: center;
  flex-wrap: wrap;
  gap: 0.45rem;
  padding: 0 2rem 0.85rem;
  background: var(--bg-surface);
  border-bottom: 1px solid var(--border);
}}
.sourcing-chip {{
  display: inline-flex;
  align-items: center;
  padding: 0.2rem 0.55rem;
  border-radius: 999px;
  font-size: 0.72rem;
  font-weight: 600;
  border: 1px solid var(--border-strong);
  background: var(--bg-surface-alt);
  color: var(--text-dim);
}}
.sourcing-chip-adequate {{
  border-color: color-mix(in srgb, #4caf50 35%, var(--border));
  color: color-mix(in srgb, #4caf50 75%, var(--text));
}}
.sourcing-chip-abstract {{
  border-color: color-mix(in srgb, var(--gold) 45%, var(--border));
  color: color-mix(in srgb, var(--gold) 80%, var(--text));
}}
.sourcing-chip-thin {{
  border-color: color-mix(in srgb, var(--accent) 35%, var(--border));
  color: color-mix(in srgb, var(--accent) 80%, var(--text));
}}

/* ── Layout ────────────────────────────────────────── */
.layout {{
  display: grid;
  grid-template-columns: 200px minmax(0, 1fr) 300px;
  max-width: calc(var(--max-w) + 560px);
  margin: 0 auto;
  align-items: start;
}}
@media (max-width: 1100px) {{
  .layout {{ grid-template-columns: 1fr; }}
  .toc-sidebar {{ display: none; }}
  .sources-sidebar {{
    display: flex;
    grid-column: 1;
    border-left: 0;
    border-top: 1px solid var(--border);
    max-height: none;
    position: static;
  }}
}}
@media (max-width: 900px) {{
  .layout {{ grid-template-columns: 1fr; }}
  .toc-sidebar {{ display: none; }}
}}

/* ── TOC sidebar ───────────────────────────────────── */
.toc-sidebar {{
  position: sticky; top: 0; height: 100vh; overflow-y: auto;
  padding: 3.2rem 0.8rem 2rem 1.4rem;
  border-right: 1px solid var(--border);
  font-size: 0.78rem;
}}
.toc-sidebar nav {{ position: relative; }}
.toc-sidebar nav a {{
  position: relative;
  display: block;
  color: var(--text-dim);
  text-decoration: none;
  padding: 0.42rem 0.7rem 0.42rem 0.85rem;
  margin: 1px 0;
  border-radius: 6px;
  line-height: 1.4;
  letter-spacing: -0.005em;
  transition: color 0.18s ease, background 0.18s ease, padding-left 0.18s ease;
}}
/* Sliding accent indicator on the left edge of each TOC link */
.toc-sidebar nav a::before {{
  content: '';
  position: absolute;
  left: 0; top: 50%;
  width: 2px; height: 0;
  background: var(--accent);
  transform: translateY(-50%);
  border-radius: 1px;
  transition: height 0.18s ease, opacity 0.18s ease;
  opacity: 0;
}}
.toc-sidebar nav a:hover {{
  color: var(--text);
  background: var(--accent-bg);
  padding-left: 1rem;
}}
.toc-sidebar nav a:hover::before {{
  height: 60%;
  opacity: 1;
}}
.toc-sidebar nav a.active {{
  color: var(--accent);
  font-weight: 600;
  background: var(--accent-bg);
}}
.toc-sidebar nav a.active::before {{
  height: 80%;
  opacity: 1;
}}
.toc-sidebar nav a.depth-3 {{
  padding-left: 1.3rem;
  font-size: 0.72rem;
  color: var(--text-muted);
}}
.toc-sidebar nav a.depth-3:hover {{ padding-left: 1.45rem; }}

.toc-group {{
  margin: 2px 0;
  border-radius: 6px;
}}
.toc-group > summary {{
  cursor: pointer;
  list-style: none;
  padding: 0.42rem 0.7rem 0.42rem 0.85rem;
  border-radius: 6px;
  color: var(--text-dim);
  font-size: 0.78rem;
  line-height: 1.4;
}}
.toc-group > summary::-webkit-details-marker {{ display: none; }}
.toc-group > summary::before {{
  content: '\\25B6';
  display: inline-block;
  margin-right: 0.45rem;
  font-size: 0.55em;
  color: var(--text-muted);
  transition: transform 0.18s ease;
}}
.toc-group[open] > summary::before {{ transform: rotate(90deg); }}
.toc-group > summary:hover {{
  color: var(--text);
  background: var(--accent-bg);
}}
.toc-group-title {{
  color: inherit;
  text-decoration: none;
}}
.toc-group-title:hover {{ color: var(--accent); }}
.toc-group-children {{
  padding: 0.1rem 0 0.35rem 0.55rem;
  border-left: 1px solid var(--border);
  margin: 0 0 0.35rem 0.85rem;
}}
.toc-sources-group > summary {{
  font-weight: 600;
  color: var(--text);
}}

/* ── Content ───────────────────────────────────────── */
.content {{ max-width: var(--max-w); padding: 3rem 2.5rem 4rem; }}

/* Display headings — Fraunces optical-size driven so they get more
   contrast and personality at the larger end. */
.content h2 {{
  font-family: var(--font-display);
  font-size: clamp(1.55rem, 2.4vw, 1.85rem);
  font-weight: 600;
  font-variation-settings: 'opsz' 96, 'SOFT' 50;
  margin: 3rem 0 1rem;
  padding-bottom: 0.55rem;
  border-bottom: 1px solid transparent;
  border-image: linear-gradient(90deg, var(--accent) 0%, transparent 65%) 1;
  letter-spacing: -0.022em;
  line-height: 1.2;
  color: var(--text);
}}
.content h2:first-child {{ margin-top: 0; }}
.content h3 {{
  font-family: var(--font-display);
  font-size: 1.22rem;
  font-weight: 600;
  font-variation-settings: 'opsz' 32;
  margin: 2.2rem 0 0.6rem;
  letter-spacing: -0.015em;
  color: var(--text);
}}
.content h4 {{
  font-family: var(--font-body);
  font-size: 0.78rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.12em;
  color: var(--text-dim);
  margin: 1.6rem 0 0.5rem;
}}
.content p {{ margin-bottom: 1.1rem; hanging-punctuation: first last; }}

/* Drop cap on the very first paragraph of the body — old-school editorial
   touch that anchors the reader. */
.content > p:first-of-type::first-letter,
.content > h2:first-child + p::first-letter {{
  font-family: var(--font-display);
  font-weight: 700;
  font-variation-settings: 'opsz' 144;
  font-size: 3.6em;
  line-height: 0.85;
  float: left;
  margin: 0.15em 0.12em 0 -0.04em;
  color: var(--accent);
}}

.content a {{
  color: var(--accent);
  text-decoration: underline;
  text-decoration-color: color-mix(in srgb, var(--accent) 35%, transparent);
  text-decoration-thickness: 1.5px;
  text-underline-offset: 3px;
  transition: text-decoration-color 0.15s, color 0.15s;
}}
.content a:hover {{
  text-decoration-color: var(--accent);
  color: var(--accent-light);
}}
.content ul, .content ol {{ margin: 0 0 1.1rem 1.6rem; }}
.content li {{ margin-bottom: 0.4rem; }}
.content li::marker {{ color: var(--accent); }}
.content li > ul, .content li > ol {{ margin-top: 0.4rem; margin-bottom: 0; }}
.content blockquote {{
  position: relative;
  border-left: 3px solid var(--gold);
  background: var(--gold-bg);
  padding: 1.1rem 1.4rem 1.1rem 2.6rem;
  margin: 1.5rem 0;
  border-radius: 0 var(--radius) var(--radius) 0;
  color: var(--text);
  font-family: var(--font-display);
  font-style: italic;
  font-size: 1.05rem;
  line-height: 1.55;
}}
.content blockquote::before {{
  content: '\\201C';
  position: absolute;
  left: 0.5rem; top: 0.3rem;
  font-family: var(--font-display);
  font-size: 3rem;
  font-style: normal;
  color: var(--gold);
  opacity: 0.5;
  line-height: 1;
}}
.content hr {{ border: none; height: 1px; background: linear-gradient(90deg, transparent, var(--border-strong), transparent); margin: 2rem 0; }}
.content code {{ font-family: var(--font-mono); font-size: 0.86em; background: var(--bg-surface-alt); padding: 0.15em 0.4em; border-radius: 4px; }}
.content pre {{ background: var(--bg-surface-alt); border: 1px solid var(--border); border-radius: var(--radius); padding: 1.25rem 1.5rem; overflow-x: auto; margin: 1.25rem 0; font-size: 0.86rem; line-height: 1.6; }}
.content pre code {{ background: none; padding: 0; }}
.content table {{ width: 100%; border-collapse: collapse; margin: 1.25rem 0; font-size: 0.9rem; border-radius: var(--radius); overflow: hidden; box-shadow: var(--shadow-sm); }}
.content th {{ text-align: left; padding: 0.7rem 1rem; background: var(--accent-bg); font-weight: 600; border-bottom: 2px solid var(--border-strong); }}
.content td {{ padding: 0.6rem 1rem; border-bottom: 1px solid var(--border); vertical-align: top; }}
.content tr:last-child td {{ border-bottom: none; }}
.content tr:hover td {{ background: var(--accent-bg); }}

.cite-link {{
  color: var(--accent);
  font-weight: 600;
  text-decoration: none;
  border-bottom: 1px dotted color-mix(in srgb, var(--accent) 45%, transparent);
}}
.cite-link:hover {{ border-bottom-style: solid; }}

.exec-summary-panel {{
  margin: 0 0 2rem;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--bg-surface);
  box-shadow: var(--shadow-sm);
}}
.exec-summary-panel > summary {{
  cursor: pointer;
  font-family: var(--font-display);
  font-size: 1.05rem;
  font-weight: 600;
  padding: 0.85rem 1.1rem;
  list-style: none;
  user-select: none;
}}
.exec-summary-panel > summary::-webkit-details-marker {{ display: none; }}
.exec-summary-panel > summary::before {{
  content: '\\25B6';
  display: inline-block;
  margin-right: 0.55rem;
  font-size: 0.65em;
  color: var(--text-muted);
  transition: transform 0.2s;
}}
.exec-summary-panel[open] > summary::before {{ transform: rotate(90deg); }}
.exec-summary-body {{
  padding: 0 1.1rem 1rem;
  border-top: 1px solid var(--border);
}}
.exec-summary-body p:last-child {{ margin-bottom: 0; }}

.toc-sources-label {{
  margin: 1rem 0 0.35rem;
  padding: 0 0.7rem;
  font-size: 0.68rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--text-muted);
}}

/* legacy — bottom sources panel replaced by sources-sidebar (Phase 5c) */
.sources-panel {{ margin-top: 3rem; border-top: 2px solid var(--border); padding-top: 1.5rem; }}
.sources-sidebar {{
  position: sticky;
  top: 0;
  max-height: 100vh;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  border-left: 1px solid var(--border);
  background: color-mix(in srgb, var(--bg-surface) 92%, transparent);
}}
.sources-sidebar-header {{
  padding: 1.4rem 1rem 0.75rem;
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}}
.sources-sidebar-header h2 {{
  font-size: 0.92rem;
  font-weight: 700;
  margin: 0 0 0.65rem;
  letter-spacing: -0.01em;
}}
.sources-count {{ font-weight: 500; color: var(--text-muted); font-size: 0.82em; }}
.source-filters {{
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
}}
.source-filter {{
  border: 1px solid var(--border-strong);
  background: var(--bg-surface);
  color: var(--text-dim);
  border-radius: 999px;
  padding: 0.18rem 0.55rem;
  font-size: 0.68rem;
  font-family: inherit;
  cursor: pointer;
}}
.source-filter:hover {{ background: var(--bg-surface-alt); color: var(--text); }}
.source-filter.active {{
  background: var(--accent-bg);
  border-color: color-mix(in srgb, var(--accent) 40%, var(--border));
  color: var(--accent);
  font-weight: 600;
}}
.sources-sidebar-list {{
  overflow-y: auto;
  padding: 0.65rem 0.75rem 1.25rem;
  flex: 1;
  min-height: 0;
}}
.source-card {{
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--bg-surface);
  margin-bottom: 0.55rem;
  scroll-margin-top: 4.5rem;
  transition: border-color 0.15s, box-shadow 0.15s;
}}
.source-card.source-highlight {{
  border-color: color-mix(in srgb, var(--accent) 55%, var(--border));
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--accent) 18%, transparent);
}}
.source-card[data-hidden="1"] {{ display: none; }}
.source-card-head {{
  display: grid;
  grid-template-columns: auto 1fr auto;
  gap: 0.45rem;
  align-items: start;
  padding: 0.55rem 0.65rem 0.35rem;
}}
.source-card-title-wrap {{ min-width: 0; }}
.source-card-title {{
  font-size: 0.78rem;
  font-weight: 600;
  line-height: 1.35;
  word-break: break-word;
}}
.source-card-meta {{
  margin-top: 0.15rem;
  font-size: 0.68rem;
  color: var(--text-muted);
  line-height: 1.3;
}}
.source-card-badges {{
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 0.2rem;
  flex-shrink: 0;
}}
.source-seed-badge {{
  font-size: 0.58rem;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  padding: 0.1rem 0.35rem;
  border-radius: 4px;
  border: 1px solid var(--border-strong);
  color: var(--text-dim);
}}
.tier-badge {{
  font-size: 0.58rem;
  font-weight: 700;
  letter-spacing: 0.02em;
  padding: 0.12rem 0.38rem;
  border-radius: 999px;
  border: 1px solid var(--border-strong);
  white-space: nowrap;
}}
.tier-adequate {{
  border-color: color-mix(in srgb, #4caf50 35%, var(--border));
  color: color-mix(in srgb, #4caf50 75%, var(--text));
}}
.tier-abstract {{
  border-color: color-mix(in srgb, var(--gold) 45%, var(--border));
  color: color-mix(in srgb, var(--gold) 80%, var(--text));
}}
.tier-thin, .tier-unknown {{
  border-color: color-mix(in srgb, var(--accent) 35%, var(--border));
  color: color-mix(in srgb, var(--accent) 75%, var(--text));
}}
.source-card-body {{
  padding: 0 0.65rem 0.6rem;
  font-size: 0.72rem;
  color: var(--text-dim);
}}
.source-detail-row {{
  display: flex;
  gap: 0.45rem;
  align-items: baseline;
  margin: 0.15rem 0;
  min-width: 0;
}}
.source-detail-label {{
  flex-shrink: 0;
  width: 3.2rem;
  font-size: 0.62rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--text-muted);
}}
.source-detail-value, .source-detail-link {{
  min-width: 0;
  word-break: break-word;
}}
.source-detail-link {{
  color: var(--accent);
  text-decoration: none;
}}
.source-detail-link:hover {{ text-decoration: underline; }}
.source-tier-note {{
  margin: 0.35rem 0 0.15rem;
  font-size: 0.68rem;
  line-height: 1.4;
  color: var(--text-muted);
  font-style: italic;
}}
.source-excerpt {{
  margin-top: 0.35rem;
  border-top: 1px dashed var(--border);
  padding-top: 0.35rem;
}}
.source-excerpt > summary {{
  cursor: pointer;
  font-size: 0.68rem;
  font-weight: 600;
  color: var(--text-dim);
  list-style: none;
  user-select: none;
}}
.source-excerpt > summary::-webkit-details-marker {{ display: none; }}
.source-excerpt > summary::before {{
  content: '\\25B6';
  display: inline-block;
  margin-right: 0.35rem;
  font-size: 0.55em;
  color: var(--text-muted);
  transition: transform 0.15s;
}}
.source-excerpt[open] > summary::before {{ transform: rotate(90deg); }}
.source-excerpt p {{
  margin: 0.35rem 0 0;
  line-height: 1.45;
  color: var(--text-dim);
}}
.source-card-head .snum {{
  color: var(--text-muted);
  font-size: 0.72rem;
  font-weight: 700;
  flex-shrink: 0;
  padding-top: 0.1rem;
}}
.sources-list .snum {{
  color: var(--text-muted); font-size: 0.75rem;
  min-width: 1.5rem; text-align: right; flex-shrink: 0;
}}
.sources-list .sdomain {{
  color: var(--text-muted); font-size: 0.75rem;
  margin-left: auto; flex-shrink: 0;
}}

/* ── Chat-about CTA ────────────────────────────────── */
.chat-cta {{
  margin: 3rem 0 1rem; padding: 1.5rem;
  text-align: center;
  border: 1px solid var(--border); border-radius: 12px;
  background: var(--bg-surface);
}}
.chat-cta-btn {{
  display: inline-flex; align-items: center; gap: 8px;
  padding: 10px 18px; font-size: 0.95rem; font-weight: 600;
  background: var(--accent); color: #fff;
  border: none; border-radius: 8px; cursor: pointer;
  font-family: inherit;
  transition: filter 0.15s, transform 0.05s;
}}
.chat-cta-btn:hover:not(:disabled) {{ filter: brightness(1.1); }}
.chat-cta-btn:active:not(:disabled) {{ transform: translateY(1px); }}
.chat-cta-btn:disabled {{ opacity: 0.6; cursor: progress; }}
.chat-cta-hint {{
  margin-top: 8px; font-size: 0.8rem; color: var(--text-muted);
}}

/* ── Footer ────────────────────────────────────────── */
.report-footer {{
  text-align: center; padding: 2rem; font-size: 0.75rem;
  color: var(--text-muted); border-top: 1px solid var(--border); margin-top: 2rem;
}}

/* ── Animations ────────────────────────────────────── */
@media (prefers-reduced-motion: no-preference) {{
  .content h2, .content h3, .content p, .content ul, .content ol,
  .content blockquote, .content table, .content pre, .section-image {{
    animation: fadeUp 0.4s ease both;
  }}
  @keyframes fadeUp {{
    from {{ opacity: 0; transform: translateY(8px); }}
    to   {{ opacity: 1; transform: translateY(0); }}
  }}
}}

/* ── Print ─────────────────────────────────────────── */
@media print {{
  .toc-sidebar, .toolbar {{ display: none !important; }}
  .layout {{ grid-template-columns: 1fr; }}
  .hero {{ -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
}}
{category_css}
</style>
</head>
<body class="{body_class}">

<!-- Toolbar: Export + Restore hidden images -->
<div class="toolbar">
  {restore_btn_html}
  <div class="dropdown">
    <button id="btn-export" title="Export">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
      Export &#9662;
    </button>
    <div class="dropdown-menu" id="export-menu">
      <button id="btn-export-md">Download Markdown</button>
      <button id="btn-export-bib">Download BibTeX</button>
      <button id="btn-export-csl">Download CSL JSON</button>
      <button id="btn-save-zotero">Save cited to Zotero</button>
      <button id="btn-pdf">Save as PDF</button>
      <button id="btn-html">Download HTML</button>
    </div>
  </div>
</div>

<div class="hero">
  <div class="hero-label">Nobody &mdash; Deep Research Report</div>
  <h1>{question_html}</h1>
</div>

{hero_image_html}

<div class="stats-bar">
  {stats_html}
</div>

{sourcing_disclosure_html}

<div class="layout">
  <aside class="toc-sidebar">
    <nav>
      {toc_html}
    </nav>
  </aside>
  <main class="content">
    {report_html}

    {chat_cta_html}
  </main>
  {sources_sidebar_html}
</div>

<div class="report-footer">
  Generated by Nobody Deep Research &middot; {timestamp}
</div>

<script>
(function() {{
  // ESC closes the report tab. window.close() works when the tab was
  // opened via window.open() (which is how the panel launches it). If the
  // browser blocks self-close (rare — e.g. report opened by direct URL),
  // fall back to history.back() so ESC still feels responsive.
  document.addEventListener('keydown', function(e) {{
    if (e.key !== 'Escape' || e.defaultPrevented) return;
    // Don't hijack ESC while typing in a field or with an open dropdown.
    var t = e.target;
    if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return;
    var menu = document.getElementById('export-menu');
    if (menu && menu.classList.contains('open')) {{ menu.classList.remove('open'); return; }}
    try {{ window.close(); }} catch (err) {{}}
    // window.close() is a no-op when the tab wasn't script-opened; in that
    // case fall back to navigation so the key isn't ignored.
    setTimeout(function() {{ if (!window.closed) history.back(); }}, 50);
  }});

  // Export dropdown toggle
  var exportBtn = document.getElementById('btn-export');
  var exportMenu = document.getElementById('export-menu');
  exportBtn.addEventListener('click', function(e) {{
    e.stopPropagation();
    exportMenu.classList.toggle('open');
  }});
  document.addEventListener('click', function() {{ exportMenu.classList.remove('open'); }});

  // Save as PDF (browser print)
  document.getElementById('btn-pdf').addEventListener('click', function() {{
    exportMenu.classList.remove('open');
    window.print();
  }});

  // Download HTML
  document.getElementById('btn-html').addEventListener('click', function() {{
    exportMenu.classList.remove('open');
    var blob = new Blob([document.documentElement.outerHTML], {{ type: 'text/html' }});
    var a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = document.title.replace(/[^a-z0-9]+/gi, '-').substring(0, 60) + '.html';
    a.click();
  }});

  function __downloadExport(fmt, scope) {{
    if (!__sessionId) return;
    exportMenu.classList.remove('open');
    var url = '/api/research/' + encodeURIComponent(__sessionId)
      + '/export?format=' + encodeURIComponent(fmt)
      + '&scope=' + encodeURIComponent(scope || 'cited');
    var a = document.createElement('a');
    a.href = url;
    a.rel = 'noopener';
    document.body.appendChild(a);
    a.click();
    a.remove();
  }}
  var btnMd = document.getElementById('btn-export-md');
  if (btnMd) btnMd.addEventListener('click', function() {{ __downloadExport('markdown'); }});
  var btnBib = document.getElementById('btn-export-bib');
  if (btnBib) btnBib.addEventListener('click', function() {{ __downloadExport('bibtex', 'cited'); }});
  var btnCsl = document.getElementById('btn-export-csl');
  if (btnCsl) btnCsl.addEventListener('click', function() {{ __downloadExport('csl-json', 'cited'); }});

  var btnZotero = document.getElementById('btn-save-zotero');
  if (btnZotero && __sessionId) {{
    btnZotero.addEventListener('click', function() {{
      exportMenu.classList.remove('open');
      var orig = btnZotero.textContent;
      btnZotero.disabled = true;
      btnZotero.textContent = 'Saving…';
      fetch('/api/research/' + encodeURIComponent(__sessionId) + '/save-to-zotero', {{
        method: 'POST',
        credentials: 'same-origin',
        headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify({{ scope: 'cited' }}),
      }})
        .then(function(r) {{ return r.json().then(function(d) {{ return {{ ok: r.ok, data: d }}; }}); }})
        .then(function(out) {{
          if (!out.ok) throw new Error(out.data.detail || 'Save failed');
          btnZotero.textContent = 'Saved ' + (out.data.created || 0);
          setTimeout(function() {{ btnZotero.textContent = orig; btnZotero.disabled = false; }}, 2500);
        }})
        .catch(function(err) {{
          btnZotero.textContent = 'Failed';
          btnZotero.title = err.message || 'Save failed';
          setTimeout(function() {{ btnZotero.textContent = orig; btnZotero.disabled = false; btnZotero.title = ''; }}, 2500);
        }});
    }});
  }}

  document.querySelectorAll('.cite-link').forEach(function(link) {{
    link.addEventListener('click', function(e) {{
      var cite = link.getAttribute('data-cite');
      if (!cite) return;
      var target = document.getElementById('source-' + cite);
      if (!target) return;
      e.preventDefault();
      var sidebar = document.querySelector('.sources-sidebar');
      if (sidebar && sidebar.offsetParent !== null) {{
        target.scrollIntoView({{ behavior: 'smooth', block: 'center' }});
      }} else {{
        target.scrollIntoView({{ behavior: 'smooth', block: 'start' }});
      }}
      var excerpt = target.querySelector('.source-excerpt');
      if (excerpt && !excerpt.open) excerpt.open = true;
      target.classList.add('source-highlight');
      setTimeout(function() {{ target.classList.remove('source-highlight'); }}, 1600);
    }});
  }});

  document.querySelectorAll('.source-filter').forEach(function(btn) {{
    btn.addEventListener('click', function() {{
      document.querySelectorAll('.source-filter').forEach(function(b) {{ b.classList.remove('active'); }});
      btn.classList.add('active');
      var filter = btn.getAttribute('data-filter') || 'all';
      document.querySelectorAll('.source-card').forEach(function(card) {{
        var show = filter === 'all'
          || (filter === 'seed' && card.getAttribute('data-seed') === '1')
          || (filter === 'adequate' && card.getAttribute('data-tier') === 'adequate')
          || (filter === 'thin' && card.getAttribute('data-tier') === 'thin');
        card.setAttribute('data-hidden', show ? '0' : '1');
      }});
    }});
  }});

  function __openInternalHref(href) {{
    if (!href) return;
    var dest = href.charAt(0) === '#' ? ('/' + href) : href;
    try {{
      if (window.opener && !window.opener.closed) {{
        window.opener.location.href = dest;
        window.opener.focus();
        return;
      }}
    }} catch (err) {{}}
    window.location.href = dest;
  }}

  function __openInternalNode(nodeId) {{
    if (!nodeId) return;
    try {{
      if (window.opener && !window.opener.closed) {{
        window.opener.postMessage({{ type: 'odysseus-open-knowledge', nodeId: nodeId }}, window.location.origin);
        window.opener.focus();
        return;
      }}
    }} catch (err) {{}}
  }}

  document.querySelectorAll('.source-detail-link.source-internal, .source-detail-link[data-node-id]').forEach(function(link) {{
    if (!link.getAttribute('data-node-id') && !link.classList.contains('source-internal')) return;
    link.addEventListener('click', function(e) {{
      var href = link.getAttribute('href') || '';
      if (!href || href.indexOf('http') === 0) return;
      e.preventDefault();
      var nodeId = link.getAttribute('data-node-id') || '';
      if (nodeId) {{
        __openInternalNode(nodeId);
        return;
      }}
      __openInternalHref(href);
    }});
  }});

  document.querySelectorAll('.sources-list a.source-internal, .sources-list a[data-node-id]').forEach(function(link) {{
    link.addEventListener('click', function(e) {{
      var href = link.getAttribute('href') || '';
      if (!href || href.indexOf('http') === 0) return;
      e.preventDefault();
      var panel = link.closest('.sources-panel details');
      if (panel && !panel.open) panel.open = true;
      var nodeId = link.getAttribute('data-node-id') || '';
      if (nodeId) {{
        __openInternalNode(nodeId);
        return;
      }}
      __openInternalHref(href);
    }});
  }});

  // Per-image hide — fades the image out, then POSTs to the backend so
  // future renders of this report skip the URL. Falls back to a silent
  // no-op if there's no session_id (e.g. the report was opened from a
  // saved-HTML download where the backend isn't reachable).
  var __sessionId = {session_id_js};
  // Unused scraped images — the reroll pool. Each is used at most once.
  var __spareImages = {spare_images_js};

  // Persist a rejected URL so future renders skip it.
  function __persistHide(url) {{
    if (!__sessionId || !url) return;
    fetch('/api/research/' + encodeURIComponent(__sessionId) + '/hide-image', {{
      method: 'POST',
      credentials: 'same-origin',
      headers: {{ 'Content-Type': 'application/json' }},
      body: JSON.stringify({{ url: url }}),
    }}).catch(function(err) {{ console.warn('hide-image POST failed', err); }});
  }}

  // Once the pool is empty, there's nothing to swap to — hide all reroll btns.
  function __syncRerollAvailability() {{
    if (__spareImages.length === 0) {{
      document.querySelectorAll('.img-reroll-btn').forEach(function(b) {{ b.disabled = true; }});
    }}
  }}

  document.querySelectorAll('.img-hide-btn').forEach(function(btn) {{
    btn.addEventListener('click', function(e) {{
      e.preventDefault(); e.stopPropagation();
      var wrap = btn.closest('[data-img-url]');
      if (!wrap) return;
      var url = wrap.dataset.imgUrl;
      wrap.classList.add('fading');
      setTimeout(function() {{ wrap.remove(); }}, 280);
      __persistHide(url);
    }});
  }});

  // Reroll — swap the current image for the next unused scraped one, and
  // persist-hide the rejected URL so it won't resurface on reload.
  document.querySelectorAll('.img-reroll-btn').forEach(function(btn) {{
    btn.addEventListener('click', function(e) {{
      e.preventDefault(); e.stopPropagation();
      // Per-button busy flag — a rapid double-click would otherwise both
      // shift the spare pool, but only the second probe's image would land,
      // silently consuming the first one. Bail until finish() clears it.
      if (btn.dataset._busy === '1') return;
      if (__spareImages.length === 0) {{ btn.disabled = true; return; }}
      var wrap = btn.closest('[data-img-url]');
      if (!wrap) return;
      var img = wrap.querySelector('img');
      if (!img) return;
      btn.dataset._busy = '1';
      var oldUrl = wrap.dataset.imgUrl;
      var newUrl = __spareImages.shift();
      btn.classList.add('spinning');
      // Swap once the new image has loaded (or failed) to avoid a flash of empty.
      var probe = new Image();
      var done = false;
      var finish = function(ok) {{
        if (done) return; done = true;
        btn.classList.remove('spinning');
        delete btn.dataset._busy;
        if (ok) {{
          img.src = newUrl;
          wrap.dataset.imgUrl = newUrl;
          __persistHide(oldUrl);
        }} else {{
          // Bad candidate — persist-hide it so it can't resurface on reload,
          // then try the next spare if any remain. Busy flag already cleared
          // so the synthetic click below proceeds.
          __persistHide(newUrl);
          if (__spareImages.length) btn.click();
        }}
        __syncRerollAvailability();
      }};
      probe.onload = function() {{ finish(true); }};
      probe.onerror = function() {{ finish(false); }};
      probe.src = newUrl;
    }});
  }});
  __syncRerollAvailability();

  // "Show hidden (N)" button — clears the hidden_images list on the
  // server, then reloads the page so all images come back.
  var restoreBtn = document.getElementById('btn-restore-images');
  if (restoreBtn && __sessionId) {{
    restoreBtn.addEventListener('click', function() {{
      restoreBtn.disabled = true;
      restoreBtn.textContent = 'Restoring…';
      fetch('/api/research/' + encodeURIComponent(__sessionId) + '/unhide-images', {{
        method: 'POST', credentials: 'same-origin',
      }}).then(function() {{ window.location.reload(); }})
        .catch(function(err) {{
          restoreBtn.disabled = false;
          restoreBtn.textContent = 'Failed — retry?';
          console.warn('unhide-images POST failed', err);
        }});
    }});
  }}

  // TOC: explicit smooth-scroll handler (some browsers/anchor plugins
  // bypass the CSS `scroll-behavior: smooth` rule on hash clicks).
  // Also keeps the URL hash updated and toggles an `.active` highlight.
  var tocLinks = document.querySelectorAll('.toc-sidebar nav a[href^="#"]');
  tocLinks.forEach(function(link) {{
    link.addEventListener('click', function(e) {{
      var id = link.getAttribute('href').slice(1);
      var target = document.getElementById(id);
      if (!target) return;
      e.preventDefault();
      if (link.classList.contains('toc-group-title')) e.stopPropagation();
      var panel = target.closest('details');
      if (panel && !panel.open) panel.open = true;
      target.scrollIntoView({{ behavior: 'smooth', block: 'start' }});
      history.replaceState(null, '', '#' + id);
    }});
  }});
  document.querySelectorAll('.toc-group-title').forEach(function(link) {{
    link.addEventListener('click', function(e) {{ e.stopPropagation(); }});
  }});

  // Highlight the TOC entry that matches whichever heading is currently
  // closest to the top of the viewport. IntersectionObserver keeps it
  // cheap (no scroll listener spam).
  var tocMap = {{}};
  tocLinks.forEach(function(link) {{
    tocMap[link.getAttribute('href').slice(1)] = link;
  }});
  var activeId = null;
  function setActive(id) {{
    if (id === activeId) return;
    if (activeId && tocMap[activeId]) tocMap[activeId].classList.remove('active');
    if (id && tocMap[id]) tocMap[id].classList.add('active');
    activeId = id;
  }}
  var headings = document.querySelectorAll('.content h2[id], .content h3[id]');
  if (headings.length && 'IntersectionObserver' in window) {{
    var visible = new Set();
    var io = new IntersectionObserver(function(entries) {{
      entries.forEach(function(en) {{
        if (en.isIntersecting) visible.add(en.target.id);
        else visible.delete(en.target.id);
      }});
      // Pick the visible heading that's furthest down in document order
      // before the current scroll — i.e. the section we're reading.
      var current = null;
      for (var i = 0; i < headings.length; i++) {{
        if (visible.has(headings[i].id)) {{ current = headings[i].id; break; }}
      }}
      if (current) setActive(current);
    }}, {{ rootMargin: '-10% 0px -75% 0px', threshold: 0 }});
    headings.forEach(function(h) {{ io.observe(h); }});
  }}

  // Chat about this research — POST to spinoff and redirect to the new chat
  var chatBtn = document.getElementById('btn-chat-about');
  if (chatBtn) {{
    chatBtn.addEventListener('click', function() {{
      var researchId = chatBtn.dataset.researchId;
      if (!researchId) return;
      var origLabel = chatBtn.innerHTML;
      chatBtn.disabled = true;
      chatBtn.innerHTML = '<span>Creating chat…</span>';
      fetch('/api/research/spinoff/' + encodeURIComponent(researchId), {{
        method: 'POST', credentials: 'same-origin',
      }}).then(function(res) {{
        if (!res.ok) {{
          return res.json().then(function(d) {{
            throw new Error(d && d.detail ? d.detail : ('HTTP ' + res.status));
          }}, function() {{ throw new Error('HTTP ' + res.status); }});
        }}
        return res.json();
      }}).then(function(data) {{
        if (!data || !data.session_id) {{
          throw new Error('Server did not return a session id');
        }}
        var url = '/#' + data.session_id;
        var opened = false;
        // The report typically opens in a new tab — if we have access to the
        // original Odysseus tab, navigate it and close this report tab so the
        // user lands directly in the new chat.
        try {{
          if (window.opener && !window.opener.closed) {{
            window.opener.location.href = url;
            window.opener.location.reload();
            window.opener.focus();
            opened = true;
            window.close();
          }}
        }} catch (e) {{ /* cross-origin or detached opener — fall through */ }}
        if (!opened) {{
          // No opener (report was opened directly via URL) — open the chat in a
          // new tab so the report stays available.
          var w = window.open(url, '_blank');
          if (w) {{
            chatBtn.disabled = false;
            chatBtn.innerHTML = '<span>Chat opened in new tab</span>';
          }} else {{
            // Popup blocked — navigate this tab as a last resort.
            window.location.href = url;
            window.location.reload();
          }}
        }}
      }}).catch(function(err) {{
        chatBtn.disabled = false;
        chatBtn.innerHTML = origLabel;
        alert('Could not start follow-up chat: ' + err.message);
      }});
    }});
  }}
}})();

// Colorize comparison table cells
if (document.body.classList.contains('category-comparison')) {{
  const pos = /^(yes|excellent|best|great|strong|fast|high|superior|winner|free|unlimited|native|full|advanced|built[- ]in|✓|✅|⭐)/i;
  const neg = /^(no|none|poor|weak|slow|low|limited|lacking|missing|basic|minimal|✗|❌|N\\/A$)/i;
  const mid = /^(moderate|average|fair|partial|some|decent|okay|mixed|varies|depends)/i;
  document.querySelectorAll('.content table td').forEach(td => {{
    if (td.cellIndex === 0) return;
    const t = td.textContent.trim();
    if (pos.test(t)) td.classList.add('cmp-pos');
    else if (neg.test(t)) td.classList.add('cmp-neg');
    else if (mid.test(t)) td.classList.add('cmp-mid');
  }});
}}
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _category_css(category: Optional[str]) -> str:
    category = category or "academic"
    # Per-category palette overrides — applied BEFORE the structural rules so
    # everything that reads --accent / --aurora-* automatically retints.
    palettes = """
/* ── Category palettes ───────────────────────────────────
   Override the accent + aurora vars per category so each report
   type has a distinct visual identity. */
body.category-academic {
  --accent: #2c5282;
  --accent-light: #4a7ab8;
  --accent-bg: rgba(44,82,130,0.07);
  --aurora-a: rgba(44,82,130,0.11);
  --aurora-b: rgba(90,120,160,0.06);
  --aurora-c: rgba(64,98,128,0.06);
}
body.category-product {
  --accent: #2a8a8c;
  --accent-light: #4ab0b2;
  --accent-bg: rgba(42,138,140,0.07);
  --aurora-a: rgba(42,138,140,0.11);
  --aurora-b: rgba(201,149,46,0.06);
  --aurora-c: rgba(64,98,128,0.06);
}
body.category-comparison {
  --accent: #7a4cb8;
  --accent-light: #9d76d0;
  --accent-bg: rgba(122,76,184,0.07);
  --aurora-a: rgba(122,76,184,0.11);
  --aurora-b: rgba(184,84,58,0.05);
  --aurora-c: rgba(64,98,128,0.07);
}
body.category-howto {
  --accent: #3d8a3d;
  --accent-light: #62b162;
  --accent-bg: rgba(61,138,61,0.07);
  --aurora-a: rgba(61,138,61,0.11);
  --aurora-b: rgba(201,149,46,0.07);
  --aurora-c: rgba(42,138,140,0.05);
}
body.category-landscape {
  --accent: #b88a2e;
  --accent-light: #d4a955;
  --accent-bg: rgba(184,138,46,0.08);
  --aurora-a: rgba(184,138,46,0.13);
  --aurora-b: rgba(184,84,58,0.06);
  --aurora-c: rgba(122,76,184,0.05);
}
@media (prefers-color-scheme: dark) {
  body.category-academic {
    --accent: #7eb3e8; --accent-light: #a8cdf0;
    --accent-bg: rgba(126,179,232,0.10);
    --aurora-a: rgba(126,179,232,0.13);
    --aurora-b: rgba(160,190,220,0.07);
    --aurora-c: rgba(125,180,224,0.08);
  }
  body.category-product {
    --accent: #5cc8cb; --accent-light: #8fdde0;
    --accent-bg: rgba(92,200,203,0.10);
    --aurora-a: rgba(92,200,203,0.13);
    --aurora-b: rgba(232,192,90,0.07);
    --aurora-c: rgba(125,180,224,0.08);
  }
  body.category-comparison {
    --accent: #b896e8; --accent-light: #d0b8f0;
    --accent-bg: rgba(184,150,232,0.10);
    --aurora-a: rgba(184,150,232,0.13);
    --aurora-b: rgba(232,143,115,0.06);
    --aurora-c: rgba(125,180,224,0.08);
  }
  body.category-howto {
    --accent: #82c882; --accent-light: #a8dba8;
    --accent-bg: rgba(130,200,130,0.09);
    --aurora-a: rgba(130,200,130,0.12);
    --aurora-b: rgba(232,192,90,0.07);
    --aurora-c: rgba(92,200,203,0.07);
  }
  body.category-landscape {
    --accent: #e6c069; --accent-light: #f0d390;
    --accent-bg: rgba(230,192,105,0.10);
    --aurora-a: rgba(230,192,105,0.15);
    --aurora-b: rgba(232,143,115,0.07);
    --aurora-c: rgba(184,150,232,0.06);
  }
}

/* ── Per-category font pairings ───────────────────────
   Body font shifts between serif (long-form categories) and sans
   (practical/data categories) so each report reads as a different
   publication, not just a re-tinted version of the same template. */

/* Long-form: literary serif for both display and body */
body:not([class*="category-"]),
body.category-landscape {
  --font-body: 'Source Serif 4', 'Iowan Old Style', Georgia, serif;
}

/* Comparison: analytical serif display + clean sans body */
body.category-comparison {
  --font-display: 'Playfair Display', Georgia, serif;
  --font-body: 'Inter', system-ui, sans-serif;
}

/* How-to: friendly geometric sans, top to bottom */
body.category-howto {
  --font-display: 'Manrope', system-ui, sans-serif;
  --font-body: 'Inter', system-ui, sans-serif;
}

/* Product: techy/engineery — IBM Plex Sans display + Inter body */
body.category-product {
  --font-display: 'IBM Plex Sans', system-ui, sans-serif;
  --font-body: 'Inter', system-ui, sans-serif;
}

/* Source Serif sits visually larger than Inter at the same px — pull it
   back one notch for the categories that use it as body so line length
   and rhythm stay comparable across categories. */
body:not([class*="category-"]) body, /* no-op selector, kept for clarity */
body.category-landscape { font-size: 16.5px; }

/* Drop cap looks bad on geometric sans — kill it for those categories */
body.category-product   .content > p:first-of-type::first-letter,
body.category-howto     .content > p:first-of-type::first-letter,
body.category-comparison .content > p:first-of-type::first-letter,
body.category-product   .content > h2:first-child + p::first-letter,
body.category-howto     .content > h2:first-child + p::first-letter,
body.category-comparison .content > h2:first-child + p::first-letter {
  font-size: 1em; float: none; margin: 0; color: inherit;
  font-family: inherit; font-weight: inherit;
}

/* ── Per-category background effects ───────────────
   Each category overrides body::before so the page reads as a
   distinctly-textured surface. Aurora stays the default. */

/* Product → blueprint grid that slowly pans */
body.category-product::before {
  background:
    linear-gradient(to right, var(--aurora-a) 1px, transparent 1px),
    linear-gradient(to bottom, var(--aurora-a) 1px, transparent 1px),
    radial-gradient(70vw 60vh at 50% 50%, var(--aurora-a) 0%, transparent 75%);
  background-size: 56px 56px, 56px 56px, 100% 100%;
  filter: none;
  animation: cat-grid-pan 60s linear infinite;
}
@keyframes cat-grid-pan {
  to { background-position: 56px 56px, 56px 56px, 0 0; }
}

/* Comparison → dot grid + slow opacity pulse */
body.category-comparison::before {
  background:
    radial-gradient(circle, var(--aurora-a) 1.4px, transparent 1.8px),
    radial-gradient(60vw 55vh at 25% 25%, var(--aurora-b) 0%, transparent 65%),
    radial-gradient(60vw 55vh at 75% 75%, var(--aurora-c) 0%, transparent 65%);
  background-size: 26px 26px, 100% 100%, 100% 100%;
  filter: none;
  animation: cat-dot-pulse 14s ease-in-out infinite alternate;
}
@keyframes cat-dot-pulse {
  from { opacity: 0.65; }
  to   { opacity: 1; }
}

/* How-to → flat surface with a very subtle vignette. Drop the flow-lines
   pattern — it competes visually with the step number rails on the
   right-hand side of each H2. The reading should feel like an O'Reilly
   procedure: clean, scannable, no decoration in the way. */
body.category-howto::before {
  background:
    radial-gradient(70vw 70vh at 50% 0%, var(--aurora-a) 0%, transparent 60%),
    radial-gradient(50vw 50vh at 50% 100%, var(--aurora-b) 0%, transparent 65%);
  filter: blur(40px);
  animation: none;
}

/* Landscape → horizontal horizon bands that slowly shift sideways */
body.category-landscape::before {
  background:
    linear-gradient(
      180deg,
      transparent 0%,
      var(--aurora-a) 22%,
      transparent 35%,
      var(--aurora-b) 55%,
      transparent 68%,
      var(--aurora-c) 85%,
      transparent 100%
    );
  background-size: 100% 200%;
  filter: blur(40px);
  animation: cat-horizon-drift 36s ease-in-out infinite alternate;
}
@keyframes cat-horizon-drift {
  0%   { background-position: 0 0; }
  100% { background-position: 0 100%; }
}

@media (prefers-reduced-motion: reduce) {
  body.category-product::before,
  body.category-comparison::before,
  body.category-howto::before,
  body.category-landscape::before {
    animation: none;
  }
}

/* ─────────────────────────────────────────────────────
   PER-CATEGORY STRUCTURAL TREATMENTS
   Each category gets distinctive structural CSS so the page
   reads as a different publication — not just retinted.
   ───────────────────────────────────────────────────── */

/* ── HOWTO: O'Reilly-style numbered procedure ─────── */
body.category-howto .content { counter-reset: howto-step; }
body.category-howto .content h2 {
  counter-increment: howto-step;
  display: flex; align-items: center; gap: 14px;
  border-bottom: none;
  padding-left: 0;
  margin-top: 3.5rem;
}
body.category-howto .content h2::before {
  content: counter(howto-step);
  display: inline-flex; align-items: center; justify-content: center;
  flex-shrink: 0;
  width: 40px; height: 40px;
  border-radius: 12px;
  background: var(--accent);
  color: #fff;
  font-family: var(--font-display);
  font-size: 1.15rem;
  font-weight: 700;
  letter-spacing: 0;
  box-shadow: 0 4px 12px color-mix(in srgb, var(--accent) 30%, transparent);
}
/* Step body gets a colored left rail so you can scan "this is step 1's stuff" */
body.category-howto .content h2 ~ p,
body.category-howto .content h2 ~ ul,
body.category-howto .content h2 ~ ol,
body.category-howto .content h2 ~ pre,
body.category-howto .content h2 ~ blockquote {
  border-left: 2px solid color-mix(in srgb, var(--accent) 25%, transparent);
  padding-left: 1rem;
  margin-left: 4px;
}
body.category-howto .content h2:has(+ *) ~ h2 ~ * { border-left: none; padding-left: 0; margin-left: 0; }
/* Terminal-style code blocks — green $ prompt, monospaced, dark surface */
body.category-howto .content pre {
  background: #1a1a1e;
  color: #d4e4d4;
  border: 1px solid color-mix(in srgb, var(--accent) 20%, transparent);
  border-radius: 8px;
  position: relative;
  padding-left: 2.6rem;
}
body.category-howto .content pre::before {
  content: '$';
  position: absolute;
  left: 1.1rem; top: 1.15rem;
  color: var(--accent);
  font-family: var(--font-mono);
  font-weight: 700;
  font-size: 0.86rem;
  opacity: 0.85;
}
body.category-howto .content pre code { color: inherit; }

/* ── LANDSCAPE: editorial briefing with H3 player cards ─ */
body.category-landscape .content h3 {
  /* Each H3 in landscape = a "player" in the field — give it a card frame */
  margin-top: 2.5rem;
  padding: 14px 18px 4px;
  border-left: 3px solid var(--accent);
  background: color-mix(in srgb, var(--accent) 4%, transparent);
  border-radius: 0 8px 8px 0;
  font-family: var(--font-display);
  font-size: 1.18rem;
}
body.category-landscape .content h3 + p {
  margin-top: 0;
  padding: 0 18px 14px;
  background: color-mix(in srgb, var(--accent) 4%, transparent);
  border-left: 3px solid var(--accent);
  margin-left: 0;
  border-radius: 0 0 8px 0;
}
/* Pull-quote treatment for any standalone blockquote */
body.category-landscape .content blockquote {
  font-size: 1.2rem;
  line-height: 1.5;
  max-width: 90%;
  margin: 2rem auto;
  text-align: center;
  border-left: none;
  border-top: 1px solid color-mix(in srgb, var(--accent) 40%, transparent);
  border-bottom: 1px solid color-mix(in srgb, var(--accent) 40%, transparent);
  background: transparent;
  border-radius: 0;
  padding: 1.5rem 1rem;
  font-style: italic;
}
body.category-landscape .content blockquote::before {
  display: none;
}

/* ── COMPARISON: lab-report tables with winner badges ─ */
body.category-comparison .content {
  font-feature-settings: 'tnum' on, 'ss01';  /* tabular numerals for tables */
}
body.category-comparison .content table {
  font-size: 0.92rem;
  box-shadow: 0 6px 20px rgba(0,0,0,0.06);
}
body.category-comparison .content th {
  background: color-mix(in srgb, var(--accent) 18%, var(--bg-surface));
  color: var(--text);
  text-transform: uppercase;
  letter-spacing: 0.1em;
  font-size: 0.72rem;
  font-weight: 700;
}
body.category-comparison .content td:first-child {
  font-weight: 600;
  background: color-mix(in srgb, var(--accent) 6%, transparent);
}
/* The first H3 inside a comparison report often names the recommended pick */
body.category-comparison .content h3:first-of-type::after {
  content: 'Pick';
  display: inline-block;
  margin-left: 10px;
  padding: 2px 10px;
  background: var(--accent);
  color: #fff;
  font-family: var(--font-body);
  font-size: 0.65rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  border-radius: 999px;
  vertical-align: middle;
}

/* ── PRODUCT: spec-sheet cards for each H3 ─────────── */
body.category-product .content h3 {
  /* Each product gets a spec-card frame — bordered, slight bg lift */
  margin-top: 2.4rem;
  padding: 16px 18px;
  border: 1px solid color-mix(in srgb, var(--accent) 28%, var(--border));
  background: var(--bg-surface);
  border-radius: 10px;
  display: flex; align-items: baseline; gap: 10px;
  font-family: var(--font-display);
  letter-spacing: -0.01em;
  box-shadow: 0 2px 8px rgba(0,0,0,0.04);
}
body.category-product .content h3::after {
  /* small "spec" tag on each product heading */
  content: 'SPEC';
  margin-left: auto;
  font-family: var(--font-body);
  font-size: 0.6rem;
  font-weight: 700;
  letter-spacing: 0.18em;
  color: var(--accent);
  background: color-mix(in srgb, var(--accent) 10%, transparent);
  padding: 3px 8px;
  border-radius: 4px;
}
body.category-product .content h3 + p,
body.category-product .content h3 + ul,
body.category-product .content h3 + table {
  margin-top: 0.8rem;
  padding-left: 4px;
}
"""
    styles = {
        "product": """
/* Product category */
.category-product .content h3 {
  display:flex; align-items:baseline; gap:8px;
  border-bottom:1px solid var(--border); padding-bottom:6px;
}
.category-product .content table {
  width:100%; border-collapse:collapse; margin:1.2em 0; font-size:0.92em;
}
.category-product .content table th {
  background:var(--accent); color:#fff; padding:8px 12px; text-align:left;
}
.category-product .content table td { padding:8px 12px; border-bottom:1px solid var(--border); }
.category-product .content table tr:nth-child(even) td { background:var(--bg-surface); }
.category-product .content ul { columns:2; column-gap:2em; }
@media (max-width:600px) { .category-product .content ul { columns:1; } }
.category-product .content a[href*="amazon"],
.category-product .content a[href*="ebay"],
.category-product .content a[href*="shop"],
.category-product .content a[href*="buy"] {
  display:inline-block; padding:3px 10px; border-radius:4px;
  background:var(--accent); color:#fff; text-decoration:none; font-size:0.85em; margin:2px 4px;
}
.quick-links-bar {
  display:flex; flex-wrap:wrap; gap:6px; padding:12px 0; margin-bottom:12px;
  border-bottom:1px solid var(--border);
}
.quick-link {
  padding:5px 12px; border-radius:16px; font-size:0.82em; text-decoration:none;
  border:1px solid var(--border); color:var(--text); transition:all 0.15s;
  white-space:nowrap;
}
.quick-link:hover {
  background:var(--accent); color:#fff; border-color:var(--accent);
}
""",
        "comparison": """
/* Comparison category */
.category-comparison .content table {
  width:100%; border-collapse:collapse; margin:1.2em 0;
}
.category-comparison .content table th {
  background:var(--accent); color:#fff; padding:10px 14px;
  text-align:center; font-weight:600; position:sticky; top:0;
}
.category-comparison .content table td {
  padding:10px 14px; border-bottom:1px solid var(--border); text-align:center;
}
.category-comparison .content table tr:nth-child(even) td { background:var(--bg-surface); }
.category-comparison .content table td:first-child {
  text-align:left; font-weight:500; background:color-mix(in srgb, var(--accent) 8%, transparent);
}
.category-comparison .content table td.cmp-pos {
  color:#2e7d32; font-weight:600;
  background:color-mix(in srgb, #4caf50 10%, transparent);
}
.category-comparison .content table td.cmp-neg {
  color:#c62828; font-weight:600;
  background:color-mix(in srgb, #f44336 8%, transparent);
}
.category-comparison .content table td.cmp-mid {
  color:#e68a00;
  background:color-mix(in srgb, #ffa726 8%, transparent);
}
.category-comparison .content h2 ~ p strong:first-child {
  display:inline-block; padding:2px 8px; border-radius:3px;
  background:color-mix(in srgb, var(--accent) 15%, transparent); font-size:0.9em;
}
""",
        "howto": """
/* How-to category */
.category-howto .content h2 {
  counter-increment:step-counter;
}
.category-howto .content h2::before {
  content:counter(step-counter);
  display:inline-flex; align-items:center; justify-content:center;
  width:28px; height:28px; border-radius:50%;
  background:var(--accent); color:#fff; font-size:0.8em; font-weight:700;
  margin-right:10px; flex-shrink:0;
}
.category-howto .content { counter-reset:step-counter; }
.category-howto .content blockquote {
  border-left:3px solid var(--accent); background:color-mix(in srgb, var(--accent) 8%, transparent);
  padding:12px 16px; border-radius:0 6px 6px 0; margin:1em 0;
}
.category-howto .content blockquote strong:first-child {
  display:inline-block; margin-bottom:4px; text-transform:uppercase;
  font-size:0.82em; letter-spacing:0.5px;
}
.category-howto .content h2#quick-guide + ol,
.category-howto .content h2#quick-guide ~ ol:first-of-type {
  background:color-mix(in srgb, var(--accent) 8%, transparent);
  border:1px solid color-mix(in srgb, var(--accent) 20%, transparent);
  border-radius:8px; padding:14px 14px 14px 32px; font-size:0.95em; line-height:1.8;
}
.category-howto .content h2#quick-guide {
  counter-increment:none;
}
.category-howto .content h2#quick-guide::before {
  content:'\\26A1'; background:none; width:auto; height:auto; margin-right:6px;
}
""",
        "landscape": """
/* Landscape category */
.category-landscape .content h3 {
  display:flex; align-items:center; gap:8px;
  padding:8px 0; border-bottom:1px solid var(--border);
}
.category-landscape .content table {
  width:100%; border-collapse:collapse; margin:1em 0; font-size:0.92em;
}
.category-landscape .content table th {
  background:var(--accent); color:#fff; padding:8px 12px; text-align:left;
}
.category-landscape .content table td { padding:8px 12px; border-bottom:1px solid var(--border); }
.category-landscape .content table tr:nth-child(even) td { background:var(--bg-surface); }
.category-landscape .content blockquote {
  border-left:3px solid var(--gold, #d4a73a);
  background:color-mix(in srgb, var(--gold, #d4a73a) 8%, transparent);
  padding:10px 14px; border-radius:0 6px 6px 0;
}
""",
        "factcheck": """
/* Fact-check category */
.category-factcheck .hero {
  background:linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
}
.category-factcheck .content h2:first-of-type {
  font-size:1.4em; text-align:center; padding:16px 0; border:none;
  background:color-mix(in srgb, var(--accent) 8%, transparent);
  border-radius:8px; margin:1em 0;
}
.category-factcheck .content blockquote {
  position:relative; padding-left:20px;
}
.category-factcheck .content h2 ~ h3 {
  padding:6px 10px; border-radius:4px;
  border-left:3px solid var(--accent);
}
.category-factcheck .content strong:only-child {
  display:inline-block; padding:4px 12px; border-radius:4px;
  font-size:1.1em;
}
""",
    }
    # Always emit the per-category palette block when ANY category is set —
    # it contains body.category-X scoped rules so it only re-skins the page
    # for the matching category. The legacy `styles[category]` block adds
    # structural CSS specific to that one type.
    return palettes + styles.get(category, "")


_GENERIC_HEADINGS = {
    "report", "deep research report", "research",
    "executive summary", "summary", "tl;dr",
    "introduction", "overview", "abstract",
    "findings", "key findings", "results",
    "conclusion", "conclusions", "table of contents",
}


def _extract_report_title(markdown_text: str, fallback: str):
    """Pull a real title from the report's first heading rather than reusing
    the raw user query. Returns (title, markdown_with_title_stripped).

    Falls back to the query when no heading is present. Skips generic
    placeholders ("Executive Summary", "Introduction", etc.) and tries the
    next heading. If the chosen title was the report's own top heading, that
    heading is removed from the markdown so it doesn't duplicate the hero h1.
    """
    if not markdown_text:
        return fallback, markdown_text

    # Walk through headings (h1 first, then h2 anywhere) and use the first
    # non-generic one. Track the chosen match so we can strip it from the body.
    candidates = []
    for level, pattern in ((1, r'^# +(.+?)\s*$'), (2, r'^## +(.+?)\s*$')):
        for m in re.finditer(pattern, markdown_text, re.MULTILINE):
            cand = m.group(1).strip().rstrip('#').strip()
            if cand and cand.lower() not in _GENERIC_HEADINGS:
                candidates.append((level, m, cand))

    # Prefer h1 over h2; among same-level, prefer the earliest.
    candidates.sort(key=lambda t: (t[0], t[1].start()))
    if candidates:
        _level, match, title = candidates[0]
        stripped = markdown_text[:match.start()] + markdown_text[match.end():]
        return title, stripped.lstrip()
    return fallback, markdown_text


_ICON_LOGO_RE = re.compile(r'/(icon|logo|favicon)([._/-]|$)', re.IGNORECASE)


def _is_icon_or_logo_url(url: str) -> bool:
    """True if a URL path points at an icon/logo/favicon asset.

    Matches the icon/logo/favicon token only at a path-segment or basename
    boundary, so a real photo whose slug merely CONTAINS the word (e.g.
    /iconic-moment.jpg, /logos-history.png) is no longer dropped, while
    /icon.png, /logo.svg and /favicon.ico still are.
    """
    return bool(_ICON_LOGO_RE.search(url or ""))


def generate_visual_report(
    question: str,
    report_markdown: str,
    sources: Optional[List[Dict]] = None,
    stats: Optional[Dict] = None,
    category: Optional[str] = None,
    session_id: Optional[str] = None,
    hidden_images: Optional[List[str]] = None,
    evidence_registry: Optional[dict] = None,
) -> str:
    sources = sources or []
    stats = stats or {}
    category = category or "academic"
    hidden_images_set = set(hidden_images or [])
    registry_sources = sources_from_registry(
        evidence_registry,
        sources,
        for_visual_report=True,
    )

    # Strip thinking artifacts
    report_markdown = strip_thinking(report_markdown)

    # Use the report's first heading as the title (synthesized by the LLM)
    # rather than the raw user query. Fall back to the query if absent.
    synthesized, report_markdown = _extract_report_title(report_markdown, question)
    title_text = synthesized[:120] + ("..." if len(synthesized) > 120 else "")

    # Promote bold-only lines to ## headings if no markdown headings exist
    if not re.search(r'^#{2,3}\s+', report_markdown, re.MULTILINE):
        report_markdown = re.sub(
            r'^\*\*([^*]+)\*\*\s*$',
            lambda m: f'## {m.group(1).strip()}',
            report_markdown,
            flags=re.MULTILINE,
        )

    summary_md, body_md = split_executive_summary(report_markdown)
    body_md = strip_references_section(body_md if summary_md else report_markdown)
    markdown_for_body = prepare_markdown_for_report_html(body_md)
    report_html = _md_to_html(markdown_for_body)
    if summary_md:
        summary_html = _md_to_html(prepare_markdown_for_report_html(summary_md))
        report_html = _wrap_executive_summary_html(summary_html) + report_html
    report_html = linkify_citation_markers(report_html)

    headings = _extract_headings(markdown_for_body)
    report_html = _apply_heading_ids(report_html, headings)

    # Collect OG images for hero/section figures (disabled — text-only reports).
    hero_image_html = ""
    spare_images: List[str] = []
    og_image_meta = ""
    restore_btn_html = ""
    if REPORT_IMAGES_ENABLED:
        _IMAGE_BLOCKLIST = {
            "cdn.shopify.com/s/files/1/0179/4388/7926/files/icon.png",
        }
        _seen_images = set()
        all_images = []
        for s in sources:
            img = s.get("image", "")
            if (img and img.startswith("https://")
                and img not in _seen_images
                and img not in hidden_images_set
                and not img.endswith((".svg", ".ico", ".gif"))
                and not any(b in img for b in _IMAGE_BLOCKLIST)
                and not _is_icon_or_logo_url(img)):
                _seen_images.add(img)
                all_images.append(img)

        if all_images:
            hero_url = html.escape(all_images[0])
            hero_image_html = (
                f'<div class="hero-image" data-img-url="{hero_url}">'
                f'<img src="{hero_url}" alt="" loading="lazy" '
                f'onerror="this.parentElement.style.display=\'none\'">'
                f'{_IMG_OVERLAY_BTNS}'
                f'</div>'
            )
            og_image_meta = f'<meta property="og:image" content="{html.escape(all_images[0])}">'

        section_pool = all_images[1:]
        report_html, _consumed = _inject_images(report_html, section_pool)
        spare_images = section_pool[_consumed:]

        if session_id and hidden_images_set:
            restore_btn_html = (
                '<button id="btn-restore-images" type="button" '
                f'title="Restore {len(hidden_images_set)} hidden image'
                f'{"" if len(hidden_images_set) == 1 else "s"}">'
                '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" '
                'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
                '<path d="M1 4v6h6"/><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"/>'
                '</svg>'
                f'Show hidden ({len(hidden_images_set)})'
                '</button>'
            )

    # Product quick-links bar
    if category == "product" and headings:
        product_headings = [h for h in headings if h["level"] == 3]
        if product_headings:
            pills = " ".join(
                f'<a href="#{h["slug"]}" class="quick-link">{html.escape(h["text"][:40])}</a>'
                for h in product_headings
            )
            report_html = f'<div class="quick-links-bar">{pills}</div>\n' + report_html

    # Build TOC
    toc_html = build_toc_html(headings, registry_sources)

    # Build stats bar
    stat_items = []
    for key, label in [("Duration", "Duration"), ("Rounds", "Rounds"), ("Queries", "Queries"), ("URLs", "URLs Analyzed"), ("Model", "Model"), ("Search", "Search")]:
        val = stats.get(key)
        if val is not None:
            stat_items.append(
                f'<div class="stat"><span class="stat-value">{html.escape(str(val))}</span> {html.escape(label)}</div>'
            )
    stats_html = "\n  ".join(stat_items)

    # Build sources sidebar + retrieval disclosure (Phase 5c)
    sources_sidebar_html = build_sources_sidebar_html(registry_sources)
    sourcing_disclosure_html = build_sourcing_disclosure_html(registry_sources)
    sources_html = ""
    if not registry_sources and sources:
        items = []
        for i, s in enumerate(sources, 1):
            url = s.get("url", "")
            title = html.escape(s.get("title", "") or url)
            domain = ""
            try:
                domain = urlparse(url).hostname or ""
                if domain.startswith("www."):
                    domain = domain[4:]
            except Exception:
                domain = url
            items.append(
                f'<a href="{html.escape(url)}" target="_blank" rel="noopener noreferrer">'
                f'<span class="snum">{i}.</span>'
                f'<span>{title}</span>'
                f'<span class="sdomain">{html.escape(domain)}</span>'
                f'</a>'
            )
        sources_html = (
            '<div class="sources-panel">\n'
            '<details>\n'
            f'<summary>Sources ({len(sources)})</summary>\n'
            '<div class="sources-list">\n'
            + "\n".join(items)
            + "\n</div>\n</details>\n</div>"
        )
        report_html = report_html + sources_html

    timestamp = datetime.now().strftime("%B %d, %Y at %H:%M")

    # Build description for OG/meta tags (first 160 chars of plain text)
    desc_text = re.sub(r'[#*_\[\]()]', '', report_markdown)[:160].strip()

    chat_cta_html = ""
    if session_id:
        chat_cta_html = (
            '<div class="chat-cta">'
            '<button id="btn-chat-about" class="chat-cta-btn" '
            f'data-research-id="{html.escape(session_id)}">'
            '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" '
            'width="18" height="18">'
            '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>'
            '</svg>'
            '<span>Discuss</span>'
            '</button>'
            '<div class="chat-cta-hint">Opens a new chat with this report as context.</div>'
            '</div>'
        )

    return _TEMPLATE.format(
        title=html.escape(title_text),
        description=html.escape(desc_text),
        og_image_meta=og_image_meta,
        question_html=html.escape(synthesized),
        hero_image_html=hero_image_html,
        stats_html=stats_html,
        sourcing_disclosure_html=sourcing_disclosure_html,
        toc_html=toc_html,
        report_html=report_html,
        sources_sidebar_html=sources_sidebar_html,
        chat_cta_html=chat_cta_html,
        restore_btn_html=restore_btn_html,
        timestamp=timestamp,
        category_css=_category_css(category),
        body_class=f"category-{category}" if category else "",
        session_id_js=json_dumps_str(session_id or ""),
        spare_images_js=_json_for_script(spare_images),
    )


def _json_for_script(value) -> str:
    """JSON-encode a value safe to embed inside a <script> block.

    json.dumps doesn't escape '/', so a string containing the literal
    substring '</script>' would terminate the script element early.
    Escape the closing slash to keep the inline JSON inert as HTML.
    """
    return json.dumps(value).replace("</", "<\\/")


def json_dumps_str(s: str) -> str:
    """JSON-encode a string so it's safe to embed inside a <script> block."""
    return _json_for_script(s)
