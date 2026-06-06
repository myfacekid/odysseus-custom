"""Source retrieval quality and title-only inference guards."""

from src.research_evidence import EvidenceRegistry
from src.research_sourcing import (
    SOURCING_TIER_ADEQUATE,
    SOURCING_TIER_ABSTRACT_ONLY,
    SOURCING_TIER_METADATA_ONLY,
    SOURCING_TIER_RETRIEVAL_FAILED,
    annotate_finding_sourcing,
    assess_finding_sourcing,
    build_sourcing_limitations_block,
    ensure_sourcing_disclosure,
    format_finding_content_for_prompt,
    is_thin_sourcing,
)


def test_metadata_only_when_only_title_available():
    finding = {
        "title": "Evolutionary-scale prediction with ESM3",
        "summary": "Evolutionary-scale prediction with ESM3",
        "evidence": "Evolutionary-scale prediction with ESM3",
        "authors": "Hayes, Tom",
    }
    tier, note, allow = assess_finding_sourcing(finding)
    assert tier == SOURCING_TIER_METADATA_ONLY
    assert allow is False
    assert "title" in note.lower()


def test_retrieval_failed_when_pdf_missing_and_no_web():
    finding = {
        "title": "Evolutionary-scale prediction with ESM3",
        "summary": "Bibliographic record: Evolutionary-scale prediction with ESM3",
        "evidence": "",
        "pdf_fetch_failed": True,
        "has_pdf": True,
    }
    tier, _, allow = assess_finding_sourcing(finding)
    assert tier == SOURCING_TIER_RETRIEVAL_FAILED
    assert allow is False


def test_adequate_when_full_text_present():
    finding = {
        "title": "AlphaFold",
        "evidence": "x" * 1200,
        "pdf_extracted": True,
    }
    tier, _, allow = assess_finding_sourcing(finding)
    assert tier == SOURCING_TIER_ADEQUATE
    assert allow is True


def test_abstract_only_allows_substantive_claims_with_caveat():
    abstract = "Protein structure prediction using neural networks has advanced. " * 8
    finding = {
        "title": "Highly accurate protein structure prediction with AlphaFold",
        "abstract": abstract,
        "evidence": abstract,
        "summary": abstract[:500],
    }
    tier, _, allow = assess_finding_sourcing(finding)
    assert tier == SOURCING_TIER_ABSTRACT_ONLY
    assert allow is True
    assert not is_thin_sourcing(tier)


def test_format_finding_content_blocks_title_inference():
    finding = {
        "title": "Evolutionary-scale prediction with ESM3",
        "summary": "ESM3 is a generative model for proteins.",
        "evidence": "Evolutionary-scale prediction with ESM3",
    }
    text = format_finding_content_for_prompt(finding)
    assert "do not" in text.lower() or "not" in text.lower()
    assert "generative model" not in text.lower()


def test_sourcing_limitations_block_lists_thin_sources():
    reg = EvidenceRegistry()
    reg.register({
        "title": "ESM3 paper",
        "url": "https://doi.org/10.1/esm3",
        "summary": "ESM3 paper",
        "evidence": "ESM3 paper",
        "is_seed": True,
    })
    block = reg.sourcing_limitations_block()
    assert "NOT adequately retrieved" in block
    assert "ESM3 paper" in block


def test_ensure_sourcing_disclosure_appends_when_missing():
    reg = EvidenceRegistry()
    reg.register({
        "title": "ESM3 paper",
        "url": "https://doi.org/10.1/esm3",
        "summary": "ESM3 paper",
        "evidence": "ESM3 paper",
    })
    report = "## Executive Summary\n\nSome text [1].\n\n## References\n\n[1] Ref"
    out = ensure_sourcing_disclosure(report, reg.sources())
    assert "Source retrieval limitations" in out
    assert "ESM3 paper" in out


def test_annotate_finding_sourcing_sets_fields():
    finding = annotate_finding_sourcing({
        "title": "Short",
        "summary": "Short",
    })
    assert finding["allow_substantive_claims"] is False
    assert finding["sourcing_tier"] == SOURCING_TIER_METADATA_ONLY
