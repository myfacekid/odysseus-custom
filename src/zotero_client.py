"""Zotero Web API client for academic research integration.

Uses the Zotero cloud API so it works whether Nobody runs on a home desktop
(port-forwarded) or a laptop with a remote LLM — as long as the library syncs
to Zotero Cloud and the user supplies their API key + user ID.
"""
from __future__ import annotations

import io
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)

ZOTERO_API = "https://api.zotero.org"
ZOTERO_VERSION = "3"

# Common words stripped before sending long research questions to the Zotero API.
_SEARCH_STOPWORDS = frozenset({
    "about", "after", "also", "among", "analysis", "based", "been", "being",
    "between", "both", "could", "does", "each", "effect", "effects", "evidence",
    "from", "have", "include", "including", "into", "literature", "more",
    "most", "other", "review", "reviews", "should", "some", "such", "systematic",
    "than", "that", "their", "them", "then", "there", "these", "they", "this",
    "those", "through", "using", "what", "when", "where", "which", "while",
    "with", "would", "your",
})


def _extract_search_terms(query: str, max_terms: int = 5) -> str:
    """Reduce a long research question to a short Zotero search string."""
    q = (query or "").strip()
    if not q:
        return ""
    if len(q) <= 80 and q.count(" ") <= 8:
        return q
    tokens: List[str] = []
    for raw in re.split(r"\W+", q.lower()):
        if len(raw) <= 3 or raw in _SEARCH_STOPWORDS:
            continue
        if raw not in tokens:
            tokens.append(raw)
        if len(tokens) >= max_terms:
            break
    return " ".join(tokens) if tokens else q[:80]


def _title_matches_query(title: str, query: str) -> bool:
    """Loose title match — substring or enough overlapping keywords."""
    title_l = (title or "").lower()
    q_lower = (query or "").strip().lower()
    if not title_l or not q_lower:
        return False
    if q_lower in title_l or title_l in q_lower:
        return True
    q_tokens = [t for t in re.split(r"\W+", q_lower) if len(t) > 2]
    short_q = _extract_search_terms(q_lower)
    short_tokens = [t for t in short_q.split() if t]
    tokens = short_tokens or q_tokens
    if not tokens:
        return False
    hits = sum(1 for t in tokens if t in title_l)
    return hits >= max(1, min(2, len(tokens)))


def mask_api_key(key: str) -> str:
    key = (key or "").strip()
    if len(key) <= 4:
        return "****" if key else ""
    return key[:4] + "****"


def resolve_zotero_credentials(owner: str = "") -> Optional[Dict[str, str]]:
    """Load Zotero credentials: per-user prefs first, then global admin settings."""
    cfg: Dict[str, str] = {}
    if owner:
        try:
            from routes.prefs_routes import _load_for_user
            user_cfg = (_load_for_user(owner) or {}).get("zotero") or {}
            if isinstance(user_cfg, dict):
                cfg.update({k: str(v).strip() for k, v in user_cfg.items() if v})
        except Exception:
            pass
    if not cfg.get("api_key") or not cfg.get("user_id"):
        try:
            from src.settings import get_setting
            g_key = (get_setting("zotero_api_key") or "").strip()
            g_uid = (get_setting("zotero_user_id") or "").strip()
            if g_key and not cfg.get("api_key"):
                cfg["api_key"] = g_key
            if g_uid and not cfg.get("user_id"):
                cfg["user_id"] = g_uid
        except Exception:
            pass
    api_key = (cfg.get("api_key") or "").strip()
    user_id = (cfg.get("user_id") or "").strip()
    if not api_key or not user_id:
        return None
    return {"api_key": api_key, "user_id": user_id}


