"""Tests for paper section parsing (Paper Token Retrieval R1)."""

from src.paper_sections import (
    extract_section_text,
    normalize_section_slug,
    parse_pdf_sections,
)


SAMPLE_PAPER = """
1. Introduction

We study optimization in deep learning.
Prior work used SGD.

2. Methods

We train with AdamW and cosine decay.
Batch size 256 on 8 GPUs.

3. Results

Accuracy improved by 2.1 points on ImageNet.

4. Discussion

Limitations include compute cost.
"""


def test_normalize_section_slug_aliases():
    assert normalize_section_slug("methods") == "methods"
    assert normalize_section_slug("Materials and Methods") == "methods"
    assert normalize_section_slug("experimental setup") == "methods"
    assert normalize_section_slug("intro") == "introduction"
    assert normalize_section_slug("bogus") is None


def test_parse_pdf_sections_detects_headings():
    sections = parse_pdf_sections(SAMPLE_PAPER)
    assert "introduction" in sections
    assert "methods" in sections
    assert "results" in sections
    assert "discussion" in sections
    assert "AdamW" in sections["methods"]
    assert "ImageNet" in sections["results"]


def test_extract_section_text_truncates():
    long_methods = "2. Methods\n\n" + ("word " * 5000)
    text, slug, available = extract_section_text(long_methods, "methods", max_chars=500)
    assert slug == "methods"
    assert len(text) <= 520
    assert "truncated" in text
    assert "methods" in available


def test_extract_section_text_missing_section():
    text, slug, available = extract_section_text(SAMPLE_PAPER, "limitations", max_chars=1000)
    assert text == ""
    assert slug is None
    assert "methods" in available
