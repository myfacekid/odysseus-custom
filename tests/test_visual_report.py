from bs4 import BeautifulSoup

from src.visual_report import (
    build_toc_html,
    generate_visual_report,
    linkify_citation_markers,
    split_executive_summary,
    sources_from_registry,
    strip_references_section,
)


def test_split_executive_summary():
    report = """## Executive Summary

Short overview [1].

## Background

More detail [2].
"""
    summary, body = split_executive_summary(report)
    assert "Short overview" in summary
    assert "## Background" in body
    assert "Executive Summary" not in body


def test_linkify_citation_markers_skips_markdown_links():
    html = linkify_citation_markers("Claim %%CITE:1%% and [2](https://ex.com)")
    assert 'href="#source-1"' in html
    assert "[2](https://ex.com)" in html


def test_linkify_citation_markers_body_with_executive_summary():
    """Body citations must linkify even when an executive summary is present."""
    summary_html = "<p>Summary %%CITE:1%%</p>"
    body_html = "<p>Body claim [2] here.</p>"
    combined = summary_html + body_html
    out = linkify_citation_markers(combined)
    assert 'href="#source-1"' in out
    assert 'href="#source-2"' in out


def test_visual_report_omits_scraped_images():
    html = generate_visual_report(
        "test question",
        "## Findings\n\nClaim [1].",
        sources=[{"url": "https://ex.com/a", "title": "Alpha", "image": "https://ex.com/photo.jpg"}],
        stats={},
        session_id="img-off",
    )
    assert "hero-image" not in html
    assert "section-image" not in html
    assert "https://ex.com/photo.jpg" not in html
    assert 'property="og:image"' not in html


def test_strip_references_section():
    report = "## Key Findings\n\nClaim [1].\n\n## References\n\n[1] Alpha"
    body = strip_references_section(report)
    assert "Key Findings" in body
    assert "References" not in body
    assert "Alpha" not in body


def test_build_toc_html_nests_h3_and_collapses_sources():
    headings = [
        {"level": 2, "text": "Background", "slug": "background"},
        {"level": 3, "text": "Methods", "slug": "methods"},
        {"level": 2, "text": "Findings", "slug": "findings"},
    ]
    toc = build_toc_html(
        headings,
        [{"citation_num": 1, "title": "Alpha paper", "url": "https://ex.com/a"}],
    )
    assert 'class="toc-group"' in toc
    assert "Sources (1)" in toc
    assert "Methods" in toc
    assert toc.count('class="toc-group"') >= 1
    assert "Findings" in toc


def test_sources_from_registry_prefers_registry_rows():
    registry = {
        "sources": [
            {
                "source_id": "src:web:https://ex.com/a",
                "citation_num": 2,
                "title": "Beta",
                "url": "https://ex.com/a",
            },
            {
                "source_id": "src:web:https://ex.com/b",
                "citation_num": 1,
                "title": "Alpha",
                "url": "https://ex.com/b",
            },
        ]
    }
    rows = sources_from_registry(registry, [{"title": "Legacy"}])
    assert [row["citation_num"] for row in rows] == [2, 1]
    assert rows[0]["title"] == "Beta"


def test_visual_report_toc_links_match_rendered_heading_ids():
    report = """
# Automated Crypto Trading Bot Strategies

### **1.0 Introduction & Research Scope**

Intro body.

### **2.0 Determining the "Best" Configuration**

Configuration body.
"""

    html = generate_visual_report(
        "crypto bot strategies",
        report,
        sources=[],
        stats={},
        session_id="rp-test",
    )
    soup = BeautifulSoup(html, "html.parser")

    links = soup.select(".toc-sidebar nav a")
    assert [link.get_text(strip=True) for link in links] == [
        "1.0 Introduction & Research Scope",
        '2.0 Determining the "Best" Configuration',
    ]

    for link in links:
        target_id = link["href"].removeprefix("#")
        target = soup.find(id=target_id)
        assert target is not None
        assert target.name in {"h2", "h3"}


def test_visual_report_renders_canonical_references_section():
    """References live in the sources panel, not duplicated in report body."""
    report = """## Key Findings

Claim one [1]. Claim two [2].

## References

[1] Smith (2024). Alpha paper. https://ex.com/a
[2] Jones (2023). Beta paper. https://ex.com/b
"""
    registry = {
        "sources": [
            {
                "source_id": "src:web:https://ex.com/a",
                "citation_num": 1,
                "title": "Alpha paper",
                "url": "https://ex.com/a",
            },
            {
                "source_id": "src:web:https://ex.com/b",
                "citation_num": 2,
                "title": "Beta paper",
                "url": "https://ex.com/b",
            },
        ]
    }
    html = generate_visual_report(
        "test question",
        report,
        sources=[],
        stats={},
        session_id="refs-test",
        evidence_registry=registry,
    )
    soup = BeautifulSoup(html, "html.parser")
    main = soup.select_one("main.content")
    assert main is not None
    assert "Alpha paper" in html
    assert soup.find(id="source-1") is not None
    assert main.find("h2", string=lambda t: t and "References" in t) is None
    assert "Key Findings" in main.get_text()