class ZoteroClient:
    """Minimal read/write client for a user's Zotero library."""

    def __init__(self, api_key: str, user_id: str):
        self.api_key = api_key.strip()
        self.user_id = str(user_id).strip()
        self._headers = {
            "Zotero-API-Key": self.api_key,
            "Zotero-API-Version": ZOTERO_VERSION,
        }

    def _url(self, path: str) -> str:
        return f"{ZOTERO_API}/users/{self.user_id}{path}"

    def test_connection(self) -> Tuple[bool, str, Optional[dict]]:
        """Verify credentials and return basic library info."""
        try:
            with httpx.Client(timeout=20, headers=self._headers) as client:
                r = client.get(self._url("/items/top"), params={"limit": 1})
                if r.status_code == 403:
                    return False, "Invalid API key or insufficient permissions", None
                if r.status_code == 404:
                    return False, "User ID not found — check your Zotero user ID", None
                r.raise_for_status()
                total_hdr = r.headers.get("Total-Results") or r.headers.get("total-results")
                try:
                    total = int(total_hdr) if total_hdr is not None else None
                except (TypeError, ValueError):
                    total = None
                items = r.json()
                sample = len(items) if isinstance(items, list) else 0
                if total is not None:
                    msg = f"Connected — {total} item{'s' if total != 1 else ''} in library"
                elif sample:
                    msg = f"Connected — library reachable ({sample}+ items)"
                else:
                    msg = "Connected — library is empty (add items in Zotero and sync to cloud)"
                return True, msg, {"total": total, "sample": sample}
        except httpx.HTTPError as e:
            return False, f"Connection failed: {e}", None

    def list_top_items(self, limit: int = 25) -> List[dict]:
        """List top-level library items (useful for small libraries)."""
        try:
            with httpx.Client(timeout=25, headers=self._headers) as client:
                r = client.get(self._url("/items/top"), params={"limit": min(max(limit, 1), 100)})
                r.raise_for_status()
                items = r.json()
                return items if isinstance(items, list) else []
        except httpx.HTTPError as e:
            logger.warning(f"Zotero list_top_items failed: {e}")
            return []

    def search_items(
        self,
        query: str,
        limit: int = 10,
        *,
        seed_library: bool = False,
    ) -> List[dict]:
        """Search the user's library (excludes attachments).

        seed_library: when True and nothing matches the query, return top-level
        items from small libraries so research can seed from the whole collection.
        """
        q = (query or "").strip()
        limit = min(max(limit, 1), 25)
        items: List[dict] = []
        search_q = _extract_search_terms(q) if q else ""

        if search_q:
            params = {"q": search_q, "limit": limit, "qmode": "everything"}
            try:
                with httpx.Client(timeout=12, headers=self._headers) as client:
                    r = client.get(self._url("/items"), params=params)
                    r.raise_for_status()
                    raw = r.json()
                    items = raw if isinstance(raw, list) else []
            except httpx.HTTPError as e:
                logger.warning(f"Zotero search failed for {search_q!r}: {e}")

        tops = self.list_top_items(max(limit * 3, 25)) if (not items or seed_library) else []

        # Local title match against top-level items (handles API misses/timeouts).
        if not items and q and tops:
            for item in tops:
                title = (item.get("data") or {}).get("title") or ""
                if _title_matches_query(title, q):
                    items.append(item)

        # Small library seed: include everything when the user asked to use their library.
        if not items and seed_library and tops:
            items = tops

        if not items and not q and tops:
            items = tops

        filtered = []
        for item in items:
            itype = (item.get("data") or {}).get("itemType") or ""
            if itype in ("attachment", "note", "annotation"):
                continue
            filtered.append(item)
        return filtered[:limit]

    def get_item(self, item_key: str) -> Optional[dict]:
        try:
            with httpx.Client(timeout=20, headers=self._headers) as client:
                r = client.get(self._url(f"/items/{item_key}"))
                if r.status_code == 404:
                    return None
                r.raise_for_status()
                return r.json()
        except httpx.HTTPError as e:
            logger.warning(f"Zotero get_item failed: {e}")
            return None

    def get_children(self, item_key: str) -> List[dict]:
        try:
            with httpx.Client(timeout=20, headers=self._headers) as client:
                r = client.get(self._url(f"/items/{item_key}/children"))
                r.raise_for_status()
                items = r.json()
                return items if isinstance(items, list) else []
        except httpx.HTTPError as e:
            logger.warning(f"Zotero get_children failed: {e}")
            return []

    def download_attachment_pdf(
        self,
        attachment_key: str,
        fallback_url: str = "",
        max_bytes: int = 8_000_000,
    ) -> str:
        """Download a PDF attachment and extract text.

        Tries Zotero's /file endpoint first (stored files). For linked PDFs
        (imported_url), falls back to fetching the attachment URL directly.
        """
        data = b""
        try:
            with httpx.Client(timeout=60, headers=self._headers, follow_redirects=True) as client:
                r = client.get(self._url(f"/items/{attachment_key}/file"))
                if r.status_code == 200 and r.content.startswith(b"%PDF"):
                    data = r.content
        except Exception as e:
            logger.warning(f"Zotero PDF download failed: {e}")

        if not data and (fallback_url or "").strip():
            try:
                with httpx.Client(timeout=60, follow_redirects=True) as client:
                    r = client.get(fallback_url.strip())
                    if r.status_code == 200 and r.content.startswith(b"%PDF"):
                        data = r.content
            except Exception as e:
                logger.warning(f"Zotero linked PDF fetch failed: {e}")

        if not data:
            return ""
        if len(data) > max_bytes:
            data = data[:max_bytes]
        return _extract_pdf_text(data)

    def create_items(self, items: List[dict]) -> Tuple[int, Optional[str]]:
        """Create up to 50 items in the library. Returns (created_count, error)."""
        if not items:
            return 0, None
        batch = items[:50]
        try:
            with httpx.Client(
                timeout=30,
                headers={**self._headers, "Content-Type": "application/json"},
            ) as client:
                r = client.post(self._url("/items"), json=batch)
                if r.status_code not in (200, 201):
                    return 0, f"HTTP {r.status_code}: {r.text[:200]}"
                body = r.json()
                if isinstance(body, dict) and body.get("successful"):
                    return len(body["successful"]), None
                if isinstance(body, list):
                    return len(body), None
                return len(batch), None
        except httpx.HTTPError as e:
            return 0, str(e)


