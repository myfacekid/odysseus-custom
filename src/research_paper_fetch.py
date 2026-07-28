"""Resolve paper abstracts and open-access text by DOI (PubMed, Europe PMC)."""
from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, Optional

logger = logging.getLogger(__name__)

_USER_AGENT = "Nobody-DeepResearch/1.0 (mailto:support@example.com)"
_MIN_USEFUL_CHARS = 280
_SHELL_MARKERS = (
    "redirecting",
    "just a moment",
    "enable javascript",
    "needs javascript",
    "cookies",
    "access denied",
    "purchase this article",
    "sign in to",
    "log in to",
    "clipboard, search history",
)


def normalize_doi(raw: str) -> str:
    from src.research_finding_enrich import extract_doi

    text = (raw or "").strip()
    if text.lower().startswith("10.") and "/" in text:
        return text.split()[0].rstrip("/")
    found = extract_doi(text)
    return found or ""


def is_usable_paper_content(text: str, *, title: str = "") -> bool:
    """Reject DOI landing shells and title-only stubs."""
    body = (text or "").strip()
    if len(body) < _MIN_USEFUL_CHARS:
        return False
    lower = body.lower()
    if any(marker in lower for marker in _SHELL_MARKERS):
        return False
    title = (title or "").strip()
    if title and len(body) < max(len(title) + 160, 320):
        remainder = body.lower().replace(title.lower(), "").strip(" .-|,")
        if len(re.findall(r"[a-z0-9]+", remainder)) < 20:
            return False
    return True