def test_visual_report_internal_document_source_has_node_id():
    registry = {
        "sources": [
            {
                "source_id": "src:graph:document:vault:notes/my-note.md",
                "citation_num": 1,
                "title": "My vault note",
                "url": "links://document:vault:notes/my-note.md",
                "sourcing_tier": "adequate",
            },
        ]
    }
    html = generate_visual_report(
        "test",
        "Claim [1].",
        sources=[],
        stats={},
        session_id="doc-test",
        evidence_registry=registry,
    )
    soup = BeautifulSoup(html, "html.parser")
    source_card = soup.select_one("#source-1")
    assert source_card is not None
    internal = soup.select_one('#source-1 a.source-detail-link[data-node-id]')
    assert internal is not None
    assert internal.get("data-node-id") == "document:vault:notes/my-note.md"


def test_visual_report_exec_summary_and_citation_jumps():
    report = """## Executive Summary

Finding [1].

## Key Findings

More [2].

## References

[1] Alpha
[2] Beta
"""
    registry = {
        "sources": [
            {
                "source_id": "src:web:https://ex.com/a",
                "citation_num": 1,
                "title": "Alpha paper",
                "url": "https://ex.com/a",
                "authors": "Smith",
                "year": "2024",
                "sourcing_tier": "adequate",
                "content_excerpt": "Alpha abstract text for the sidebar excerpt panel.",
            },
            {
                "source_id": "src:web:https://ex.com/b",
                "citation_num": 2,
                "title": "Beta paper",
                "url": "https://ex.com/b",
                "sourcing_tier": "abstract_only",
            },
        ]
    }
    html = generate_visual_report(
        "test question",
        report,
        sources=[],
        stats={},
        session_id="ui-test",
        evidence_registry=registry,
    )
    soup = BeautifulSoup(html, "html.parser")
    assert soup.select_one("details.exec-summary-panel")
    assert soup.select_one('a.cite-link[data-cite="1"]')
    assert soup.select_one('a.cite-link[data-cite="2"]')
    assert soup.find(id="source-1")
    source_card = soup.select_one("#source-1")
    assert source_card is not None
    assert source_card.select_one(".tier-badge")
    assert "Alpha paper" in source_card.get_text()
    toc_source = soup.select_one(".toc-sources-group a")
    assert toc_source is not None
    assert "Alpha paper" in toc_source.get_text()
    assert soup.select_one(".sourcing-disclosure")
    assert soup.select_one(".sources-sidebar")
    assert soup.select_one('.source-filter[data-filter="seed"]')
    main = soup.select_one("main.content")
    ref_headings = [h.get_text(strip=True) for h in main.find_all("h2")]
    assert not any("References" in text for text in ref_headings)
    assert "full text" in soup.select_one(".sourcing-disclosure").get_text()
    assert "abstract only" in soup.select_one(".sourcing-disclosure").get_text()
    assert soup.select_one("#source-1 .source-excerpt")


def test_zotero_key_from_source_row():
    from src.visual_report import zotero_key_from_source_row

    assert zotero_key_from_source_row({"source_id": "src:zotero:ABCD1234"}) == "ABCD1234"
    assert zotero_key_from_source_row({"source_id": "src:paper:WXYZ9876"}) == "WXYZ9876"
    assert zotero_key_from_source_row({"doi_or_id": "PAPERKEY"}) == "PAPERKEY"


def test_build_sources_sidebar_html_includes_zotero_and_excerpt():
    from src.visual_report import build_sources_sidebar_html

    html = build_sources_sidebar_html([
        {
            "citation_num": 1,
            "title": "Seed paper",
            "source_id": "src:zotero:SEED1234",
            "is_seed": True,
            "sourcing_tier": "adequate",
            "content_excerpt": "Methods and results excerpt.",
            "zotero_key": "SEED1234",
        },
    ])
    assert 'id="source-1"' in html
    assert "SEED1234" in html
    assert "Methods and results excerpt." in html
    assert 'data-filter="seed"' in html
    assert "Seed</span>" in html