def _extract_pdf_text(data: bytes, max_chars: int = 15000) -> str:
    """Extract text from PDF bytes. Uses pypdf (required); pdfminer as fallback."""
    if not data or not data.startswith(b"%PDF"):
        return ""
    text = ""
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data))
        parts = []
        for page in reader.pages:
            parts.append(page.extract_text() or "")
        text = "\n".join(parts).strip()
    except Exception as e:
        logger.warning(f"pypdf extraction failed: {e}")
    if not text:
        try:
            from pdfminer.high_level import extract_text
            text = (extract_text(io.BytesIO(data)) or "").strip()
        except Exception as e:
            logger.warning(f"PDF text extraction failed: {e}")
    if len(text) > max_chars:
        text = text[:max_chars] + "\n[PDF content truncated]"
    return text


def _is_pdf_attachment(cdata: dict) -> bool:
    if (cdata.get("contentType") or "").lower() == "application/pdf":
        return True
    filename = (cdata.get("filename") or "").lower()
    if "pdf" in filename and cdata.get("itemType") == "attachment":
        return True
    url = (cdata.get("url") or "").lower()
    return url.endswith(".pdf")


def _format_authors(creators: List[dict]) -> str:
    parts = []
    for c in creators or []:
        last = (c.get("lastName") or "").strip()
        first = (c.get("firstName") or "").strip()
        if last and first:
            parts.append(f"{last}, {first}")
        elif last or first:
            parts.append(last or first)
    return "; ".join(parts[:6])


