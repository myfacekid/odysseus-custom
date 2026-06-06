"""Research source link resolution and citation placeholders."""

from src.research_source_links import (
    enrich_registry_source_row,
    graph_node_id_from_source,
    inject_citation_placeholders,
    linkify_bracket_citations_html,
    linkify_citation_placeholders_html,
    resolve_source_href,
)


def test_graph_node_from_links_scheme():
    assert graph_node_id_from_source("links://document:doc-1", "") == "document:doc-1"
    assert graph_node_id_from_source("", "src:graph:paper:ABCD1234") == "paper:ABCD1234"


def test_resolve_internal_document_href():
    nav = resolve_source_href("links://document:abc123", "src:graph:document:abc123", citation_num=2)
    assert nav["href"] == "#document-abc123"
    assert nav["external"] is False
    assert nav["node_id"] == "document:abc123"

    visual = resolve_source_href(
        "links://document:abc123",
        "src:graph:document:abc123",
        citation_num=2,
        for_visual_report=True,
    )
    assert visual["href"] == "/#document-abc123"


def test_resolve_paper_href():
    nav = resolve_source_href("", "src:paper:ABCD1234", citation_num=1)
    assert nav["href"] == "#paper-ABCD1234"
    assert nav["node_id"] == "paper:ABCD1234"


def test_inject_citation_placeholders_skips_reference_definitions():
    md = "Claim [1].\n\n[1]: https://example.com/paper"
    out = inject_citation_placeholders(md)
    assert "%%CITE:1%%" in out.split("\n")[0]
    assert "[1]: https://example.com/paper" in out


def test_linkify_citation_placeholders_html():
    html = linkify_citation_placeholders_html("<p>See %%CITE:2%% here.</p>")
    assert 'href="#source-2"' in html
    assert "[2]" in html


def test_linkify_bracket_citations_skips_existing_anchors():
    html = linkify_bracket_citations_html(
        '<p>See [1] and <a href="https://ex.com">[2]</a> here.</p>'
    )
    assert 'href="#source-1"' in html
    assert 'href="https://ex.com">[2]</a>' in html
    assert html.count('href="#source-2"') == 0


def test_linkify_citation_placeholders_html_bracket_fallback():
    html = linkify_citation_placeholders_html("<p>Claim [3] without placeholder.</p>")
    assert 'href="#source-3"' in html


def test_resolve_vault_document_href():
    nav = resolve_source_href(
        "links://document:vault:notes/my-note.md",
        "src:graph:document:vault:notes/my-note.md",
        citation_num=1,
    )
    assert nav["href"] == "#document-vault:notes/my-note.md"
    assert nav["node_id"] == "document:vault:notes/my-note.md"


def test_enrich_registry_source_row():
    row = enrich_registry_source_row(
        {
            "citation_num": 3,
            "title": "My note",
            "url": "links://document:note-9",
            "source_id": "src:graph:document:note-9",
        }
    )
    assert row["href"] == "#document-note-9"
    assert row["node_id"] == "document:note-9"