def _http_text(url: str, *, timeout: int = 20) -> str:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": _USER_AGENT, "Accept": "*/*"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
        logger.info("Paper fetch failed (%s): %s", url[:80], exc)
        return ""


def doi_urls(doi: str) -> Dict[str, str]:
    """Canonical doi.org landing URL (HTML and PDF via content negotiation)."""
    doi = normalize_doi(doi)
    if not doi.startswith("10."):
        return {}
    encoded = urllib.parse.quote(doi, safe="/")
    landing = f"https://doi.org/{encoded}"
    return {"html": landing, "pdf": landing, "doi": doi}


def _http_get(
    url: str,
    *,
    accept: str = "*/*",
    timeout: int = 25,
) -> tuple[bytes, str, str]:
    """GET with Accept header; returns (body, content_type, final_url)."""
    req = urllib.request.Request(
        url,
        headers={"User-Agent": _USER_AGENT, "Accept": accept},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read(), (resp.headers.get("Content-Type") or ""), (resp.geturl() or url)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
        logger.info("Paper GET failed (%s): %s", url[:80], exc)
        return b"", "", url


def fetch_doi_pdf_text(
    doi: str,
    *,
    title: str = "",
    max_chars: int = 50000,
) -> Dict[str, str]:
    """Request PDF from doi.org (content negotiation) and extract text."""
    urls = doi_urls(doi)
    landing = urls.get("pdf") or ""
    if not landing:
        return {}
    body, ctype, final_url = _http_get(
        landing,
        accept="application/pdf,application/x-pdf,text/pdf;q=0.9,*/*;q=0.1",
        timeout=30,
    )
    is_pdf = body.startswith(b"%PDF") or "pdf" in ctype.lower()
    if not is_pdf or not body:
        return {}
    text = _extract_pdf_from_bytes(body, max_chars=max_chars)
    if not is_usable_paper_content(text, title=title):
        return {}
    return {
        "fulltext": text[:max_chars],
        "source": "doi_pdf",
        "source_url": final_url or landing,
    }


def fetch_doi_article_html(
    doi: str,
    *,
    title: str = "",
    max_chars: int = 50000,
) -> Dict[str, str]:
    """Follow doi.org to the publisher HTML page and extract article text."""
    urls = doi_urls(doi)
    landing = urls.get("html") or ""
    if not landing:
        return {}
    try:
        body, ctype, final_url = _http_get(
            landing,
            accept="text/html,application/xhtml+xml;q=0.9,*/*;q=0.1",
            timeout=25,
        )
        text = ""
        if body and "html" in ctype.lower():
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(body.decode("utf-8", errors="replace"), "html.parser")
            for tag in soup.find_all(["script", "style", "nav", "header", "footer", "aside"]):
                tag.decompose()
            main = (
                soup.find("article")
                or soup.find("main")
                or soup.find("div", class_=re.compile(r"\barticle\b|fulltext|body-content", re.I))
            )
            if main:
                text = re.sub(r"\s+", " ", main.get_text(separator=" ", strip=True)).strip()
        if not text:
            from src.search.content import fetch_webpage_content

            page = fetch_webpage_content(landing, timeout=20, include_og_image=False)
            text = (page.get("content") or "").strip()
            final_url = page.get("url") or final_url or landing
    except Exception as exc:
        logger.info("DOI article HTML fetch failed (%s): %s", landing[:80], exc)
        return {}
    if not is_usable_paper_content(text, title=title):
        return {}
    return {
        "fulltext": text[:max_chars],
        "source": "doi_article_html",
        "source_url": final_url or landing,
    }


def _apply_doi_fulltext(
    best: Dict[str, str],
    doi: str,
    *,
    title: str = "",
) -> None:
    """Try doi.org PDF negotiation then publisher HTML — keep the richest result."""
    doi = normalize_doi(doi)
    if not doi.startswith("10."):
        return

    candidates: list[tuple[str, Dict[str, str]]] = []

    pdf_hit = fetch_doi_pdf_text(doi, title=title)
    if pdf_hit.get("fulltext"):
        candidates.append((pdf_hit["fulltext"], pdf_hit))

    html_hit = fetch_doi_article_html(doi, title=title)
    if html_hit.get("fulltext"):
        candidates.append((html_hit["fulltext"], html_hit))

    if not candidates:
        return

    text, meta = max(candidates, key=lambda row: len(row[0]))
    if len(text) > len(best.get("fulltext", "")):
        best["fulltext"] = text[:50000]
        best["source"] = meta.get("source") or "doi_fulltext"
        best["source_url"] = meta.get("source_url") or best.get("source_url", "")
        urls = doi_urls(doi)
        if urls.get("doi"):
            best["doi"] = urls["doi"]


def fetch_pdf_text_from_url(url: str, *, max_chars: int = 50000) -> str:
    """Download a PDF URL and extract text."""
    if not url or not url.startswith("http"):
        return ""
    raw = _http_bytes(url, timeout=30)
    if not raw:
        return ""
    return _extract_pdf_from_bytes(raw, max_chars=max_chars)


def normalize_pmcid(raw: str) -> str:
    """Normalize PMCID to ``PMC12345`` form."""
    text = (raw or "").strip()
    if not text:
        return ""
    match = re.search(r"(PMC\d+)", text, re.I)
    if match:
        return match.group(1).upper()
    if text.isdigit():
        return f"PMC{text}"
    return ""


def pmc_article_urls(pmcid: str) -> Dict[str, str]:
    """Canonical PMC article HTML and auto-resolve PDF URLs."""
    cid = normalize_pmcid(pmcid)
    if not cid:
        return {}
    base = f"https://pmc.ncbi.nlm.nih.gov/articles/{cid}/"
    return {"html": base, "pdf": f"{base}pdf/"}


def _http_bytes(url: str, *, timeout: int = 25) -> bytes:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": _USER_AGENT, "Accept": "application/pdf,*/*"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
        logger.info("Paper fetch bytes failed (%s): %s", url[:80], exc)
        return b""


def _extract_pdf_from_bytes(raw: bytes, *, max_chars: int = 50000) -> str:
    """Extract PDF text (wrapper for tests and lazy import)."""
    if not raw:
        return ""
    try:
        from src.search.content import _extract_pdf_bytes

        return (_extract_pdf_bytes(raw, max_chars=max_chars) or "").strip()
    except Exception as exc:
        logger.info("PDF extract failed: %s", exc)
        return ""


def fetch_pmc_pdf_text(
    pmcid: str,
    *,
    title: str = "",
    max_chars: int = 50000,
) -> Dict[str, str]:
    """Download full text via PMC ``/pdf/`` redirect and extract with pypdf."""
    urls = pmc_article_urls(pmcid)
    pdf_url = urls.get("pdf") or ""
    if not pdf_url:
        return {}
    raw = _http_bytes(pdf_url, timeout=30)
    if not raw:
        return {}
    text = _extract_pdf_from_bytes(raw, max_chars=max_chars)
    if not is_usable_paper_content(text, title=title):
        return {}
    return {
        "fulltext": text[:max_chars],
        "source": "pmc_pdf",
        "source_url": pdf_url,
    }


def fetch_pmc_article_html(
    pmcid: str,
    *,
    title: str = "",
    max_chars: int = 50000,
) -> Dict[str, str]:
    """Fetch readable article text from the PMC article HTML page."""
    urls = pmc_article_urls(pmcid)
    html_url = urls.get("html") or ""
    if not html_url:
        return {}
    try:
        from bs4 import BeautifulSoup

        page_html = _http_text(html_url, timeout=25)
        if not page_html:
            return {}
        soup = BeautifulSoup(page_html, "html.parser")
        for tag in soup.find_all(["script", "style", "nav", "header", "footer", "aside"]):
            tag.decompose()
        main = (
            soup.find("div", id="mc")
            or soup.find("article")
            or soup.find("main")
            or soup.find("div", class_=re.compile(r"\barticle\b", re.I))
        )
        if main:
            text = re.sub(r"\s+", " ", main.get_text(separator=" ", strip=True)).strip()
        else:
            from src.search.content import fetch_webpage_content

            page = fetch_webpage_content(html_url, timeout=15, include_og_image=False)
            text = (page.get("content") or "").strip()
    except Exception as exc:
        logger.info("PMC article HTML fetch failed (%s): %s", html_url[:80], exc)
        return {}
    if not is_usable_paper_content(text, title=title):
        return {}
    return {
        "fulltext": text[:max_chars],
        "source": "pmc_article_html",
        "source_url": html_url,
    }


def _apply_pmc_fulltext(
    best: Dict[str, str],
    pmcid: str,
    *,
    title: str = "",
) -> None:
    """Try PMC BioC, PDF, and article HTML — keep the richest result."""
    cid = normalize_pmcid(pmcid)
    if not cid:
        return

    candidates: list[tuple[str, Dict[str, str]]] = []

    bioc = _pmc_xml_text(cid)
    if is_usable_paper_content(bioc, title=title):
        urls = pmc_article_urls(cid)
        candidates.append(
            (
                bioc,
                {
                    "source": "pmc_bioc",
                    "source_url": urls.get("html") or f"https://pmc.ncbi.nlm.nih.gov/articles/{cid}/",
                },
            )
        )

    pdf_hit = fetch_pmc_pdf_text(cid, title=title)
    if pdf_hit.get("fulltext"):
        candidates.append((pdf_hit["fulltext"], pdf_hit))

    html_hit = fetch_pmc_article_html(cid, title=title)
    if html_hit.get("fulltext"):
        candidates.append((html_hit["fulltext"], html_hit))

    if not candidates:
        return

    text, meta = max(candidates, key=lambda row: len(row[0]))
    if len(text) > len(best.get("fulltext", "")):
        best["fulltext"] = text[:50000]
        best["source"] = meta.get("source") or "pmc_fulltext"
        best["source_url"] = meta.get("source_url") or best.get("source_url", "")


def _pubmed_id_for_doi(doi: str) -> str:
    q = urllib.parse.quote(f"{doi}[doi]")
    url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed&term={q}&retmode=json"
    raw = _http_text(url)
    if not raw:
        return ""
    try:
        data = json.loads(raw)
        ids = ((data.get("esearchresult") or {}).get("idlist") or [])
        return str(ids[0]) if ids else ""
    except json.JSONDecodeError:
        return ""


def fetch_pubmed_abstract(doi: str) -> Dict[str, str]:
    """Return abstract text and PubMed URL for a DOI, if indexed in PubMed."""
    doi = normalize_doi(doi)
    if not doi.startswith("10."):
        return {}
    pmid = _pubmed_id_for_doi(doi)
    if not pmid:
        return {}
    url = (
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
        f"?db=pubmed&id={urllib.parse.quote(pmid)}&rettype=abstract&retmode=text"
    )
    abstract = _http_text(url).strip()
    if not is_usable_paper_content(abstract):
        return {}
    return {
        "abstract": abstract[:15000],
        "source_url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
        "source": "pubmed",
    }


def fetch_europe_pmc_record(doi: str) -> Dict[str, str]:
    """Return abstract and optional full text from Europe PMC."""
    doi = normalize_doi(doi)
    if not doi.startswith("10."):
        return {}
    q = urllib.parse.quote(f"DOI:{doi}")
    url = f"https://www.ebi.ac.uk/europepmc/webservices/rest/search?query={q}&format=json&pageSize=1"
    raw = _http_text(url)
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    hits = ((data.get("resultList") or {}).get("result") or [])
    if not hits:
        return {}
    hit = hits[0]
    abstract = (hit.get("abstractText") or "").strip()
    pmcid = normalize_pmcid(hit.get("pmcid") or "")
    pmid = (hit.get("pmid") or "").strip()
    out: Dict[str, str] = {}
    if pmcid:
        out["pmcid"] = pmcid
        urls = pmc_article_urls(pmcid)
        out["pmc_html_url"] = urls.get("html") or ""
        out["pmc_pdf_url"] = urls.get("pdf") or ""
    if abstract and is_usable_paper_content(abstract):
        out["abstract"] = abstract[:15000]
        out["source"] = "europe_pmc"
        if pmcid:
            out["source_url"] = out.get("pmc_html_url") or f"https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/"
        elif pmid:
            out["source_url"] = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
    full_urls = hit.get("fullTextUrlList") or {}
    url_rows = full_urls.get("fullTextUrl") or []
    if isinstance(url_rows, dict):
        url_rows = [url_rows]
    for row in url_rows:
        if not isinstance(row, dict):
            continue
        if (row.get("availability") or "").upper() in ("OPEN_ACCESS", "FREE"):
            fetch_url = (row.get("url") or "").strip()
            if fetch_url:
                out["fulltext_url"] = fetch_url
                break
    return out


def _pmc_xml_text(pmcid: str) -> str:
    cid = (pmcid or "").strip()
    if not cid:
        return ""
    if not cid.upper().startswith("PMC"):
        cid = f"PMC{cid}"
    url = (
        "https://www.ncbi.nlm.nih.gov/research/bionlp/RESTful/"
        f"pmcoa.cgi/BioC_json/{urllib.parse.quote(cid, safe='')}/unicode"
    )
    raw = _http_text(url, timeout=30)
    if not raw:
        return ""
    try:
        docs = json.loads(raw).get("documents") or []
    except json.JSONDecodeError:
        return ""
    parts = []
    for doc in docs[:1]:
        for passage in doc.get("passages") or []:
            text = (passage.get("text") or "").strip()
            if text:
                parts.append(text)
    body = "\n\n".join(parts).strip()
    return body[:50000] if body else ""


def resolve_paper_content_by_doi(
    doi: str,
    *,
    title: str = "",
    fetch_fulltext: bool = True,
) -> Dict[str, str]:
    """Best-effort abstract/full text for a DOI via PubMed and Europe PMC."""
    doi = normalize_doi(doi)
    if not doi.startswith("10."):
        return {}

    best: Dict[str, str] = {}

    pubmed = fetch_pubmed_abstract(doi)
    if pubmed.get("abstract"):
        best.update(pubmed)

    epmc = fetch_europe_pmc_record(doi)
    if epmc.get("abstract") and len(epmc["abstract"]) > len(best.get("abstract", "")):
        best["abstract"] = epmc["abstract"]
        best["source"] = epmc.get("source") or "europe_pmc"
        if epmc.get("source_url"):
            best["source_url"] = epmc["source_url"]

    if fetch_fulltext:
        full_url = epmc.get("fulltext_url") or ""
        if full_url:
            page = _http_text(full_url, timeout=25)
            if is_usable_paper_content(page, title=title):
                best["fulltext"] = page[:50000]
                best["source_url"] = full_url
                best["source"] = "europe_pmc_fulltext"

        pmcid = epmc.get("pmcid") or ""
        if not pmcid:
            for src_url in (epmc.get("source_url"), best.get("source_url")):
                match = re.search(r"/articles/(PMC\d+)", src_url or "", re.I)
                if match:
                    pmcid = match.group(1)
                    break
        if not best.get("fulltext") and pmcid:
            _apply_pmc_fulltext(best, pmcid, title=title)

        if not best.get("fulltext"):
            _apply_doi_fulltext(best, doi, title=title)

    if not best.get("source_url"):
        urls = doi_urls(doi)
        if urls.get("html"):
            best["source_url"] = urls["html"]

    return best
