"""DOI resolution via PubMed / Europe PMC."""

from unittest.mock import patch

from src.research_paper_fetch import (
    is_usable_paper_content,
    normalize_doi,
    resolve_paper_content_by_doi,
)


def test_normalize_doi_from_url():
    assert normalize_doi("https://doi.org/10.1038/s41586-021-03819-2") == "10.1038/s41586-021-03819-2"


def test_is_usable_paper_content_rejects_shell():
    assert not is_usable_paper_content("Redirecting you to the publisher. Enable JavaScript.")
    assert not is_usable_paper_content("Short title only")


def test_resolve_paper_content_by_doi_pubmed(monkeypatch):
    monkeypatch.setattr(
        "src.research_paper_fetch.fetch_pubmed_abstract",
        lambda doi: {
            "abstract": "AlphaFold predicts protein structures with high accuracy. " * 20,
            "source_url": "https://pubmed.ncbi.nlm.nih.gov/123/",
            "source": "pubmed",
        },
    )
    monkeypatch.setattr("src.research_paper_fetch.fetch_europe_pmc_record", lambda doi: {})
    out = resolve_paper_content_by_doi("10.1038/s41586-021-03819-2", fetch_fulltext=False)
    assert out.get("abstract")
    assert len(out["abstract"]) > 400


def test_enrich_title_only_seed_via_pubmed(monkeypatch):
    from src.research_seeds import enrich_seed_finding_from_web

    finding = {
        "title": "Evolutionary-scale prediction of atomic-level protein structure with a language model",
        "doi_or_id": "10.1126/science.adl5899",
        "summary": "Bibliographic record: Evolutionary-scale prediction of atomic-level protein structure with a language model",
        "evidence": "",
        "pdf_fetch_failed": True,
        "has_pdf": True,
        "zotero_key": "ESMKEY1",
    }

    monkeypatch.setattr("src.research_seeds.refresh_seed_from_zotero_api", lambda owner, f: f)
    monkeypatch.setattr(
        "src.research_seeds._fetch_zotero_pdf_text",
        lambda owner, key, max_chars: ("", "PDF download failed"),
    )
    monkeypatch.setattr(
        "src.research_paper_fetch.resolve_paper_content_by_doi",
        lambda doi, title="", fetch_fulltext=True: {
            "abstract": "ESM3 is a multimodal generative model of protein sequence, structure, and function. " * 12,
            "source_url": "https://pubmed.ncbi.nlm.nih.gov/999/",
            "source": "pubmed",
        },
    )

    enriched = enrich_seed_finding_from_web(finding, owner="tester", max_chars=5000)
    assert len(enriched.get("evidence") or "") > 400
    assert enriched.get("sourcing_tier") in ("abstract_only", "adequate")
    assert enriched.get("allow_substantive_claims") is True
    assert enriched.get("sourcing_tier") != "retrieval_failed"


def test_alphafold_catalog_abstract_is_usable_without_failure():
    from src.research_sourcing import SOURCING_TIER_ABSTRACT_ONLY, SOURCING_TIER_ADEQUATE, assess_finding_sourcing

    abstract = (
        "Proteins are essential to life, and understanding their structure can facilitate "
        "a mechanistic understanding of their function. " * 8
    )
    finding = {
        "title": "Highly accurate protein structure prediction with AlphaFold",
        "abstract": abstract,
        "summary": abstract[:800],
        "evidence": abstract,
        "doi_or_id": "10.1038/s41586-021-03819-2",
    }
    tier, _, allow = assess_finding_sourcing(finding)
    assert tier in (SOURCING_TIER_ADEQUATE, SOURCING_TIER_ABSTRACT_ONLY)
    assert allow is True


def test_abstract_only_not_listed_as_retrieval_failure():
    from src.research_evidence import EvidenceRegistry
    from src.research_sourcing import is_thin_sourcing

    reg = EvidenceRegistry()
    abstract = "Protein structure prediction methods have improved substantially. " * 12
    reg.register({
        "title": "Highly accurate protein structure prediction with AlphaFold",
        "url": "https://doi.org/10.1038/s41586-021-03819-2",
        "abstract": abstract,
        "summary": abstract[:800],
        "evidence": abstract,
    })
    src = reg.sources()[0]
    assert not is_thin_sourcing(src.sourcing_tier)
    block = reg.sourcing_limitations_block()
    assert "NOT adequately retrieved" not in block or "AlphaFold" not in block