def _item_type_label(item_type: str) -> str:
    mapping = {
        "journalArticle": "journal article",
        "conferencePaper": "conference paper",
        "preprint": "preprint",
        "report": "report",
        "book": "book",
        "bookSection": "book chapter",
        "thesis": "thesis",
    }
    return mapping.get(item_type or "", item_type or "unknown")


def _peer_status(item_type: str) -> str:
    if item_type in ("preprint",):
        return "preprint"
    if item_type in ("journalArticle", "conferencePaper", "report", "thesis"):
        return "peer_reviewed"
    return "unknown"


def zotero_item_to_finding(item: dict, user_id: str, pdf_text: str = "") -> dict:
    """Convert a Zotero API item into a research finding dict."""
    data = item.get("data") or {}
    key = item.get("key") or data.get("key") or ""
    title = data.get("title") or "Untitled"
    authors = _format_authors(data.get("creators") or [])
    year_match = re.search(r"\d{4}", str(data.get("date") or ""))
    year = year_match.group(0) if year_match else ""
    doi = (data.get("DOI") or "").strip()
    abstract = (data.get("abstractNote") or "").strip()
    item_type = data.get("itemType") or ""
    url = doi if doi.startswith("http") else (f"https://doi.org/{doi}" if doi else f"https://www.zotero.org/users/{user_id}/items/{key}")

    evidence_parts = []
    if abstract:
        evidence_parts.append(abstract)
    if pdf_text:
        evidence_parts.append(pdf_text)
    if not evidence_parts:
        extra = (data.get("extra") or data.get("url") or "").strip()
        if extra:
            evidence_parts.append(extra)
    evidence = "\n\n".join(evidence_parts)[:15000]

    summary = abstract[:2000] if abstract else (evidence[:800] if evidence else f"Zotero library item: {title}")

    return {
        "url": url,
        "title": title,
        "rational": "Matched item from the user's Zotero library (cloud-synced)",
        "evidence": evidence,
        "summary": summary,
        "authors": authors,
        "year": year,
        "doi_or_id": doi or key,
        "study_type": _item_type_label(item_type),
        "peer_review_status": _peer_status(item_type),
        "source_type": "zotero",
        "zotero_key": key,
    }


def fetch_zotero_findings(
    query: str,
    owner: str = "",
    limit: int = 5,
    extract_pdfs: bool = True,
    seed_library: bool = False,
) -> List[dict]:
    """Search Zotero and return findings ready for the research pipeline."""
    creds = resolve_zotero_credentials(owner)
    if not creds:
        return []

    client = ZoteroClient(creds["api_key"], creds["user_id"])
    items = client.search_items(query, limit=limit, seed_library=seed_library)
    findings: List[dict] = []

    for item in items:
        key = item.get("key") or (item.get("data") or {}).get("key")
        if not key:
            continue
        full = client.get_item(key) or item
        pdf_text = ""
        if extract_pdfs:
            for child in client.get_children(key):
                cdata = child.get("data") or {}
                if not _is_pdf_attachment(cdata):
                    continue
                ck = child.get("key") or cdata.get("key")
                if ck:
                    pdf_text = client.download_attachment_pdf(
                        ck, fallback_url=cdata.get("url") or "",
                    )
                    if pdf_text:
                        break
        findings.append(zotero_item_to_finding(full, creds["user_id"], pdf_text=pdf_text))

    return findings


def sources_to_zotero_items(sources: List[dict]) -> List[dict]:
    """Build Zotero item payloads from research source dicts."""
    payloads = []
    for s in sources or []:
        url = (s.get("url") or "").strip()
        title = (s.get("title") or url or "Untitled source").strip()
        if not url and not title:
            continue
        item: Dict[str, Any] = {
            "itemType": "journalArticle",
            "title": title[:500],
        }
        if url:
            item["url"] = url
            doi_match = re.search(r"10\.\d{4,9}/[^\s]+", url)
            if doi_match:
                item["DOI"] = doi_match.group(0).rstrip(").,")
        payloads.append(item)
    return payloads
