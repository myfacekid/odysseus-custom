# src/visual_report.py
"""
Generate a self-contained, styled HTML page from deep research results.

Takes the markdown report, sources, and stats produced by Deep Research
and wraps them in a Blueprint + Modus Operandi Tinted HTML document with:
- Self-hosted Iosevka / Roboto Mono (same origin /static/fonts)
- Light default: Modus Operandi Tinted; dark: Modus Vivendi Tinted via prefers-color-scheme
- Inherits the user's saved app theme and font from localStorage when available
- Blueprint chrome (2px radius, hard shadows, uppercase labels)
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
<meta name="theme-color" content="#0031a9" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#0d0e1c" media="(prefers-color-scheme: dark)">
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='75' font-size='75'>N</text></svg>">
<script>
/* Apply the app's saved theme + font (localStorage) before first paint when available. */
(function() {{
  try {{
    var raw = null;
    try {{ raw = localStorage.getItem('nobody-theme') || localStorage.getItem('oculus-theme'); }} catch (e) {{}}
    if (!raw) return;
    var t = JSON.parse(raw);
    var s = document.documentElement.style;
    var c = (t && t.colors) ? t.colors : t;

    /* Font — same keys as theme.js FONT_MAP / index.html early script */
    var fm = {{
      mono: "'Iosevka', monospace",
      fira: "'Fira Code', monospace",
      jetbrains: "'JetBrains Mono', monospace",
      'roboto-mono': "'Roboto Mono', monospace",
      'ibm-plex': "'IBM Plex Sans', system-ui, sans-serif",
      'source-sans': "'Source Sans 3', system-ui, sans-serif",
      atkinson: "'Atkinson Hyperlegible', system-ui, sans-serif",
      manrope: "'Manrope', system-ui, sans-serif",
      'space-grotesk': "'Space Grotesk', system-ui, sans-serif",
      outfit: "'Outfit', system-ui, sans-serif",
      sans: "system-ui, -apple-system, 'Segoe UI', sans-serif",
      literata: "'Literata', Georgia, serif",
      'source-serif': "'Source Serif 4', Georgia, serif",
      lora: "'Lora', Georgia, serif",
      newsreader: "'Newsreader', Georgia, serif",
      fraunces: "'Fraunces', Georgia, serif",
      serif: "'Literata', Georgia, serif"
    }};
    var monoKeys = {{ mono:1, fira:1, jetbrains:1, 'roboto-mono':1 }};
    var fontKey = (t && t.font) || '';
    var family = fm[fontKey] || null;
    if (!family && fontKey) {{
      /* Custom font name from static/fonts/custom — inject faces async below */
      family = "'" + String(fontKey).replace(/'/g, '') + "', sans-serif";
    }}
    if (family) {{
      s.setProperty('--font-ui', family);
      s.setProperty('--font-body', family);
      s.setProperty('--font-display', family);
      s.setProperty('--font-family', family);
      if (monoKeys[fontKey]) s.setProperty('--font-mono', family);
      document.documentElement.setAttribute('data-user-font', fontKey);
    }}
    if (t && t.density && t.density !== 'comfortable') {{
      document.documentElement.classList.add('density-' + t.density);
    }}

    /* Custom font files (if selected font isn't a built-in key) */
    if (fontKey && !fm[fontKey]) {{
      fetch('/api/fonts/custom', {{ credentials: 'same-origin' }})
        .then(function(r) {{ return r.json(); }})
        .then(function(data) {{
          var fonts = (data && data.fonts) || {{}};
          var variants = fonts[fontKey];
          if (!variants || !variants.length) return;
          var style = document.createElement('style');
          style.setAttribute('data-custom-font', fontKey);
          var css = '';
          var fmtMap = {{ woff2: 'woff2', woff: 'woff', ttf: 'truetype', otf: 'opentype' }};
          for (var i = 0; i < variants.length; i++) {{
            var v = variants[i];
            var fmt = fmtMap[v.format] || v.format || 'woff2';
            css += "@font-face {{ font-family: '" + fontKey.replace(/'/g, '') + "'; src: url('" + v.url + "') format('" + fmt + "'); font-display: swap; }}\\n";
          }}
          style.textContent = css;
          document.head.appendChild(style);
        }})
        .catch(function() {{}});
    }}

    if (!c || !c.bg) return;
    var adv = c.advanced || {{}};
    var accent = adv.accentPrimary || c.red || '#0031a9';
    var accentHover = adv.sendBtnHover || accent;
    var warm = adv.accentWarm || '#6d5000';
    var err = adv.accentError || '#a60000';
    var panel = c.panel || c.bg;
    s.setProperty('--bg', c.bg);
    s.setProperty('--bg-surface', panel);
    s.setProperty('--bg-surface-alt', panel);
    s.setProperty('--border', c.border || '#9f9690');
    s.setProperty('--border-strong', c.border || '#9f9690');
    s.setProperty('--text', c.fg || '#000000');
    s.setProperty('--text-dim', '#595959');
    s.setProperty('--text-muted', '#595959');
    s.setProperty('--accent', accent);
    s.setProperty('--accent-light', accentHover);
    s.setProperty('--accent-bg', 'color-mix(in srgb, ' + accent + ' 8%, ' + panel + ')');
    s.setProperty('--gold', warm);
    s.setProperty('--gold-bg', 'color-mix(in srgb, ' + warm + ' 9%, transparent)');
    s.setProperty('--error', err);
    s.setProperty('--aurora-a', 'color-mix(in srgb, ' + accent + ' 10%, transparent)');
    s.setProperty('--aurora-b', 'color-mix(in srgb, ' + warm + ' 8%, transparent)');
    s.setProperty('--shadow-sm', '2px 2px 0 color-mix(in srgb, ' + (c.fg || '#000') + ' 18%, transparent)');
    s.setProperty('--shadow-md', '2px 2px 0 color-mix(in srgb, ' + (c.fg || '#000') + ' 18%, transparent)');
    if (adv.codeBg) s.setProperty('--bg-surface-alt', adv.codeBg);
    document.documentElement.setAttribute('data-user-theme', (t && t.name) || 'custom');
    var mtc = document.querySelector('meta[name="theme-color"]');
    if (mtc && c.bg) mtc.setAttribute('content', c.bg);
    /* Dim/muted text: blend fg toward bg for readability on any theme */
    var bgL = 50;
    try {{
      var hex = (c.bg || '').replace('#','');
      if (hex.length === 3) hex = hex[0]+hex[0]+hex[1]+hex[1]+hex[2]+hex[2];
      if (hex.length === 6) {{
        var r = parseInt(hex.slice(0,2),16)/255, g = parseInt(hex.slice(2,4),16)/255, b = parseInt(hex.slice(4,6),16)/255;
        bgL = (Math.max(r,g,b)+Math.min(r,g,b))/2 * 100;
      }}
    }} catch (e2) {{}}
    s.setProperty('--text-dim', bgL < 50 ? '#a8a8a8' : '#595959');
    s.setProperty('--text-muted', bgL < 50 ? '#a8a8a8' : '#595959');
    if (bgL < 50) s.setProperty('--success', '#44bc44');
  }} catch (err) {{}}
}})();
</script>
<style>
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

/* Self-hosted theme fonts (same set as static/style.css) */
@font-face {{ font-family: 'Iosevka'; font-weight: 400; font-style: normal; font-display: swap; src: url('/static/fonts/Iosevka-Regular.woff2') format('woff2'); }}
@font-face {{ font-family: 'Iosevka'; font-weight: 500; font-style: normal; font-display: swap; src: url('/static/fonts/Iosevka-Medium.woff2') format('woff2'); }}
@font-face {{ font-family: 'Iosevka'; font-weight: 600; font-style: normal; font-display: swap; src: url('/static/fonts/Iosevka-SemiBold.woff2') format('woff2'); }}
@font-face {{ font-family: 'Fira Code'; font-weight: 300; font-style: normal; font-display: swap; src: url('/static/fonts/FiraCode-Light.woff2') format('woff2'); }}
@font-face {{ font-family: 'Fira Code'; font-weight: 400; font-style: normal; font-display: swap; src: url('/static/fonts/FiraCode-Regular.woff2') format('woff2'); }}
@font-face {{ font-family: 'Fira Code'; font-weight: 600; font-style: normal; font-display: swap; src: url('/static/fonts/FiraCode-SemiBold.woff2') format('woff2'); }}
@font-face {{ font-family: 'JetBrains Mono'; font-weight: 400; font-style: normal; font-display: swap; src: url('/static/fonts/JetBrainsMono-Regular.woff2') format('woff2'); }}
@font-face {{ font-family: 'JetBrains Mono'; font-weight: 500; font-style: normal; font-display: swap; src: url('/static/fonts/JetBrainsMono-Medium.woff2') format('woff2'); }}
@font-face {{ font-family: 'JetBrains Mono'; font-weight: 600; font-style: normal; font-display: swap; src: url('/static/fonts/JetBrainsMono-SemiBold.woff2') format('woff2'); }}
@font-face {{ font-family: 'Roboto Mono'; font-weight: 400; font-style: normal; font-display: swap; src: url('/static/fonts/RobotoMono-Regular.woff2') format('woff2'); }}
@font-face {{ font-family: 'Roboto Mono'; font-weight: 500; font-style: normal; font-display: swap; src: url('/static/fonts/RobotoMono-Medium.woff2') format('woff2'); }}
@font-face {{ font-family: 'Roboto Mono'; font-weight: 600; font-style: normal; font-display: swap; src: url('/static/fonts/RobotoMono-SemiBold.woff2') format('woff2'); }}
@font-face {{ font-family: 'IBM Plex Sans'; font-weight: 400; font-style: normal; font-display: swap; src: url('/static/fonts/IBMPlexSans-Regular.woff2') format('woff2'); }}
@font-face {{ font-family: 'IBM Plex Sans'; font-weight: 500; font-style: normal; font-display: swap; src: url('/static/fonts/IBMPlexSans-Medium.woff2') format('woff2'); }}
@font-face {{ font-family: 'IBM Plex Sans'; font-weight: 600; font-style: normal; font-display: swap; src: url('/static/fonts/IBMPlexSans-SemiBold.woff2') format('woff2'); }}
@font-face {{ font-family: 'Source Sans 3'; font-weight: 400; font-style: normal; font-display: swap; src: url('/static/fonts/SourceSans3-Regular.woff2') format('woff2'); }}
@font-face {{ font-family: 'Source Sans 3'; font-weight: 500; font-style: normal; font-display: swap; src: url('/static/fonts/SourceSans3-Medium.woff2') format('woff2'); }}
@font-face {{ font-family: 'Source Sans 3'; font-weight: 600; font-style: normal; font-display: swap; src: url('/static/fonts/SourceSans3-SemiBold.woff2') format('woff2'); }}
@font-face {{ font-family: 'Atkinson Hyperlegible'; font-weight: 400; font-style: normal; font-display: swap; src: url('/static/fonts/AtkinsonHyperlegible-Regular.woff2') format('woff2'); }}
@font-face {{ font-family: 'Atkinson Hyperlegible'; font-weight: 500; font-style: normal; font-display: swap; src: url('/static/fonts/AtkinsonHyperlegible-Regular.woff2') format('woff2'); }}
@font-face {{ font-family: 'Atkinson Hyperlegible'; font-weight: 600; font-style: normal; font-display: swap; src: url('/static/fonts/AtkinsonHyperlegible-Bold.woff2') format('woff2'); }}
@font-face {{ font-family: 'Atkinson Hyperlegible'; font-weight: 700; font-style: normal; font-display: swap; src: url('/static/fonts/AtkinsonHyperlegible-Bold.woff2') format('woff2'); }}
@font-face {{ font-family: 'Manrope'; font-weight: 400; font-style: normal; font-display: swap; src: url('/static/fonts/Manrope-Regular.woff2') format('woff2'); }}
@font-face {{ font-family: 'Manrope'; font-weight: 500; font-style: normal; font-display: swap; src: url('/static/fonts/Manrope-Medium.woff2') format('woff2'); }}
@font-face {{ font-family: 'Manrope'; font-weight: 600; font-style: normal; font-display: swap; src: url('/static/fonts/Manrope-SemiBold.woff2') format('woff2'); }}
@font-face {{ font-family: 'Space Grotesk'; font-weight: 400; font-style: normal; font-display: swap; src: url('/static/fonts/SpaceGrotesk-Regular.woff2') format('woff2'); }}
@font-face {{ font-family: 'Space Grotesk'; font-weight: 500; font-style: normal; font-display: swap; src: url('/static/fonts/SpaceGrotesk-Medium.woff2') format('woff2'); }}
@font-face {{ font-family: 'Space Grotesk'; font-weight: 600; font-style: normal; font-display: swap; src: url('/static/fonts/SpaceGrotesk-SemiBold.woff2') format('woff2'); }}
@font-face {{ font-family: 'Outfit'; font-weight: 400; font-style: normal; font-display: swap; src: url('/static/fonts/Outfit-Regular.woff2') format('woff2'); }}
@font-face {{ font-family: 'Outfit'; font-weight: 500; font-style: normal; font-display: swap; src: url('/static/fonts/Outfit-Medium.woff2') format('woff2'); }}
@font-face {{ font-family: 'Outfit'; font-weight: 600; font-style: normal; font-display: swap; src: url('/static/fonts/Outfit-SemiBold.woff2') format('woff2'); }}
@font-face {{ font-family: 'Literata'; font-weight: 400; font-style: normal; font-display: swap; src: url('/static/fonts/Literata-Regular.woff2') format('woff2'); }}
@font-face {{ font-family: 'Literata'; font-weight: 500; font-style: normal; font-display: swap; src: url('/static/fonts/Literata-Medium.woff2') format('woff2'); }}
@font-face {{ font-family: 'Literata'; font-weight: 600; font-style: normal; font-display: swap; src: url('/static/fonts/Literata-SemiBold.woff2') format('woff2'); }}
@font-face {{ font-family: 'Source Serif 4'; font-weight: 400; font-style: normal; font-display: swap; src: url('/static/fonts/SourceSerif4-Regular.woff2') format('woff2'); }}
@font-face {{ font-family: 'Source Serif 4'; font-weight: 500; font-style: normal; font-display: swap; src: url('/static/fonts/SourceSerif4-Medium.woff2') format('woff2'); }}
@font-face {{ font-family: 'Source Serif 4'; font-weight: 600; font-style: normal; font-display: swap; src: url('/static/fonts/SourceSerif4-SemiBold.woff2') format('woff2'); }}
@font-face {{ font-family: 'Lora'; font-weight: 400; font-style: normal; font-display: swap; src: url('/static/fonts/Lora-Regular.woff2') format('woff2'); }}
@font-face {{ font-family: 'Lora'; font-weight: 500; font-style: normal; font-display: swap; src: url('/static/fonts/Lora-Medium.woff2') format('woff2'); }}
@font-face {{ font-family: 'Lora'; font-weight: 600; font-style: normal; font-display: swap; src: url('/static/fonts/Lora-SemiBold.woff2') format('woff2'); }}
@font-face {{ font-family: 'Newsreader'; font-weight: 400; font-style: normal; font-display: swap; src: url('/static/fonts/Newsreader-Regular.woff2') format('woff2'); }}
@font-face {{ font-family: 'Newsreader'; font-weight: 500; font-style: normal; font-display: swap; src: url('/static/fonts/Newsreader-Medium.woff2') format('woff2'); }}
@font-face {{ font-family: 'Newsreader'; font-weight: 600; font-style: normal; font-display: swap; src: url('/static/fonts/Newsreader-SemiBold.woff2') format('woff2'); }}
@font-face {{ font-family: 'Fraunces'; font-weight: 400; font-style: normal; font-display: swap; src: url('/static/fonts/Fraunces-Regular.woff2') format('woff2'); }}
@font-face {{ font-family: 'Fraunces'; font-weight: 500; font-style: normal; font-display: swap; src: url('/static/fonts/Fraunces-Medium.woff2') format('woff2'); }}
@font-face {{ font-family: 'Fraunces'; font-weight: 600; font-style: normal; font-display: swap; src: url('/static/fonts/Fraunces-SemiBold.woff2') format('woff2'); }}

:root {{
  /* Blueprint + Modus Operandi Tinted */
  --font-ui: 'Iosevka', 'Fira Code', monospace;
  --font-display: var(--font-ui);
  --font-body: var(--font-ui);
  --font-mono: 'Roboto Mono', ui-monospace, monospace;
  --font-family: var(--font-ui);
  --tracking-label: 0.06em;
  --bg: #fbf7f0;
  --bg-surface: #efe9dd;
  --bg-surface-alt: #efe9dd;
  --border: #9f9690;
  --border-strong: #9f9690;
  --text: #000000;
  --text-dim: #595959;
  --text-muted: #595959;
  --accent: #0031a9;
  --accent-light: #3546c2;
  --accent-bg: color-mix(in srgb, #0031a9 8%, var(--bg-surface));
  --gold: #6d5000;
  --gold-bg: color-mix(in srgb, #6d5000 9%, transparent);
  --success: #006300;
  --error: #a60000;
  --aurora-a: color-mix(in srgb, var(--accent) 10%, transparent);
  --aurora-b: color-mix(in srgb, var(--gold) 8%, transparent);
  --aurora-c: color-mix(in srgb, #00598b 7%, transparent);
  --radius: 2px;
  --radius-none: 0;
  --shadow-sm: 2px 2px 0 color-mix(in srgb, var(--text) 18%, transparent);
  --shadow-md: 2px 2px 0 color-mix(in srgb, var(--text) 18%, transparent);
  --max-w: 760px;
}}

@media (prefers-color-scheme: dark) {{
  :root {{
    /* Modus Vivendi Tinted */
    --bg: #0d0e1c; --bg-surface: #1d2235; --bg-surface-alt: #1d2235;
    --border: #61647a; --border-strong: #61647a;
    --text: #ffffff; --text-dim: #a8a8a8; --text-muted: #a8a8a8;
    --accent: #2fafff; --accent-light: #79a8ff;
    --accent-bg: color-mix(in srgb, #2fafff 10%, var(--bg-surface));
    --gold: #d0bc00; --gold-bg: color-mix(in srgb, #d0bc00 9%, transparent);
    --success: #44bc44; --error: #ff5f59;
    --aurora-a: color-mix(in srgb, var(--accent) 12%, transparent);
    --aurora-b: color-mix(in srgb, var(--gold) 9%, transparent);
    --aurora-c: color-mix(in srgb, #00d3d0 8%, transparent);
    --shadow-sm: 2px 2px 0 color-mix(in srgb, var(--text) 18%, transparent);
    --shadow-md: 2px 2px 0 color-mix(in srgb, var(--text) 18%, transparent);
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
  line-height: 1.65;
  font-size: 15px;
  -webkit-font-smoothing: antialiased;
  text-rendering: optimizeLegibility;
  position: relative;
  min-height: 100vh;
}}

/* ── Dots backdrop (Modus Operandi Tinted default pattern) ── */
body::before {{
  content: '';
  position: fixed;
  inset: 0;
  z-index: -2;
  pointer-events: none;
  background-image: radial-gradient(
    color-mix(in srgb, var(--text) 5%, transparent) 1px,
    transparent 1px
  );
  background-size: 20px 20px;
}}
body::after {{
  content: none;
}}

/* ── Toolbar (top-right) ──────────────────────────── */
.toolbar {{
  position: fixed;
  top: 1rem;
  right: 1rem;
  z-index: 100;
  display: flex;
  gap: 0.4rem;
  opacity: 0.85;
  transition: opacity 0.2s;
}}
.toolbar:hover {{ opacity: 1; }}
.toolbar button {{
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 4px 10px;
  border: 1px solid var(--border-strong);
  border-radius: var(--radius);
  background: var(--bg-surface);
  color: var(--text);
  font-family: var(--font-ui);
  font-size: 0.72rem;
  font-weight: 500;
  letter-spacing: var(--tracking-label);
  text-transform: uppercase;
  cursor: pointer;
  box-shadow: var(--shadow-sm);
  transition: background 0.12s;
  position: relative;
}}
.toolbar button:hover {{ background: color-mix(in srgb, var(--accent) 8%, var(--bg-surface)); }}
.toolbar button svg {{ width: 14px; height: 14px; flex-shrink: 0; }}
.toolbar .toast {{
  position: absolute;
  top: calc(100% + 6px);
  right: 0;
  background: var(--text);
  color: var(--bg);
  padding: 4px 10px;
  border-radius: var(--radius);
  font-size: 0.68rem;
  letter-spacing: var(--tracking-label);
  text-transform: uppercase;
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
  border-radius: var(--radius);
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
  font-family: var(--font-ui);
  font-size: 0.72rem;
  letter-spacing: var(--tracking-label);
  text-transform: uppercase;
  text-align: left;
  cursor: pointer;
  box-shadow: none;
}}
.dropdown-menu button:hover {{ background: color-mix(in srgb, var(--accent) 8%, transparent); }}

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
  content: none;
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
  letter-spacing: var(--tracking-label);
  font-size: 0.68rem;
  font-weight: 600;
  color: var(--accent);
  opacity: 0.85;
  margin-bottom: 1.4rem;
  font-family: var(--font-mono);
}}
.hero h1 {{
  position: relative;
  font-family: var(--font-display);
  font-size: clamp(1.6rem, 3.5vw, 2.25rem);
  font-weight: 600;
  line-height: 1.25;
  max-width: 720px;
  margin: 0 auto;
  letter-spacing: -0.01em;
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
  border-radius: var(--radius);
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
  border-radius: var(--radius);
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
  font-size: 0.78rem;
  font-family: var(--font-mono);
  letter-spacing: var(--tracking-label);
  text-transform: uppercase;
  color: var(--text-dim);
}}
.stat {{ display: flex; align-items: center; gap: 0.35rem; }}
.stat-value {{ font-weight: 600; color: var(--text); }}

.verify-badge {{
  max-width: 820px;
  margin: 0.9rem auto 0;
  padding: 0.7rem 1rem;
  border-radius: var(--radius);
  border: 1px solid var(--border-strong);
  background: var(--bg-surface-alt);
  font-size: 0.82rem;
  box-shadow: var(--shadow-sm);
}}
.verify-head {{ display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap; }}
.verify-dot {{
  width: 9px; height: 9px; border-radius: var(--radius-none);
  background: var(--text-dim); flex: none;
}}
.verify-label {{ font-weight: 700; color: var(--text); letter-spacing: var(--tracking-label); text-transform: uppercase; font-size: 0.72rem; }}
.verify-meta {{ color: var(--text-dim); font-size: 0.76rem; }}
.verify-counts {{ display: flex; gap: 0.4rem; flex-wrap: wrap; margin-top: 0.45rem; }}
.verify-count {{
  padding: 0.12rem 0.5rem; border-radius: var(--radius-none);
  font-size: 0.68rem; font-weight: 600; font-family: var(--font-mono);
  border: 1px solid var(--border-strong); color: var(--text-dim);
}}
.verify-ok {{ border-color: color-mix(in srgb, var(--success) 40%, var(--border)); color: color-mix(in srgb, var(--success) 75%, var(--text)); }}
.verify-partial {{ border-color: color-mix(in srgb, var(--gold) 45%, var(--border)); color: color-mix(in srgb, var(--gold) 80%, var(--text)); }}
.verify-bad {{ border-color: color-mix(in srgb, var(--error) 45%, var(--border)); color: color-mix(in srgb, var(--error) 85%, var(--text)); }}
.verify-adequate .verify-dot {{ background: var(--success); }}
.verify-abstract .verify-dot {{ background: var(--gold); }}
.verify-thin .verify-dot {{ background: var(--error); }}
.verify-details {{ margin-top: 0.55rem; }}
.verify-details summary {{
  cursor: pointer; font-weight: 600; color: var(--accent);
  font-size: 0.72rem; letter-spacing: var(--tracking-label); text-transform: uppercase;
}}
.verify-list {{ margin: 0.5rem 0 0; padding-left: 0; list-style: none; }}
.verify-list li {{
  padding: 0.4rem 0; border-top: 1px solid var(--border);
  line-height: 1.4;
}}
.verify-tag {{
  display: inline-block; padding: 0.05rem 0.4rem; border-radius: var(--radius-none);
  font-size: 0.68rem; font-weight: 700; font-family: var(--font-mono);
  border: 1px solid currentColor;
  margin-right: 0.3rem;
}}
.verify-cite {{ color: var(--accent); font-weight: 600; margin-right: 0.15rem; }}
.verify-claim {{ color: var(--text); }}
.verify-reason {{ color: var(--text-dim); font-style: italic; }}

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
  border-radius: var(--radius-none);
  font-size: 0.68rem;
  font-weight: 600;
  font-family: var(--font-mono);
  letter-spacing: var(--tracking-label);
  text-transform: uppercase;
  border: 1px solid var(--border-strong);
  background: var(--bg-surface-alt);
  color: var(--text-dim);
}}
.sourcing-chip-adequate {{
  border-color: color-mix(in srgb, var(--success) 35%, var(--border));
  color: color-mix(in srgb, var(--success) 75%, var(--text));
}}
.sourcing-chip-abstract {{
  border-color: color-mix(in srgb, var(--gold) 45%, var(--border));
  color: color-mix(in srgb, var(--gold) 80%, var(--text));
}}
.sourcing-chip-thin {{
  border-color: color-mix(in srgb, var(--error) 35%, var(--border));
  color: color-mix(in srgb, var(--error) 80%, var(--text));
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
.toc-sidebar nav > a,
.toc-group > summary {{
  position: relative;
  display: block;
  color: var(--text-dim);
  text-decoration: none;
  padding: 0.42rem 0.7rem 0.42rem 1.35rem;
  margin: 1px 0;
  border-radius: var(--radius);
  line-height: 1.4;
  letter-spacing: -0.005em;
  transition: color 0.18s ease, background 0.18s ease;
}}
.toc-sidebar nav a {{
  position: relative;
  display: block;
  color: var(--text-dim);
  text-decoration: none;
  padding: 0.42rem 0.7rem 0.42rem 1.35rem;
  margin: 1px 0;
  border-radius: var(--radius);
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
  border-radius: var(--radius-none);
  transition: height 0.18s ease, opacity 0.18s ease;
  opacity: 0;
}}
.toc-sidebar nav a:hover {{
  color: var(--text);
  background: var(--accent-bg);
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
  padding-left: 1.35rem;
  font-size: 0.72rem;
  color: var(--text-muted);
}}
.toc-sidebar nav a.depth-3:hover {{ padding-left: 1.35rem; }}

.toc-group {{
  margin: 2px 0;
  border-radius: var(--radius);
}}
.toc-group > summary {{
  cursor: pointer;
  list-style: none;
  color: var(--text-dim);
  font-size: 0.78rem;
  line-height: 1.4;
}}
.toc-group > summary::-webkit-details-marker {{ display: none; }}
/* Arrow sits in the left gutter so title text aligns with flat TOC links */
.toc-group > summary::before {{
  content: '\\25B6';
  position: absolute;
  left: 0.3rem;
  top: 50%;
  transform: translateY(-50%);
  font-size: 0.55em;
  color: var(--text-muted);
  transition: transform 0.18s ease;
  line-height: 1;
}}
.toc-group[open] > summary::before {{
  transform: translateY(-50%) rotate(90deg);
}}
.toc-group > summary:hover {{
  color: var(--text);
  background: var(--accent-bg);
}}
.toc-group-title {{
  color: inherit;
  text-decoration: none;
  display: block;
  padding: 0 !important;
  margin: 0 !important;
  background: transparent !important;
}}
.toc-group-title:hover {{ color: var(--accent); }}
.toc-group-title::before {{ display: none !important; content: none !important; }}
.toc-group-children {{
  padding: 0.1rem 0 0.35rem 0.55rem;
  border-left: 1px solid var(--border);
  margin: 0 0 0.35rem 1.35rem;
}}
.toc-group-children a {{
  padding-left: 0.55rem !important;
}}
.toc-sources-group > summary {{
  font-weight: 600;
  color: var(--text);
}}

/* ── Content ───────────────────────────────────────── */
.content {{ max-width: var(--max-w); padding: 3rem 2.5rem 4rem; }}

.content h2 {{
  font-family: var(--font-display);
  font-size: clamp(1.25rem, 2vw, 1.5rem);
  font-weight: 600;
  margin: 2.5rem 0 0.85rem;
  padding-bottom: 0.45rem;
  border-bottom: 1px solid transparent;
  border-image: linear-gradient(90deg, var(--accent) 0%, transparent 65%) 1;
  letter-spacing: -0.01em;
  line-height: 1.3;
  color: var(--text);
}}
.content h2:first-child {{ margin-top: 0; }}
.content h3 {{
  font-family: var(--font-display);
  font-size: 1.05rem;
  font-weight: 600;
  margin: 1.8rem 0 0.5rem;
  letter-spacing: -0.005em;
  color: var(--text);
}}
.content h4 {{
  font-family: var(--font-mono);
  font-size: 0.72rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: var(--tracking-label);
  color: var(--text-dim);
  margin: 1.6rem 0 0.5rem;
}}
.content p {{ margin-bottom: 1.1rem; }}

/* Lead accent on first paragraph — Blueprint mono, no editorial drop-cap */
.content > p:first-of-type::first-letter,
.content > h2:first-child + p::first-letter {{
  font-family: inherit;
  font-weight: inherit;
  font-size: 1em;
  float: none;
  margin: 0;
  color: inherit;
}}

.content a {{
  color: var(--accent);
  text-decoration: underline;
  text-decoration-color: color-mix(in srgb, var(--accent) 35%, transparent);
  text-decoration-thickness: 1px;
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
  border-left: 2px solid var(--gold);
  background: var(--gold-bg);
  padding: 0.9rem 1.2rem;
  margin: 1.5rem 0;
  border-radius: 0 var(--radius) var(--radius) 0;
  color: var(--text);
  font-family: var(--font-body);
  font-style: normal;
  font-size: 0.95rem;
  line-height: 1.55;
}}
.content blockquote::before {{
  content: none;
}}
.content hr {{ border: none; height: 1px; background: linear-gradient(90deg, transparent, var(--border-strong), transparent); margin: 2rem 0; }}
.content code {{ font-family: var(--font-mono); font-size: 0.86em; background: var(--bg-surface-alt); padding: 0.15em 0.4em; border-radius: var(--radius); border: 1px solid var(--border); }}
.content pre {{ background: var(--bg-surface-alt); border: 1px solid var(--border); border-radius: var(--radius); padding: 1.25rem 1.5rem; overflow-x: auto; margin: 1.25rem 0; font-size: 0.86rem; line-height: 1.6; box-shadow: var(--shadow-sm); }}
.content pre code {{ background: none; padding: 0; border: none; }}
.content table {{ width: 100%; border-collapse: collapse; margin: 1.25rem 0; font-size: 0.9rem; border: 1px solid var(--border); border-radius: var(--radius); overflow: hidden; box-shadow: var(--shadow-sm); }}
.content th {{ text-align: left; padding: 0.7rem 1rem; background: var(--accent-bg); font-weight: 600; font-family: var(--font-mono); font-size: 0.72rem; letter-spacing: var(--tracking-label); text-transform: uppercase; border-bottom: 2px solid var(--border-strong); }}
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
  position: relative;
  font-family: var(--font-mono);
  font-size: 0.78rem;
  font-weight: 600;
  letter-spacing: var(--tracking-label);
  text-transform: uppercase;
  padding: 0.85rem 1.1rem 0.85rem 1.85rem;
  list-style: none;
  user-select: none;
}}
.exec-summary-panel > summary::-webkit-details-marker {{ display: none; }}
.exec-summary-panel > summary::before {{
  content: '\\25B6';
  position: absolute;
  left: 1.1rem;
  top: 50%;
  transform: translateY(-50%);
  font-size: 0.65em;
  color: var(--text-muted);
  transition: transform 0.2s;
  line-height: 1;
}}
.exec-summary-panel[open] > summary::before {{
  transform: translateY(-50%) rotate(90deg);
}}
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
  font-family: var(--font-mono);
  letter-spacing: var(--tracking-label);
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
  font-size: 0.78rem;
  font-weight: 700;
  font-family: var(--font-mono);
  letter-spacing: var(--tracking-label);
  text-transform: uppercase;
  margin: 0 0 0.65rem;
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
  border-radius: var(--radius-none);
  padding: 0.18rem 0.55rem;
  font-size: 0.68rem;
  font-family: var(--font-mono);
  letter-spacing: var(--tracking-label);
  text-transform: uppercase;
  cursor: pointer;
}}
.source-filter:hover {{ background: color-mix(in srgb, var(--accent) 8%, transparent); color: var(--text); }}
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
  border-radius: var(--radius);
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
  font-family: var(--font-mono);
  letter-spacing: var(--tracking-label);
  text-transform: uppercase;
  padding: 0.1rem 0.35rem;
  border-radius: var(--radius-none);
  border: 1px solid var(--border-strong);
  color: var(--text-dim);
}}
.tier-badge {{
  font-size: 0.58rem;
  font-weight: 700;
  font-family: var(--font-mono);
  letter-spacing: var(--tracking-label);
  text-transform: uppercase;
  padding: 0.12rem 0.38rem;
  border-radius: var(--radius-none);
  border: 1px solid var(--border-strong);
  white-space: nowrap;
}}
.tier-adequate {{
  border-color: color-mix(in srgb, var(--success) 35%, var(--border));
  color: color-mix(in srgb, var(--success) 75%, var(--text));
}}
.tier-abstract {{
  border-color: color-mix(in srgb, var(--gold) 45%, var(--border));
  color: color-mix(in srgb, var(--gold) 80%, var(--text));
}}
.tier-thin, .tier-unknown {{
  border-color: color-mix(in srgb, var(--error) 35%, var(--border));
  color: color-mix(in srgb, var(--error) 75%, var(--text));
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
  font-family: var(--font-mono);
  text-transform: uppercase;
  letter-spacing: var(--tracking-label);
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
  font-family: var(--font-mono);
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
  border: 1px solid var(--border); border-radius: var(--radius);
  background: var(--bg-surface);
  box-shadow: var(--shadow-sm);
}}
.chat-cta-btn {{
  display: inline-flex; align-items: center; gap: 8px;
  padding: 6px 14px; font-size: 0.72rem; font-weight: 600;
  letter-spacing: var(--tracking-label); text-transform: uppercase;
  background: var(--accent); color: #fff;
  border: none; border-radius: var(--radius); cursor: pointer;
  font-family: var(--font-ui);
  box-shadow: var(--shadow-sm);
  transition: background 0.12s, transform 0.05s;
}}
.chat-cta-btn:hover:not(:disabled) {{ background: var(--accent-light); }}
.chat-cta-btn:active:not(:disabled) {{ transform: translateY(1px); }}
.chat-cta-btn:disabled {{ opacity: 0.6; cursor: progress; }}
.chat-cta-hint {{
  margin-top: 8px; font-size: 0.72rem; color: var(--text-muted);
  font-family: var(--font-mono); letter-spacing: var(--tracking-label); text-transform: uppercase;
}}

/* ── Footer ────────────────────────────────────────── */
.report-footer {{
  text-align: center; padding: 2rem; font-size: 0.68rem;
  font-family: var(--font-mono); letter-spacing: var(--tracking-label); text-transform: uppercase;
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
      <button id="btn-save-zotero">Save to Zotero…</button>
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

{verification_badge_html}

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
      import('/static/js/research/zoteroSaveSheet.js').then(function(mod) {{
        return mod.openZoteroSaveSheet({{ sessionId: __sessionId }});
      }}).then(function(result) {{
        if (result && result.ok) {{
          btnZotero.textContent = 'Saved ' + (result.created || 0);
          setTimeout(function() {{ btnZotero.textContent = orig; }}, 2500);
        }}
      }}).catch(function(err) {{
        btnZotero.textContent = 'Failed';
        btnZotero.title = (err && err.message) || 'Save failed';
        setTimeout(function() {{
          btnZotero.textContent = orig;
          btnZotero.title = '';
        }}, 2500);
      }}).finally(function() {{
        btnZotero.disabled = false;
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
        window.opener.postMessage({{ type: 'nobody-open-knowledge', nodeId: nodeId }}, window.location.origin);
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
        // original Nobody tab, navigate it and close this report tab so the
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
/* ── Category palettes (Modus semantic accents) ───────
   Override the accent + aurora vars per category so each report
   type has a distinct visual identity within the Modus palette.
   Skipped when the report inherits the user's saved app theme. */
html:not([data-user-theme]) body.category-academic {
  --accent: #0031a9;
  --accent-light: #3546c2;
  --accent-bg: color-mix(in srgb, #0031a9 8%, var(--bg-surface));
  --aurora-a: color-mix(in srgb, #0031a9 10%, transparent);
  --aurora-b: color-mix(in srgb, #193668 6%, transparent);
  --aurora-c: color-mix(in srgb, #00598b 6%, transparent);
}
html:not([data-user-theme]) body.category-product {
  --accent: #00598b;
  --accent-light: #007ea8;
  --accent-bg: color-mix(in srgb, #00598b 8%, var(--bg-surface));
  --aurora-a: color-mix(in srgb, #00598b 10%, transparent);
  --aurora-b: color-mix(in srgb, #6d5000 6%, transparent);
  --aurora-c: color-mix(in srgb, #0031a9 6%, transparent);
}
html:not([data-user-theme]) body.category-comparison {
  --accent: #721045;
  --accent-light: #8f2a5e;
  --accent-bg: color-mix(in srgb, #721045 8%, var(--bg-surface));
  --aurora-a: color-mix(in srgb, #721045 10%, transparent);
  --aurora-b: color-mix(in srgb, #193668 5%, transparent);
  --aurora-c: color-mix(in srgb, #0031a9 7%, transparent);
}
html:not([data-user-theme]) body.category-howto {
  --accent: #006300;
  --accent-light: #1a7a1a;
  --accent-bg: color-mix(in srgb, #006300 8%, var(--bg-surface));
  --aurora-a: color-mix(in srgb, #006300 10%, transparent);
  --aurora-b: color-mix(in srgb, #6d5000 7%, transparent);
  --aurora-c: color-mix(in srgb, #00598b 5%, transparent);
}
html:not([data-user-theme]) body.category-landscape {
  --accent: #6d5000;
  --accent-light: #8a6a10;
  --accent-bg: color-mix(in srgb, #6d5000 9%, var(--bg-surface));
  --aurora-a: color-mix(in srgb, #6d5000 12%, transparent);
  --aurora-b: color-mix(in srgb, #8a290f 6%, transparent);
  --aurora-c: color-mix(in srgb, #721045 5%, transparent);
}
@media (prefers-color-scheme: dark) {
  html:not([data-user-theme]) body.category-academic {
    --accent: #2fafff; --accent-light: #79a8ff;
    --accent-bg: color-mix(in srgb, #2fafff 10%, var(--bg-surface));
    --aurora-a: color-mix(in srgb, #2fafff 12%, transparent);
    --aurora-b: color-mix(in srgb, #79a8ff 7%, transparent);
    --aurora-c: color-mix(in srgb, #00d3d0 8%, transparent);
  }
  html:not([data-user-theme]) body.category-product {
    --accent: #00d3d0; --accent-light: #4ae0de;
    --accent-bg: color-mix(in srgb, #00d3d0 10%, var(--bg-surface));
    --aurora-a: color-mix(in srgb, #00d3d0 12%, transparent);
    --aurora-b: color-mix(in srgb, #d0bc00 7%, transparent);
    --aurora-c: color-mix(in srgb, #2fafff 8%, transparent);
  }
  html:not([data-user-theme]) body.category-comparison {
    --accent: #feacd0; --accent-light: #ffc0dc;
    --accent-bg: color-mix(in srgb, #feacd0 10%, var(--bg-surface));
    --aurora-a: color-mix(in srgb, #feacd0 12%, transparent);
    --aurora-b: color-mix(in srgb, #b6a0ff 6%, transparent);
    --aurora-c: color-mix(in srgb, #2fafff 8%, transparent);
  }
  html:not([data-user-theme]) body.category-howto {
    --accent: #44bc44; --accent-light: #70d070;
    --accent-bg: color-mix(in srgb, #44bc44 9%, var(--bg-surface));
    --aurora-a: color-mix(in srgb, #44bc44 12%, transparent);
    --aurora-b: color-mix(in srgb, #d0bc00 7%, transparent);
    --aurora-c: color-mix(in srgb, #00d3d0 7%, transparent);
  }
  html:not([data-user-theme]) body.category-landscape {
    --accent: #d0bc00; --accent-light: #e0d040;
    --accent-bg: color-mix(in srgb, #d0bc00 10%, var(--bg-surface));
    --aurora-a: color-mix(in srgb, #d0bc00 14%, transparent);
    --aurora-b: color-mix(in srgb, #ff5f59 7%, transparent);
    --aurora-c: color-mix(in srgb, #feacd0 6%, transparent);
  }
}

/* All categories keep Blueprint Iosevka / Roboto Mono — no per-category fonts. */

/* ── Per-category background effects ───────────────
   Subtle Blueprint textures on top of the default dots pattern. */

/* Product → blueprint grid */
body.category-product::before {
  background-image:
    linear-gradient(to right, color-mix(in srgb, var(--border) 35%, transparent) 1px, transparent 1px),
    linear-gradient(to bottom, color-mix(in srgb, var(--border) 35%, transparent) 1px, transparent 1px);
  background-size: 24px 24px;
  filter: none;
  animation: none;
}

/* Comparison → slightly denser dots */
body.category-comparison::before {
  background-image: radial-gradient(
    color-mix(in srgb, var(--text) 7%, transparent) 1px,
    transparent 1px
  );
  background-size: 16px 16px;
  filter: none;
  animation: none;
}

/* How-to → plain paper (no extra texture — keeps procedure scannable) */
body.category-howto::before {
  background-image: none;
  filter: none;
  animation: none;
}

/* Landscape → soft horizontal hairlines */
body.category-landscape::before {
  background-image: repeating-linear-gradient(
    180deg,
    transparent 0,
    transparent 19px,
    color-mix(in srgb, var(--border) 40%, transparent) 19px,
    color-mix(in srgb, var(--border) 40%, transparent) 20px
  );
  filter: none;
  animation: none;
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

/* ── HOWTO: numbered procedure ─────── */
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
  width: 32px; height: 32px;
  border-radius: var(--radius, 2px);
  background: var(--accent);
  color: #fff;
  font-family: var(--font-mono);
  font-size: 0.85rem;
  font-weight: 700;
  letter-spacing: 0;
  box-shadow: var(--shadow-sm, 2px 2px 0 color-mix(in srgb, var(--text) 18%, transparent));
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
  background: #0d0e1c;
  color: #d4e4d4;
  border: 1px solid color-mix(in srgb, var(--accent) 20%, transparent);
  border-radius: var(--radius, 2px);
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

/* ── LANDSCAPE: briefing with H3 player cards ─ */
body.category-landscape .content h3 {
  margin-top: 2.5rem;
  padding: 14px 18px 4px;
  border-left: 2px solid var(--accent);
  background: color-mix(in srgb, var(--accent) 4%, transparent);
  border-radius: 0 var(--radius, 2px) var(--radius, 2px) 0;
  font-family: var(--font-display);
  font-size: 1.05rem;
}
body.category-landscape .content h3 + p {
  margin-top: 0;
  padding: 0 18px 14px;
  background: color-mix(in srgb, var(--accent) 4%, transparent);
  border-left: 2px solid var(--accent);
  margin-left: 0;
  border-radius: 0 0 var(--radius, 2px) 0;
}
/* Pull-quote treatment for any standalone blockquote */
body.category-landscape .content blockquote {
  font-size: 1.05rem;
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
  font-style: normal;
}
body.category-landscape .content blockquote::before {
  display: none;
}

/* ── COMPARISON: lab-report tables with winner badges ─ */
body.category-comparison .content {
  font-feature-settings: 'tnum' on;
}
body.category-comparison .content table {
  font-size: 0.92rem;
  box-shadow: var(--shadow-sm, 2px 2px 0 color-mix(in srgb, var(--text) 18%, transparent));
}
body.category-comparison .content th {
  background: color-mix(in srgb, var(--accent) 18%, var(--bg-surface));
  color: var(--text);
  text-transform: uppercase;
  letter-spacing: var(--tracking-label, 0.06em);
  font-size: 0.72rem;
  font-weight: 700;
  font-family: var(--font-mono);
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
  font-family: var(--font-mono);
  font-size: 0.65rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: var(--tracking-label, 0.06em);
  border-radius: 0;
  vertical-align: middle;
}

/* ── PRODUCT: spec-sheet cards for each H3 ─────────── */
body.category-product .content h3 {
  margin-top: 2.4rem;
  padding: 16px 18px;
  border: 1px solid color-mix(in srgb, var(--accent) 28%, var(--border));
  background: var(--bg-surface);
  border-radius: var(--radius, 2px);
  display: flex; align-items: baseline; gap: 10px;
  font-family: var(--font-display);
  letter-spacing: -0.01em;
  box-shadow: var(--shadow-sm, 2px 2px 0 color-mix(in srgb, var(--text) 18%, transparent));
}
body.category-product .content h3::after {
  content: 'SPEC';
  margin-left: auto;
  font-family: var(--font-mono);
  font-size: 0.6rem;
  font-weight: 700;
  letter-spacing: var(--tracking-label, 0.06em);
  text-transform: uppercase;
  color: var(--accent);
  background: color-mix(in srgb, var(--accent) 10%, transparent);
  padding: 3px 8px;
  border-radius: 0;
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
  padding:5px 12px; border-radius:2px; font-size:0.82em; text-decoration:none;
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
  color: var(--success, #006300); font-weight:600;
  background:color-mix(in srgb, var(--success, #006300) 10%, transparent);
}
.category-comparison .content table td.cmp-neg {
  color: var(--error, #a60000); font-weight:600;
  background:color-mix(in srgb, var(--error, #a60000) 8%, transparent);
}
.category-comparison .content table td.cmp-mid {
  color: var(--gold, #6d5000);
  background:color-mix(in srgb, var(--gold, #6d5000) 8%, transparent);
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
  width:28px; height:28px; border-radius:2px;
  background:var(--accent); color:#fff; font-size:0.8em; font-weight:700;
  margin-right:10px; flex-shrink:0;
}
.category-howto .content { counter-reset:step-counter; }
.category-howto .content blockquote {
  border-left:2px solid var(--accent); background:color-mix(in srgb, var(--accent) 8%, transparent);
  padding:12px 16px; border-radius:0 2px 2px 0; margin:1em 0;
}
.category-howto .content blockquote strong:first-child {
  display:inline-block; margin-bottom:4px; text-transform:uppercase;
  font-size:0.82em; letter-spacing:0.5px;
}
.category-howto .content h2#quick-guide + ol,
.category-howto .content h2#quick-guide ~ ol:first-of-type {
  background:color-mix(in srgb, var(--accent) 8%, transparent);
  border:1px solid color-mix(in srgb, var(--accent) 20%, transparent);
  border-radius:2px; padding:14px 14px 14px 32px; font-size:0.95em; line-height:1.8;
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
  border-left:2px solid var(--gold, #6d5000);
  background:color-mix(in srgb, var(--gold, #6d5000) 8%, transparent);
  padding:10px 14px; border-radius:0 2px 2px 0;
}
""",
        "factcheck": """
/* Fact-check category */
.category-factcheck .hero {
  background: transparent;
}
.category-factcheck .content h2:first-of-type {
  font-size:1.4em; text-align:center; padding:16px 0; border:none;
  background:color-mix(in srgb, var(--accent) 8%, transparent);
  border-radius:2px; margin:1em 0;
}
.category-factcheck .content blockquote {
  position:relative; padding-left:20px;
}
.category-factcheck .content h2 ~ h3 {
  padding:6px 10px; border-radius:2px;
  border-left:2px solid var(--accent);
}
.category-factcheck .content strong:only-child {
  display:inline-block; padding:4px 12px; border-radius:2px;
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
    # Academic template section names — these are boilerplate section
    # headings, never a real report title, so skip them when choosing the
    # hero <h1> (otherwise every literature review is titled "Background").
    "background", "methods", "methodology", "discussion",
    "conflicting evidence", "conflicting or missing evidence",
    "limitations", "limitations of the evidence", "limitations of this report",
    "limitations compared", "references", "bibliography",
    "seed papers overview", "related work by theme", "methods and designs",
    "overlaps and distinctions vs seeds", "what the seed evidence covers",
    "identified gaps", "evidence addressing gaps",
    "papers compared", "methods comparison", "findings comparison",
    "search coverage", "citation verification", "source retrieval limitations",
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


def build_verification_badge_html(verification: Optional[dict]) -> str:
    """Structured badge summarizing the claim-grounding check.

    Renders a compact, color-coded badge plus a collapsible list of any
    flagged (unsupported/partial) claims. Returns "" when no check ran.
    """
    if not isinstance(verification, dict):
        return ""
    checked = int(verification.get("checked") or 0)
    if checked <= 0:
        return ""
    supported = int(verification.get("supported") or 0)
    partial = int(verification.get("partial") or 0)
    unsupported = int(verification.get("unsupported") or 0)
    confidence = verification.get("confidence")
    flagged = verification.get("flagged") or []

    if unsupported:
        tone, label = "thin", "Citations need review"
    elif partial:
        tone, label = "abstract", "Citations mostly verified"
    else:
        tone, label = "adequate", "Citations verified"

    conf_txt = f" · {int(confidence)}% supported" if isinstance(confidence, (int, float)) else ""
    counts = (
        f'<span class="verify-count verify-ok">{supported} supported</span>'
        f'<span class="verify-count verify-partial">{partial} partial</span>'
        f'<span class="verify-count verify-bad">{unsupported} unsupported</span>'
    )

    details_html = ""
    if flagged:
        rows = []
        for item in flagged[:20]:
            verdict = str(item.get("verdict") or "").upper()
            vcls = "verify-bad" if verdict == "UNSUPPORTED" else "verify-partial"
            cites = "".join(
                f'<span class="verify-cite">[{int(n)}]</span>'
                for n in (item.get("citations") or [])
                if isinstance(n, int) or str(n).isdigit()
            )
            reason = item.get("reason") or ""
            reason_html = f' — <span class="verify-reason">{html.escape(reason)}</span>' if reason else ""
            rows.append(
                f'<li><span class="verify-tag {vcls}">{html.escape(verdict.title())}</span> '
                f'{cites} <span class="verify-claim">{html.escape(item.get("claim", ""))}</span>'
                f'{reason_html}</li>'
            )
        details_html = (
            '<details class="verify-details">'
            f'<summary>Review {len(flagged)} flagged claim'
            f'{"" if len(flagged) == 1 else "s"}</summary>'
            f'<ul class="verify-list">{"".join(rows)}</ul>'
            '</details>'
        )

    return (
        f'<div class="verify-badge verify-{tone}" '
        f'title="Automated claim-grounding check of inline citations">'
        f'<div class="verify-head">'
        f'<span class="verify-dot"></span>'
        f'<span class="verify-label">{html.escape(label)}</span>'
        f'<span class="verify-meta">{checked} claims checked{conf_txt}</span>'
        f'</div>'
        f'<div class="verify-counts">{counts}</div>'
        f'{details_html}'
        f'</div>'
    )


def generate_visual_report(
    question: str,
    report_markdown: str,
    sources: Optional[List[Dict]] = None,
    stats: Optional[Dict] = None,
    category: Optional[str] = None,
    session_id: Optional[str] = None,
    hidden_images: Optional[List[str]] = None,
    evidence_registry: Optional[dict] = None,
    verification: Optional[dict] = None,
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
        verification_badge_html="",  # Citations-verified panel hidden from visual report
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
