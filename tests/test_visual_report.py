from bs4 import BeautifulSoup

from src.visual_report import generate_visual_report


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
    """Visual report should render the canonical markdown References block."""
    report = """## Key Findings

Claim one [1]. Claim two [2].

## References

[1] Smith (2024). Alpha paper. https://ex.com/a
[2] Jones (2023). Beta paper. https://ex.com/b
"""
    html = generate_visual_report(
        "test question",
        report,
        sources=[],
        stats={},
        session_id="refs-test",
    )
    assert "Alpha paper" in html
    assert "Beta paper" in html
    assert "References" in html
