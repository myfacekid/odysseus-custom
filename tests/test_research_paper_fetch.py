"""DOI resolution via PubMed / Europe PMC."""

from unittest.mock import patch

from src.research_paper_fetch import (
    doi_urls,
    fetch_doi_article_html,
    fetch_doi_pdf_text,
    fetch_pmc_article_html,
    fetch_pmc_pdf_text,
    is_usable_paper_content,
    normalize_doi,
    normalize_pmcid,
    pmc_article_urls,
    resolve_paper_content_by_doi,
)


def test_doi_urls():
    urls = doi_urls("10.1038/s41587-023-01773-0")
    assert urls["doi"] == "10.1038/s41587-023-01773-0"
    assert urls["html"] == "https://doi.org/10.1038/s41587-023-01773-0"
    assert urls["pdf"] == urls["html"]


def test_fetch_doi_pdf_text_mocked(monkeypatch):
    body = b"%PDF-1.4 mock"
    monkeypatch.setattr(
        "src.research_paper_fetch._http_get",
        lambda url, accept="*/*", timeout=25: (body, "application/pdf", url),
    )
    monkeypatch.setattr(
        "src.research_paper_fetch._extract_pdf_from_bytes",
        lambda raw, max_chars=50000: "DOI negotiated PDF full text about proteins. " * 40,
    )
    out = fetch_doi_pdf_text("10.1038/s41587-023-01773-0", title="Foldseek")
    assert out.get("source") == "doi_pdf"
    assert len(out.get("fulltext", "")) > 900


def test_resolve_paper_content_uses_doi_routes_when_no_pmc(monkeypatch):
    monkeypatch.setattr("src.research_paper_fetch.fetch_pubmed_abstract", lambda doi: {})
    monkeypatch.setattr("src.research_paper_fetch.fetch_europe_pmc_record", lambda doi: {})
    monkeypatch.setattr(
        "src.research_paper_fetch.fetch_doi_pdf_text",
        lambda doi, title="", max_chars=50000: {
            "fulltext": "Publisher PDF via doi.org content negotiation. " * 50,
            "source": "doi_pdf",
            "source_url": "https://doi.org/10.1038/s41587-023-01773-0",
        },
    )
    monkeypatch.setattr("src.research_paper_fetch.fetch_doi_article_html", lambda *a, **k: {})

    out = resolve_paper_content_by_doi("10.1038/s41587-023-01773-0", fetch_fulltext=True)
    assert out.get("fulltext")
    assert out.get("source") == "doi_pdf"


def test_normalize_pmcid():
    assert normalize_pmcid("5817331") == "PMC5817331"
    assert normalize_pmcid("pmc5817331") == "PMC5817331"
    assert normalize_pmcid("https://pmc.ncbi.nlm.nih.gov/articles/PMC5817331/") == "PMC5817331"


def test_pmc_article_urls():
    urls = pmc_article_urls("PMC5817331")
    assert urls["html"] == "https://pmc.ncbi.nlm.nih.gov/articles/PMC5817331/"
    assert urls["pdf"] == "https://pmc.ncbi.nlm.nih.gov/articles/PMC5817331/pdf/"


def test_fetch_pmc_pdf_text_mocked(monkeypatch):
    body = b"%PDF-1.4 mock"
    monkeypatch.setattr("src.research_paper_fetch._http_bytes", lambda url, timeout=25: body)
    monkeypatch.setattr(
        "src.research_paper_fetch._extract_pdf_from_bytes",
        lambda raw, max_chars=50000: "PMC PDF extracted full text about proteins. " * 40,
    )
    out = fetch_pmc_pdf_text("PMC5817331", title="Example")
    assert out.get("source") == "pmc_pdf"
    assert len(out.get("fulltext", "")) > 900
    assert out.get("source_url", "").endswith("/pdf/")


def test_resolve_paper_content_uses_pmc_routes(monkeypatch):
    monkeypatch.setattr("src.research_paper_fetch.fetch_pubmed_abstract", lambda doi: {})
    monkeypatch.setattr(
        "src.research_paper_fetch.fetch_europe_pmc_record",
        lambda doi: {
            "abstract": "Europe PMC abstract for a protein structure search method. " * 12,
            "source": "europe_pmc",
            "pmcid": "PMC5817331",
            "pmc_html_url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC5817331/",
            "pmc_pdf_url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC5817331/pdf/",
            "source_url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC5817331/",
        },
    )
    monkeypatch.setattr("src.research_paper_fetch._pmc_xml_text", lambda pmcid: "")
    monkeypatch.setattr(
        "src.research_paper_fetch.fetch_pmc_pdf_text",
        lambda pmcid, title="", max_chars=50000: {
            "fulltext": "Full PMC PDF text for structure alignment and remote homology. " * 50,
            "source": "pmc_pdf",
            "source_url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC5817331/pdf/",
        },
    )
    monkeypatch.setattr("src.research_paper_fetch.fetch_pmc_article_html", lambda *a, **k: {})
    monkeypatch.setattr("src.research_paper_fetch.fetch_doi_pdf_text", lambda *a, **k: {})
    monkeypatch.setattr("src.research_paper_fetch.fetch_doi_article_html", lambda *a, **k: {})

    out = resolve_paper_content_by_doi("10.1038/s41587-023-01773-0", fetch_fulltext=True)
    assert out.get("fulltext")
    assert out.get("source") == "pmc_pdf"


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
