"""LDR Phase L6 — goal-directed HTML/PDF fetch for non-DOI scholarly URLs."""
from __future__ import annotations

import logging
import re
from typing import Dict, List
from urllib.parse import urlparse

from src.research_paper_fetch import is_usable_paper_content
from src.research_web_search import is_scholar_author_profile_url

logger = logging.getLogger(__name__)

# Hosts worth fetching when LDR left only a landing-page URL (no DOI resolved yet).
_SCHOLARLY_HOST_FRAGMENTS = (
    "arxiv.org",
    "pubmed.ncbi.nlm.nih.gov",
    "ncbi.nlm.nih.gov/pmc",
    "pmc.ncbi.nlm.nih.gov",
    "semanticscholar.org",
    "nature.com/articles",
    "science.org/doi",
    "cell.com",
    "elifesciences.org",
    "frontiersin.org",
    "mdpi.com",
    "plos.org",
    "biomedcentral.com",
    "wiley.com/doi",
    "springer.com",
    "academic.oup.com",
)

_SKIP_HOST_FRAGMENTS = (
    "google.com",
    "duckduckgo.com",
    "wikipedia.org",
    "youtube.com",
    "twitter.com",
    "x.com",
    "linkedin.com",
    "researchgate.net/profile",
    "orcid.org",
)


def is_enrichable_scholarly_url(url: str) -> bool:
    """True when a URL is worth a goal-directed fetch (non-DOI landing pages)."""
    raw = (url or "").strip()
    if not raw.startswith("http"):
        return False
    if is_scholar_author_profile_url(raw):
        return False
    lower = raw.lower()
    if any(skip in lower for skip in _SKIP_HOST_FRAGMENTS):
        return False
    if "doi.org/" in lower:
        return False
    return any(host in lower for host in _SCHOLARLY_HOST_FRAGMENTS)


def scholarly_url_candidates(url: str) -> List[str]:
    """Expand known landing URLs into fetch targets (e.g. arXiv abs → HTML/PDF)."""
    raw = (url or "").strip()
    if not raw:
        return []
    out: List[str] = []
    seen: set[str] = set()

    def _add(candidate: str) -> None:
        c = (candidate or "").strip()
        if c and c not in seen:
            seen.add(c)
            out.append(c)

    _add(raw)

    arxiv = re.search(r"arxiv\.org/abs/(\d{4}\.\d{4,5})(?:v\d+)?", raw, re.I)
    if arxiv:
        aid = arxiv.group(1)
        _add(f"https://arxiv.org/html/{aid}")
        _add(f"https://arxiv.org/pdf/{aid}.pdf")

    pmc = re.search(r"pubmed\.ncbi\.nlm\.nih\.gov/(\d+)", raw, re.I)
    if pmc:
        _add(f"https://pmc.ncbi.nlm.nih.gov/articles/PMC{pmc.group(1)}/")

    return out


def fetch_url_article_text(
    url: str,
    *,
    title: str = "",
    max_chars: int = 15000,
) -> Dict[str, str]:
    """Fetch article text from a scholarly URL (HTML or PDF)."""
    if not is_enrichable_scholarly_url(url):
        return {}

    for candidate in scholarly_url_candidates(url):
        try:
            if candidate.lower().endswith(".pdf") or "/pdf/" in candidate.lower():
                from src.research_paper_fetch import fetch_pdf_text_from_url

                text = fetch_pdf_text_from_url(candidate, max_chars=max_chars)
                if is_usable_paper_content(text, title=title):
                    return {
                        "text": text[:max_chars],
                        "source": "url_pdf",
                        "source_url": candidate,
                    }
                continue

            from src.search.content import fetch_webpage_content

            page = fetch_webpage_content(candidate, timeout=18, include_og_image=False)
            content = (page.get("content") or "").strip()
            ctype = (page.get("content_type") or "").lower() if isinstance(page, dict) else ""
            if page.get("success") and "pdf" in ctype and content:
                pass
            elif page.get("success") and is_usable_paper_content(content, title=title):
                return {
                    "text": content[:max_chars],
                    "source": "url_html",
                    "source_url": page.get("url") or candidate,
                }
        except Exception as exc:
            logger.info("URL article fetch failed (%s): %s", candidate[:80], exc)
            continue
    return {}


def enrich_finding_from_url(
    finding: dict,
    *,
    max_chars: int = 8000,
    as_fulltext: bool = False,
) -> bool:
    """Enrich a thin finding from its URL when no DOI ladder applied."""
    from src.research.ldr_doi import finding_text_richness
    from src.research.ldr_content_enrich import _apply_resolved_text
    from src.research_evidence import doi_from_finding

    if doi_from_finding(finding).startswith("10."):
        return False
    url = (finding.get("url") or "").strip()
    if not is_enrichable_scholarly_url(url):
        return False
    if finding_text_richness(finding) >= 900 and finding.get("abstract"):
        return False

    hit = fetch_url_article_text(
        url,
        title=(finding.get("title") or "").strip(),
        max_chars=max_chars,
    )
    text = (hit.get("text") or "").strip()
    if not text:
        return False

    use_fulltext = as_fulltext or len(text) >= 900
    _apply_resolved_text(
        finding,
        text,
        source=hit.get("source") or "url_html",
        source_url=hit.get("source_url") or url,
        max_chars=max_chars,
        as_fulltext=use_fulltext,
    )
    return True
