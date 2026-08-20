"""Tests for Nobody LDR Zotero/knowledge tool mapping."""

from src.research.ldr_tools import _findings_to_ldr_results


def test_findings_to_ldr_results_uses_evidence_when_content_missing():
    results = _findings_to_ldr_results(
        [
            {
                "title": "Catalog paper",
                "url": "https://doi.org/10.1/paper",
                "evidence": "Abstract and PDF excerpt about folding.",
                "abstract": "Abstract about folding.",
                "doi_or_id": "10.1/paper",
                "zotero_key": "ABC",
                "paper_key": "ABC",
            }
        ]
    )
    assert len(results) == 1
    assert "folding" in results[0]["snippet"].lower()
    assert results[0]["content"] == results[0]["snippet"]
    assert results[0]["zotero_key"] == "ABC"
