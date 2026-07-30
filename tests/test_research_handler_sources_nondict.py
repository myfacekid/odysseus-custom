from src.research_handler import ResearchHandler


def test_extract_sources_skips_non_dict_findings():
    # findings come from the LDR result list / cached JSON; a
    # malformed entry (None or a bare string) made the old loop call .get on a
    # non-dict and crash, dropping every real source in the set.
    findings = [
        {"url": "https://a.com", "title": "A", "summary": "real analysis of the topic"},
        "junk-row",
        None,
        {"url": "https://b.com", "summary": "more genuine detail here"},
    ]
    out = ResearchHandler._extract_sources(findings)
    assert [s["url"] for s in out] == ["https://a.com", "https://b.com"]


def test_extract_sources_keeps_ldr_content_field():
    findings = [
        {
            "url": "https://doi.org/10.1/x",
            "title": "Paper",
            "content": "Detailed snippet about the experimental methods and results.",
        },
        {
            "url": "https://doi.org/10.1/y",
            "title": "Abstract only",
            "abstract": "Peer-reviewed abstract describing the study population.",
        },
    ]
    out = ResearchHandler._extract_sources(findings)
    assert [s["url"] for s in out] == ["https://doi.org/10.1/x", "https://doi.org/10.1/y"]


def test_extract_raw_findings_uses_content():
    findings = [
        {
            "url": "https://example.com/p",
            "title": "T",
            "content": "Concrete experimental findings from the paper.",
        }
    ]
    out = ResearchHandler._extract_raw_findings(findings)
    assert len(out) == 1
    assert out[0]["summary"].startswith("Concrete experimental")
