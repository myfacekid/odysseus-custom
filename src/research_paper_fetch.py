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

_USER_AGENT = "Odysseus-DeepResearch/1.0 (mailto:support@example.com)"
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
    out: Dict[str, str] = {}
    if abstract and is_usable_paper_content(abstract):
        out["abstract"] = abstract[:15000]
        out["source"] = "europe_pmc"
        pmid = (hit.get("pmid") or "").strip()
        pmcid = (hit.get("pmcid") or "").strip()
        if pmcid:
            out["source_url"] = f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/"
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
        pmcid_match = re.search(r"/pmc/articles/(PMC\d+)", best.get("source_url", ""), re.I)
        if not best.get("fulltext") and pmcid_match:
            pmc_text = _pmc_xml_text(pmcid_match.group(1))
            if is_usable_paper_content(pmc_text, title=title):
                best["fulltext"] = pmc_text
                best["source"] = "pmc_fulltext"

    return best
