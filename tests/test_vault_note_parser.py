"""Tests for Obsidian note parsing."""

from src.vault_note_parser import parse_note, parse_frontmatter


def test_frontmatter_and_tags():
    text = """---
tags: [genomics, influenza]
aliases: [Epi note]
status: draft
---

# Body
Inline #epistasis mention.
Related [[Epistasis and Influenza]].
field:: value
"""
    fm, body = parse_frontmatter(text)
    assert fm.get("status") == "draft"
    parsed = parse_note("Notes/test.md", text)
    assert "genomics" in parsed.tags
    assert "influenza" in parsed.tags
    assert "epistasis" in parsed.tags
    assert "Epi note" in parsed.aliases
    assert "Epistasis and Influenza" in parsed.wikilinks
    assert parsed.dataview_fields.get("field") == "value"
    assert parsed.dataview_fields.get("status") == "draft"
