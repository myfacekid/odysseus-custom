"""Zotero Web API client for academic research integration.

Uses the Zotero cloud API so it works whether Nobody runs on a home desktop
(port-forwarded) or a laptop with a remote LLM — as long as the library syncs
to Zotero Cloud and the user supplies their API key + user ID.
"""
from __future__ import annotations

import io
import logging
import re
from contextvars import ContextVar
from dataclasses import dataclass
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


_BROAD_LIBRARY_QUERIES = frozenset({
    "library", "libraries", "paper", "papers", "publication", "publications",
    "article", "articles", "source", "sources", "citation", "citations",
    "everything", "anything", "all", "items", "saved", "zotero", "collection",
    "collections", "reading", "references", "reference", "my work",
})


def _is_broad_library_query(query: str) -> bool:
    """True when the user is asking to browse the library, not keyword-search it."""
    q = (query or "").strip().lower()
    if not q:
        return True
    tokens = [t for t in re.split(r"\W+", q) if t]
    if not tokens:
        return True
    if len(tokens) <= 3 and all(t in _BROAD_LIBRARY_QUERIES for t in tokens):
        return True
    return q in _BROAD_LIBRARY_QUERIES


def _is_bibliographic_item(item: dict) -> bool:
    itype = (item.get("data") or {}).get("itemType") or ""
    return itype not in ("attachment", "note", "annotation")


def _filter_bibliographic(items: List[dict], limit: int) -> List[dict]:
    out: List[dict] = []
    for item in items or []:
        if not _is_bibliographic_item(item):
            continue
        out.append(item)
        if len(out) >= limit:
            break
    return out


def _item_display_title(item: dict) -> str:
    data = item.get("data") or {}
    title = (data.get("title") or "").strip()
    if title:
        return title
    filename = (data.get("filename") or "").strip()
    if filename:
        return filename
    url = (data.get("url") or "").strip()
    if url:
        return url[:200]
    itype = (data.get("itemType") or "item").strip()
    return f"Untitled ({itype})"


def _normalize_searchable_item(item: dict) -> Optional[dict]:
    """Make bibliographic entries and standalone PDFs/notes searchable."""
    if not item:
        return None
    data = dict(item.get("data") or {})
    itype = data.get("itemType") or ""
    if _is_bibliographic_item(item):
        return item
    if itype == "attachment":
        if not (_is_pdf_attachment(data) or (data.get("filename") or "").strip()):
            return None
        if not (data.get("title") or "").strip():
            data = {**data, "title": _item_display_title(item)}
        return {**item, "data": data}
    if itype == "note":
        note_text = (data.get("note") or "").strip()
        if not note_text:
            return None
        first_line = note_text.split("\n", 1)[0].strip() or "Note"
        data = {
            **data,
            "title": (data.get("title") or first_line)[:200],
            "abstractNote": note_text[:2000],
        }
        return {**item, "data": data}
    return None


def _expand_searchable_items(items: List[dict], limit: int) -> List[dict]:
    out: List[dict] = []
    for item in items or []:
        norm = _normalize_searchable_item(item)
        if not norm:
            continue
        out.append(norm)
        if len(out) >= limit:
            break
    return out


def _summarize_top_level_items(items: List[dict], limit: int = 8) -> str:
    if not items:
        return "No top-level entries returned by the Zotero API."
    lines = ["Top-level entries in your library:"]
    for item in items[:limit]:
        data = item.get("data") or {}
        key = item.get("key") or "?"
        itype = data.get("itemType") or "?"
        lines.append(f"- [{itype}] {_item_display_title(item)} (key: {key})")
    searchable = _expand_searchable_items(items, limit)
    if items and not searchable:
        lines.append(
            "These look like attachments or notes without bibliographic metadata. "
            "In Zotero, right-click a standalone PDF and choose “Create Parent Item”, then sync again."
        )
    return "\n".join(lines)


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
                r = client.get(self._url("/items/top"), params={"limit": 25})
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
                tops = r.json()
                tops = tops if isinstance(tops, list) else []
                searchable = _expand_searchable_items(tops, 25)
                if searchable:
                    n = len(searchable)
                    msg = f"Connected — {n} searchable item{'s' if n != 1 else ''} in library"
                elif tops:
                    types: Dict[str, int] = {}
                    for item in tops:
                        t = (item.get("data") or {}).get("itemType") or "item"
                        types[t] = types.get(t, 0) + 1
                    type_bits = ", ".join(f"{count} {name}" for name, count in sorted(types.items()))
                    msg = (
                        f"Connected — {total or len(tops)} top-level "
                        f"entr{'y' if (total or len(tops)) == 1 else 'ies'} ({type_bits}); "
                        "no bibliographic papers indexed yet"
                    )
                elif total:
                    msg = f"Connected — {total} top-level entr{'y' if total == 1 else 'ies'} in library"
                else:
                    msg = "Connected — library is empty (add items in Zotero and sync to cloud)"
                return True, msg, {
                    "total": total,
                    "top_level": len(tops),
                    "searchable": len(searchable),
                }
        except httpx.HTTPError as e:
            return False, f"Connection failed: {e}", None

    def list_recent_items(self, limit: int = 50, start: int = 0) -> List[dict]:
        """List recent library entries, including standalone attachments."""
        limit = min(max(limit, 1), 100)
        start = max(start, 0)
        params: List[Tuple[str, str]] = [
            ("limit", str(limit)),
            ("start", str(start)),
            ("sort", "dateAdded"),
            ("direction", "desc"),
        ]
        try:
            with httpx.Client(timeout=25, headers=self._headers) as client:
                r = client.get(self._url("/items"), params=params)
                r.raise_for_status()
                raw = r.json()
                items = raw if isinstance(raw, list) else []
                return _expand_searchable_items(items, limit)
        except httpx.HTTPError as e:
            logger.warning(f"Zotero list_recent_items failed: {e}")
            return []

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

    def list_bibliographic_items(self, limit: int = 50, start: int = 0) -> List[dict]:
        """List bibliographic items anywhere in the library (not just top-level)."""
        limit = min(max(limit, 1), 100)
        start = max(start, 0)
        params: List[Tuple[str, str]] = [
            ("limit", str(limit)),
            ("start", str(start)),
            ("itemType", "-attachment"),
            ("itemType", "-note"),
            ("itemType", "-annotation"),
            ("sort", "dateAdded"),
            ("direction", "desc"),
        ]
        try:
            with httpx.Client(timeout=25, headers=self._headers) as client:
                r = client.get(self._url("/items"), params=params)
                r.raise_for_status()
                raw = r.json()
                items = raw if isinstance(raw, list) else []
                return _filter_bibliographic(items, limit)
        except httpx.HTTPError as e:
            logger.warning(f"Zotero list_bibliographic_items failed: {e}")
            return []

    def search_items(
        self,
        query: str,
        limit: int = 10,
        *,
        seed_library: bool = False,
        start: int = 0,
    ) -> List[dict]:
        """Search the user's library (excludes attachments).

        seed_library: when True and nothing matches the query, return recent
        bibliographic items from small libraries so a single saved paper still
        surfaces even if the Zotero API search misses it.
        """
        q = (query or "").strip()
        limit = min(max(limit, 1), 25)
        start = max(start, 0)
        items: List[dict] = []
        search_q = _extract_search_terms(q) if q else ""

        if search_q:
            params = {
                "q": search_q,
                "limit": limit,
                "qmode": "everything",
                "start": start,
                "itemType": "-attachment",
            }
            try:
                with httpx.Client(timeout=12, headers=self._headers) as client:
                    r = client.get(self._url("/items"), params=params)
                    r.raise_for_status()
                    raw = r.json()
                    items = raw if isinstance(raw, list) else []
            except httpx.HTTPError as e:
                logger.warning(f"Zotero search failed for {search_q!r}: {e}")
            if not items:
                # titleCreatorYear often finds items the full-text index missed.
                try:
                    with httpx.Client(timeout=12, headers=self._headers) as client:
                        r = client.get(
                            self._url("/items"),
                            params={**params, "qmode": "titleCreatorYear"},
                        )
                        r.raise_for_status()
                        raw = r.json()
                        items = raw if isinstance(raw, list) else []
                except httpx.HTTPError as e:
                    logger.warning(f"Zotero title search failed for {search_q!r}: {e}")

        browse_pool: List[dict] = []
        if not items or seed_library or q:
            browse_pool = self.list_recent_items(limit=max(limit * 4, 50), start=0)
            if not browse_pool:
                browse_pool = _expand_searchable_items(
                    self.list_top_items(max(limit * 3, 25)),
                    max(limit * 4, 50),
                )

        # Local title match against recent items (handles API misses
        # and items stored only inside collections).
        if not items and q and browse_pool:
            for item in browse_pool:
                title = _item_display_title(item)
                if _title_matches_query(title, q):
                    items.append(item)

        # Small-library seed / broad browse requests.
        if not items and browse_pool and _is_broad_library_query(q):
            items = browse_pool
        elif not items and seed_library and browse_pool:
            if len(browse_pool) <= max(limit, 12):
                items = browse_pool

        if not items and not q and browse_pool:
            items = browse_pool

        if not items and not q:
            items = self.list_recent_items(limit=max(limit * 3, 25), start=start)
            if not items:
                items = _expand_searchable_items(
                    self.list_top_items(max(limit * 3, 25)),
                    limit,
                )

        return _expand_searchable_items(items, limit)[:limit]

    def list_collections(self) -> List[dict]:
        """Return all collections with human-readable paths."""
        try:
            with httpx.Client(timeout=20, headers=self._headers) as client:
                r = client.get(self._url("/collections"))
                r.raise_for_status()
                raw = r.json()
                rows = raw if isinstance(raw, list) else []
        except httpx.HTTPError as e:
            logger.warning(f"Zotero list_collections failed: {e}")
            return []

        by_key = {row.get("key"): row for row in rows if row.get("key")}

        def _path_for(key: str) -> str:
            parts: List[str] = []
            current = by_key.get(key)
            seen = set()
            while current and current.get("key") not in seen:
                seen.add(current.get("key"))
                data = current.get("data") or {}
                parts.insert(0, (data.get("name") or "Untitled").strip())
                parent = (data.get("parentCollection") or "").strip()
                current = by_key.get(parent) if parent else None
            return " / ".join(parts) if parts else "Untitled"

        out: List[dict] = []
        for row in rows:
            key = row.get("key") or ""
            data = row.get("data") or {}
            if not key:
                continue
            out.append({
                "key": key,
                "name": (data.get("name") or "Untitled").strip(),
                "path": _path_for(key),
                "parent": (data.get("parentCollection") or "").strip(),
            })
        return out

    @staticmethod
    def collection_subtree_keys(root_key: str, collections: List[dict]) -> List[str]:
        """Return root_key plus all descendant collection keys."""
        children_by_parent: Dict[str, List[str]] = {}
        for col in collections or []:
            parent = (col.get("parent") or "").strip()
            key = (col.get("key") or "").strip()
            if parent and key:
                children_by_parent.setdefault(parent, []).append(key)

        keys: List[str] = []
        stack = [root_key]
        seen = set()
        while stack:
            key = stack.pop()
            if not key or key in seen:
                continue
            seen.add(key)
            keys.append(key)
            stack.extend(children_by_parent.get(key, []))
        return keys

    def get_collection_items(
        self,
        collection_key: str,
        query: str = "",
        limit: int = 10,
        start: int = 0,
    ) -> List[dict]:
        """Search or list items in one collection (direct members only)."""
        limit = min(max(limit, 1), 100)
        start = max(start, 0)
        search_q = _extract_search_terms(query) if (query or "").strip() else ""

        def _fetch(q_param: str = "", qmode: str = "everything") -> List[dict]:
            params: Dict[str, Any] = {
                "limit": limit,
                "start": start,
            }
            if q_param:
                params["q"] = q_param
                params["qmode"] = qmode
                params["itemType"] = "-attachment"
            try:
                with httpx.Client(timeout=20, headers=self._headers) as client:
                    r = client.get(
                        self._url(f"/collections/{collection_key}/items"),
                        params=params,
                    )
                    r.raise_for_status()
                    items = r.json()
                    raw = items if isinstance(items, list) else []
                    if q_param:
                        return _filter_bibliographic(raw, limit)
                    return _expand_searchable_items(raw, limit)
            except httpx.HTTPError as e:
                logger.warning(f"Zotero get_collection_items failed for {collection_key}: {e}")
                return []

        items = _fetch(search_q) if search_q else _fetch()
        if not items and search_q:
            items = _fetch(search_q, qmode="titleCreatorYear")
        if not items and search_q:
            pool = _fetch()
            for item in pool:
                if _title_matches_query(_item_display_title(item), query):
                    items.append(item)
                    if len(items) >= limit:
                        break
        if not items and _is_broad_library_query(query):
            items = _fetch()
        return items[:limit]

    def search_scoped(
        self,
        query: str = "",
        limit: int = 10,
        start: int = 0,
        collection_keys: Optional[List[str]] = None,
        *,
        seed_library: bool = False,
    ) -> List[dict]:
        """Search library-wide or within one/more collections (incl. subfolders)."""
        limit = min(max(limit, 1), 25)
        start = max(start, 0)
        need = start + limit

        if not collection_keys:
            return self.search_items(
                query, limit=need, start=start, seed_library=seed_library,
            )[:limit]

        seen: set = set()
        merged: List[dict] = []
        per_col = min(max(need, 10), 100)
        for ck in collection_keys:
            batch = self.get_collection_items(ck, query, limit=per_col, start=0)
            for item in batch:
                key = item.get("key") or (item.get("data") or {}).get("key")
                if not key or key in seen:
                    continue
                seen.add(key)
                merged.append(item)
                if len(merged) >= need:
                    break
            if len(merged) >= need:
                break
        if not merged and seed_library and collection_keys:
            for ck in collection_keys:
                batch = self.get_collection_items(ck, "", limit=per_col, start=0)
                for item in batch:
                    key = item.get("key") or (item.get("data") or {}).get("key")
                    if not key or key in seen:
                        continue
                    seen.add(key)
                    merged.append(item)
                    if len(merged) >= need:
                        break
                if len(merged) >= need:
                    break
        return merged[start:start + limit]

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
        max_bytes: int = 16_000_000,
        *,
        max_extract_chars: int = 15000,
    ) -> str:
        """Download a PDF attachment and extract text.

        Tries Zotero's /file endpoint first (stored files). For linked PDFs
        (imported_url), falls back to fetching the attachment URL directly.
        """
        meta = self.get_item(attachment_key)
        adata = (meta or {}).get("data") or {}
        fallback_url = (fallback_url or adata.get("url") or "").strip()
        link_mode = (adata.get("linkMode") or "").strip()

        if link_mode == "linked_file":
            logger.info(
                f"Zotero attachment {attachment_key} is linked_file (local path only) — "
                "cloud API cannot fetch the file; sync the PDF to Zotero Cloud or use imported_file."
            )
            return ""

        def _download(url: str, *, use_api_headers: bool) -> bytes:
            if not url:
                return b""
            try:
                headers = self._headers if use_api_headers else {
                    "User-Agent": "Nobody/1.0 (Zotero research integration; +https://github.com/)",
                    "Accept": "application/pdf,*/*",
                }
                with httpx.Client(timeout=60, follow_redirects=True, headers=headers) as client:
                    r = client.get(url.strip())
                    if r.status_code == 200 and r.content:
                        ctype = (r.headers.get("content-type") or "").lower()
                        if r.content.startswith(b"%PDF") or "pdf" in ctype:
                            return r.content
            except Exception as e:
                logger.warning(f"Zotero PDF download failed ({url[:80]}): {e}")
            return b""

        candidates: List[Tuple[str, bool]] = []
        if link_mode in ("imported_file", "imported_url", "linked_url", ""):
            candidates.append((self._url(f"/items/{attachment_key}/file"), True))
        if fallback_url:
            candidates.append((fallback_url, False))

        seen_urls: set[str] = set()
        for url, use_api in candidates:
            if url in seen_urls:
                continue
            seen_urls.add(url)
            data = _download(url, use_api_headers=use_api)
            if not data:
                continue
            if len(data) > max_bytes:
                logger.info(
                    "Zotero PDF %s is %d bytes; extracting text before truncation",
                    attachment_key,
                    len(data),
                )
            text = _extract_pdf_text(data, max_chars=max_extract_chars)
            if text:
                return text
            logger.info(
                "PDF bytes fetched for %s (%d bytes) but text extraction failed; trying next source",
                attachment_key,
                len(data),
            )

        return ""

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


def collapse_extracted_pdf_text(text: str) -> str:
    """Join visual PDF line breaks into paragraphs; keep blank-line breaks."""
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return ""
    paragraphs = re.split(r"\n\s*\n", text)
    collapsed = []
    for para in paragraphs:
        line = re.sub(r"[ \t]*\n[ \t]*", " ", para)
        line = re.sub(r" {2,}", " ", line).strip()
        if line:
            collapsed.append(line)
    return "\n\n".join(collapsed)


def _extract_pdf_text(data: bytes, max_chars: int = 15000) -> str:
    """Extract text from PDF bytes. Uses pypdf (required); pdfminer as fallback."""
    if not data or not data.startswith(b"%PDF"):
        return ""
    text = ""
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data), strict=False)
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
    text = collapse_extracted_pdf_text(text)
    if len(text) > max_chars:
        text = text[:max_chars] + "\n[PDF content truncated]"
    return text


def _url_looks_like_pdf(url: str) -> bool:
    u = (url or "").strip().lower().split("?")[0].split("#")[0]
    if not u:
        return False
    if u.endswith(".pdf") or u.endswith("/pdf"):
        return True
    if "/pdf/" in u or "arxiv.org/pdf" in u:
        return True
    return False


def _is_pdf_attachment(cdata: dict) -> bool:
    if (cdata.get("itemType") or "") != "attachment":
        return False
    ct = (cdata.get("contentType") or "").lower()
    if ct in ("application/pdf", "application/x-pdf", "application/vnd.pdf"):
        return True
    if "pdf" in ct:
        return True
    for field in ("filename", "path"):
        val = (cdata.get(field) or "").lower()
        if val.endswith(".pdf") or (val and "pdf" in val):
            return True
    if _url_looks_like_pdf(cdata.get("url") or ""):
        return True
    link_mode = (cdata.get("linkMode") or "").strip()
    title = (cdata.get("title") or "").strip()
    if link_mode in ("imported_file", "linked_file", "imported_url", "linked_url"):
        if _generic_pdf_title(title):
            return True
        if (cdata.get("filename") or cdata.get("path") or "").strip():
            return link_mode in ("imported_file", "linked_file") and bool(
                (cdata.get("filename") or cdata.get("path") or "").lower().endswith(".pdf")
                or _generic_pdf_title(title)
            )
    return False


def _attachment_parent_key(data: dict) -> str:
    return (data.get("parentItem") or "").strip()


def _generic_pdf_title(title: str) -> bool:
    t = (title or "").strip().lower()
    return t in ("full text pdf", "full text", "pdf", "article pdf", "manuscript pdf")


def _pdf_attachment_rank(item: dict) -> tuple:
    """Prefer stored files over linked URLs when picking a child PDF."""
    data = item.get("data") or {}
    mode = (data.get("linkMode") or "").strip()
    mode_rank = {
        "imported_file": 0,
        "imported_url": 1,
        "linked_url": 2,
        "linked_file": 3,
    }.get(mode, 9)
    title = (data.get("title") or "").lower()
    generic = 1 if _generic_pdf_title(title) else 0
    return (mode_rank, generic, title)


def _pick_best_pdf_attachment(attachments: List[dict]) -> Optional[dict]:
    pdfs = [a for a in attachments or [] if _is_pdf_attachment((a.get("data") or {}))]
    if not pdfs:
        return None
    return min(pdfs, key=_pdf_attachment_rank)


def list_pdf_attachments_by_parent(client: "ZoteroClient", *, max_attachments: int = 20000) -> Dict[str, List[dict]]:
    """Fetch all PDF attachments and index them by parentItem key."""
    pdfs_by_parent: Dict[str, List[dict]] = {}
    start = 0
    page = 100
    seen = 0

    while seen < max_attachments:
        try:
            params = [
                ("limit", str(page)),
                ("start", str(start)),
                ("itemType", "attachment"),
                ("sort", "dateModified"),
                ("direction", "desc"),
            ]
            with httpx.Client(timeout=30, headers=client._headers) as http:
                r = http.get(client._url("/items"), params=params)
                r.raise_for_status()
                batch = r.json()
        except httpx.HTTPError as e:
            logger.warning(f"Zotero attachment scan failed at start={start}: {e}")
            break

        if not isinstance(batch, list) or not batch:
            break

        for item in batch:
            data = item.get("data") or {}
            if not _is_pdf_attachment(data):
                continue
            parent = _attachment_parent_key(data)
            if not parent:
                continue
            pdfs_by_parent.setdefault(parent, []).append(item)
            seen += 1
            if seen >= max_attachments:
                break

        if len(batch) < page:
            break
        start += page

    return pdfs_by_parent


def enrich_pdf_attachments_from_children(
    client: "ZoteroClient",
    bibliographic: List[dict],
    pdfs_by_parent: Dict[str, List[dict]],
) -> None:
    """Fill gaps where the flat attachment scan missed child PDFs."""
    for item in bibliographic or []:
        key = (item.get("key") or (item.get("data") or {}).get("key") or "").strip()
        if not key or pdfs_by_parent.get(key):
            continue
        for child in client.get_children(key):
            cdata = child.get("data") or {}
            if not _is_pdf_attachment(cdata):
                continue
            pdfs_by_parent.setdefault(key, []).append(child)


def _pdf_attachment_keys_for_item(
    client: "ZoteroClient",
    item_key: str,
    full_item: Optional[dict] = None,
    *,
    catalog_row: Optional[dict] = None,
) -> List[Tuple[str, str]]:
    """Return [(attachment_key, fallback_url), ...] to try for PDF text extraction."""
    attachment_items: List[dict] = []
    seen: set[str] = set()

    def add_item(att: dict) -> None:
        key = (att.get("key") or (att.get("data") or {}).get("key") or "").strip()
        if not key or key in seen:
            return
        seen.add(key)
        attachment_items.append(att)

    if catalog_row and catalog_row.get("pdf_attachment_key"):
        add_item({"key": catalog_row["pdf_attachment_key"], "data": {}})

    full = full_item or client.get_item(item_key) or {}
    full_data = full.get("data") or {}
    if _is_pdf_attachment(full_data):
        add_item(full)

    for child in client.get_children(item_key):
        cdata = child.get("data") or {}
        if _is_pdf_attachment(cdata):
            add_item(child)

    attachment_items.sort(key=_pdf_attachment_rank)
    out: List[Tuple[str, str]] = []
    for att in attachment_items:
        cdata = att.get("data") or {}
        key = att.get("key") or cdata.get("key") or ""
        out.append((key, (cdata.get("url") or "").strip()))
    return out


def _extract_pdf_text_for_item(
    client: "ZoteroClient",
    item_key: str,
    full_item: Optional[dict] = None,
    *,
    catalog_row: Optional[dict] = None,
    max_extract_chars: int = 15000,
) -> str:
    for ck, fallback_url in _pdf_attachment_keys_for_item(
        client, item_key, full_item, catalog_row=catalog_row,
    ):
        text = client.download_attachment_pdf(
            ck, fallback_url=fallback_url, max_extract_chars=max_extract_chars,
        )
        if text:
            return text
    return ""


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
        "attachment": "pdf attachment",
        "note": "note",
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
    title = _item_display_title(item)
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


@dataclass
class ZoteroSearchRequest:
    """Per-request Zotero search flag (set from the chat composer toggle)."""
    enabled: bool = False
    owner: str = ""


_zotero_search_ctx: ContextVar[ZoteroSearchRequest] = ContextVar(
    "zotero_search_request", default=ZoteroSearchRequest(),
)


def set_zotero_search_request(enabled: bool, owner: str = "") -> None:
    """Enable or disable Zotero library search for the current chat request."""
    _zotero_search_ctx.set(ZoteroSearchRequest(enabled=bool(enabled), owner=(owner or "").strip()))


def get_zotero_search_request() -> ZoteroSearchRequest:
    return _zotero_search_ctx.get()


def format_zotero_search_context(findings: List[dict]) -> Tuple[str, List[dict]]:
    """Format Zotero findings as LLM context plus source chips for the UI."""
    if not findings:
        return "No matching items found in your Zotero library.", []

    parts = [
        "ZOTERO LIBRARY RESULTS",
        "=" * 50,
    ]
    sources: List[dict] = []
    for i, finding in enumerate(findings, 1):
        title = (finding.get("title") or "Untitled").strip()
        url = (finding.get("url") or "").strip()
        authors = (finding.get("authors") or "").strip()
        year = (finding.get("year") or "").strip()
        summary = (finding.get("summary") or "").strip()
        evidence = (finding.get("evidence") or "").strip()

        parts.append(f"\n[{i}] {title}")
        if authors or year:
            byline = authors or "Unknown author"
            if year:
                byline = f"{byline} ({year})"
            parts.append(f"    {byline}")
        if url:
            parts.append(f"    URL: {url}")
        if summary:
            parts.append(f"    Summary: {summary[:800]}")
        if evidence and evidence[:800] != summary[:800]:
            excerpt = evidence[:3000]
            if len(evidence) > 3000:
                excerpt += "... [truncated]"
            parts.append(f"    Excerpt:\n{excerpt}")

        if url or title:
            sources.append({"url": url, "title": title, "source": "zotero"})

    parts.append(
        "\n(Preview from your message — call search_zotero for folder listing, "
        "pagination, or a refined library search.)"
    )
    return "\n".join(parts), sources


def search_zotero_for_chat(query: str, owner: str = "", limit: int = 5) -> Tuple[str, List[dict]]:
    """Search the user's Zotero library for chat / web-search augmentation."""
    if not resolve_zotero_credentials(owner):
        return (
            "Zotero Library is enabled but not configured. "
            "Add your User ID and API key in Settings → Search, then Save.",
            [],
        )
    single_key = _resolve_zotero_key(query, owner)
    findings = fetch_zotero_findings(
        query,
        owner=owner,
        limit=limit,
        extract_pdfs=bool(single_key),
        seed_library=not single_key,
    )
    return format_zotero_search_context(findings)


def resolve_collection_match(name_or_key: str, collections: List[dict]) -> Tuple[Optional[str], Optional[str]]:
    """Match a collection by API key, exact path, or fuzzy name/path.

    Returns (collection_key, error_message). error_message is set when ambiguous
    or not found; collection_key is set on success.
    """
    needle = (name_or_key or "").strip()
    if not needle:
        return None, None

    if not collections:
        return None, "No collections found in your Zotero library."

    # Exact key
    for col in collections:
        if col.get("key") == needle:
            return col["key"], None

    norm = needle.lower()
    norm_path = norm.replace(">", "/").replace("\\", "/")
    norm_path = " / ".join(part.strip() for part in norm_path.split("/") if part.strip())

    exact = [
        col for col in collections
        if (col.get("path") or "").lower() == norm_path
        or (col.get("name") or "").lower() == norm
    ]
    if len(exact) == 1:
        return exact[0]["key"], None

    partial = [
        col for col in collections
        if norm_path in (col.get("path") or "").lower()
        or norm == (col.get("name") or "").lower()
        or (col.get("path") or "").lower().endswith(norm_path)
    ]
    matches = exact or partial
    if len(matches) == 1:
        return matches[0]["key"], None
    if len(matches) > 1:
        lines = [
            f"Multiple collections match {name_or_key!r}. Be more specific or pass the collection key:",
        ]
        for col in sorted(matches, key=lambda c: (c.get("path") or "").lower())[:12]:
            lines.append(f"- {col.get('path')} (key: {col.get('key')})")
        return None, "\n".join(lines)

    return None, (
        f"No collection matching {name_or_key!r}. "
        "Call search_zotero with action=list_collections to see folder names and keys."
    )


def findings_from_items(
    client: ZoteroClient,
    user_id: str,
    items: List[dict],
    *,
    extract_pdfs: bool = True,
    catalog_rows: Optional[List[dict]] = None,
) -> List[dict]:
    catalog_by_key = {
        (row.get("zotero_key") or ""): row
        for row in (catalog_rows or [])
        if row.get("zotero_key")
    }
    findings: List[dict] = []
    for item in items or []:
        key = item.get("key") or (item.get("data") or {}).get("key")
        if not key:
            continue
        full = client.get_item(key) or item
        full_data = full.get("data") or {}
        catalog_row = catalog_by_key.get(key)

        # Child PDF attachments should not surface as their own papers.
        if _is_pdf_attachment(full_data) and _attachment_parent_key(full_data):
            parent_key = _attachment_parent_key(full_data)
            parent = client.get_item(parent_key)
            if parent:
                full = parent
                key = parent_key
                catalog_row = catalog_by_key.get(key) or catalog_row

        pdf_text = ""
        if extract_pdfs:
            pdf_text = _extract_pdf_text_for_item(
                client, key, full, catalog_row=catalog_row,
            )
        findings.append(zotero_item_to_finding(full, user_id, pdf_text=pdf_text))
    return findings


def fetch_paper_pdf_text(
    owner: str,
    zotero_key: str,
    *,
    max_chars: int = 15000,
) -> Tuple[str, str]:
    """Extract PDF text for a catalog paper. Returns (text, error_or_note)."""
    key = (zotero_key or "").strip()
    if not key:
        return "", "No Zotero item key provided."

    creds = resolve_zotero_credentials(owner)
    if not creds:
        return "", "Zotero is not configured for this account."

    from src.zotero_catalog import load_catalog

    row = next(
        (r for r in load_catalog(owner) if (r.get("zotero_key") or "") == key),
        None,
    )
    client = ZoteroClient(creds["api_key"], creds["user_id"])
    item = client.get_item(key)
    if not item:
        return "", f"Paper {key} not found via the Zotero API (sync Zotero to cloud)."

    pdf_text = _extract_pdf_text_for_item(client, key, item, catalog_row=row, max_extract_chars=max_chars)
    if pdf_text:
        if len(pdf_text) > max_chars:
            pdf_text = pdf_text[:max_chars] + "\n… [PDF truncated]"
        return pdf_text, ""

    att_keys = _pdf_attachment_keys_for_item(client, key, item, catalog_row=row)
    if att_keys:
        return "", (
            "A PDF is attached but text could not be extracted. "
            "The file may be an HTML snapshot, corrupted, or larger than the extractor limit. "
            "In Zotero use “Store Copy of File” on a real PDF and sync to Zotero Cloud."
        )
    if row and row.get("has_pdf"):
        return "", (
            "A PDF is attached but text could not be downloaded. "
            "In Zotero use “Store Copy of File” and sync to Zotero Cloud. "
            "Do not substitute web_search unless the user explicitly asks for outside sources."
        )
    return "", "No PDF attached to this paper in Zotero."


def fetch_paper_section_text(
    owner: str,
    zotero_key: str,
    section: str,
    *,
    max_chars: int = 8000,
) -> Tuple[str, str, dict]:
    """Extract one PDF section for a catalog paper.

    Returns (text, error_or_note, meta). Meta includes matched_slug, available_sections, from_cache.
    """
    from datetime import datetime, timezone

    from src.paper_retrieval import PAPER_SECTION_PARSE_MAX_CHARS
    from src.paper_sections import (
        normalize_section_slug,
        parse_pdf_sections,
        section_display_label,
    )
    from src.zotero_catalog import (
        load_catalog,
        load_section_cache,
        save_section_cache,
        section_cache_valid,
    )

    key = (zotero_key or "").strip()
    slug = normalize_section_slug(section)
    meta: dict = {"requested": (section or "").strip(), "matched_slug": slug or ""}
    if not key:
        return "", "No Zotero item key provided.", meta
    if not slug:
        return "", f"Unrecognized section {section!r}. Try: methods, introduction, results, discussion.", meta

    creds = resolve_zotero_credentials(owner)
    if not creds:
        return "", "Zotero is not configured for this account.", meta

    row = next(
        (r for r in load_catalog(owner) if (r.get("zotero_key") or "") == key),
        None,
    )
    cache = load_section_cache(owner, key)
    sections_map: dict = {}
    from_cache = False

    if section_cache_valid(cache, row):
        sections_map = dict(cache.get("sections") or {})
        from_cache = True
    else:
        client = ZoteroClient(creds["api_key"], creds["user_id"])
        item = client.get_item(key)
        if not item:
            return "", f"Paper {key} not found via the Zotero API (sync Zotero to cloud).", meta

        full_text = _extract_pdf_text_for_item(
            client,
            key,
            item,
            catalog_row=row,
            max_extract_chars=PAPER_SECTION_PARSE_MAX_CHARS,
        )
        if not full_text:
            att_keys = _pdf_attachment_keys_for_item(client, key, item, catalog_row=row)
            if att_keys or (row and row.get("has_pdf")):
                return "", (
                    "A PDF is attached but text could not be extracted for section parsing. "
                    "Try abstract-only read or include_pdf=true for full text."
                ), meta
            return "", "No PDF attached to this paper in Zotero.", meta

        sections_map = parse_pdf_sections(full_text)
        if sections_map:
            save_section_cache(
                owner,
                key,
                {
                    "zotero_key": key,
                    "date_modified": (row or {}).get("date_modified") or "",
                    "parsed_at": datetime.now(timezone.utc).isoformat(),
                    "sections": sections_map,
                },
            )

    available = sorted(sections_map.keys())
    meta["available_sections"] = available
    meta["from_cache"] = from_cache

    if not sections_map:
        return "", (
            "Could not detect section headings in this PDF. "
            "Use abstract-only read (default) or include_pdf=true for full text."
        ), meta

    body = sections_map.get(slug, "")
    if not body:
        hint = ", ".join(available) if available else "none detected"
        return "", (
            f"Section {section_display_label(slug)!r} not found in PDF. "
            f"Detected sections: {hint}."
        ), meta

    if len(body) > max_chars:
        body = body[:max_chars] + "\n… [section truncated]"
    meta["matched_slug"] = slug
    meta["matched_label"] = section_display_label(slug)
    return body, "", meta


def _resolve_zotero_key(query: str, owner: str) -> str:
    """Map paper:KEY, bare 8-char keys, or catalog titles to a Zotero item key."""
    q = (query or "").strip()
    if not q:
        return ""
    if q.lower().startswith("paper:"):
        return q.split(":", 1)[1].strip()
    if re.fullmatch(r"[A-Za-z0-9]{8}", q):
        from src.zotero_catalog import load_catalog

        for row in load_catalog(owner):
            if (row.get("zotero_key") or "").upper() == q.upper():
                return row["zotero_key"]
        return q
    return ""


def execute_search_zotero_tool(args: dict, owner: str = "") -> Dict[str, Any]:
    """Agent tool entry: list collections or search the user's library."""
    if not isinstance(args, dict):
        args = {}

    creds = resolve_zotero_credentials(owner)
    if not creds:
        return {
            "output": (
                "Zotero is not configured for this account. "
                "Ask the user to add their User ID and API key under Settings → Search → Zotero Library."
            ),
            "exit_code": 1,
        }

    client = ZoteroClient(creds["api_key"], creds["user_id"])
    action = (args.get("action") or "search").strip().lower()

    if action in ("list_collections", "list_folders", "collections", "folders"):
        from src.zotero_catalog import format_collections_text, load_collections

        cached = format_collections_text(owner)
        if cached:
            return {"output": cached, "exit_code": 0}
        cols = client.list_collections()
        if not cols:
            return {"output": "No collections found in your Zotero library.", "exit_code": 0}
        lines = [
            "Zotero collections (pass `collection` as the path or key in search_zotero):",
            "",
        ]
        for col in sorted(cols, key=lambda c: (c.get("path") or "").lower()):
            lines.append(f"- {col.get('path')}  (key: {col.get('key')})")
        lines.append("")
        lines.append("Tip: Sync library in Settings → Search → Zotero to cache metadata for Links and faster search.")
        return {"output": "\n".join(lines), "exit_code": 0}

    if action in ("sync_catalog", "sync"):
        from src.zotero_catalog import sync_zotero_catalog

        result = sync_zotero_catalog(owner)
        if not result.get("ok"):
            return {"output": result.get("error") or "Sync failed", "exit_code": 1}
        return {
            "output": (
                f"Synced Zotero catalog — {result['items']} items, "
                f"{result['collections']} collections. "
                "Papers are indexed in Links (Papers tab). "
                "Use search_knowledge with types=[\"paper\"] to browse the graph."
            ),
            "exit_code": 0,
        }

    query = (args.get("query") or args.get("q") or "").strip()
    collection = (args.get("collection") or args.get("folder") or "").strip()
    zotero_key = (
        (args.get("zotero_key") or args.get("item_key") or args.get("key") or "").strip()
        or _resolve_zotero_key(query, owner)
    )
    try:
        limit = int(args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    try:
        start = int(args.get("start", 0))
    except (TypeError, ValueError):
        start = 0
    include_pdf = args.get("include_pdf")
    section_query = (args.get("section") or "").strip()
    if include_pdf is None:
        include_pdf = bool(zotero_key) and not section_query
    elif isinstance(include_pdf, str):
        include_pdf = include_pdf.lower() not in ("false", "0", "no")
    else:
        include_pdf = bool(include_pdf)

    limit = min(max(limit, 1), 25)
    start = max(start, 0)

    if zotero_key and section_query:
        from src.paper_retrieval import PAPER_SECTION_DEFAULT_MAX_CHARS

        try:
            sec_max = int(args.get("max_chars", PAPER_SECTION_DEFAULT_MAX_CHARS))
        except (TypeError, ValueError):
            sec_max = PAPER_SECTION_DEFAULT_MAX_CHARS
        sec_text, sec_note, sec_meta = fetch_paper_section_text(
            owner, zotero_key, section_query, max_chars=sec_max,
        )
        if sec_text:
            label = sec_meta.get("matched_label") or section_query
            header = f"Zotero paper:{zotero_key} — section: {label}"
            return {"output": f"{header}\n\n{sec_text}", "exit_code": 0}
        return {
            "output": sec_note or f"Section {section_query!r} not found.",
            "exit_code": 1,
        }

    from src.zotero_catalog import load_catalog, search_catalog, catalog_row_to_item

    items: List[dict] = []
    catalog_hits: List[dict] = []
    scope_label = "entire library"

    if zotero_key:
        row = next(
            (r for r in load_catalog(owner) if (r.get("zotero_key") or "").upper() == zotero_key.upper()),
            None,
        )
        if row:
            catalog_hits = [row]
            items = [catalog_row_to_item(row)]
        else:
            item = client.get_item(zotero_key)
            if not item:
                return {
                    "output": f"No Zotero item with key {zotero_key!r}. Sync catalog or check the key from paper:… in Links.",
                    "exit_code": 1,
                }
            items = [item]
        scope_label = f"paper:{zotero_key}"
    elif load_catalog(owner):
        catalog_hits = search_catalog(owner, query, collection=collection, limit=limit + start)
        if start:
            catalog_hits = catalog_hits[start:start + limit]
        else:
            catalog_hits = catalog_hits[:limit]

        if catalog_hits:
            items = [catalog_row_to_item(row) for row in catalog_hits]
            if collection:
                scope_label = collection + " (local catalog)"
            elif query:
                scope_label = "local catalog"
            else:
                scope_label = "recent library items (local catalog)"
        elif not query and not collection:
            items = client.list_recent_items(limit=limit, start=start)
            if not items:
                items = _expand_searchable_items(client.list_top_items(limit), limit)
            scope_label = "recent library items"
        else:
            collections = client.list_collections()
            collection_keys = None
            scope_label = "entire library"
            if collection:
                root_key, err = resolve_collection_match(collection, collections)
                if err:
                    return {"output": err, "exit_code": 1}
                if not root_key:
                    return {"output": f"Could not resolve collection {collection!r}.", "exit_code": 1}
                collection_keys = client.collection_subtree_keys(root_key, collections)
                scope_label = next((c["path"] for c in collections if c["key"] == root_key), collection)
                scope_label += " (including subfolders)"

            items = client.search_scoped(
                query=query,
                limit=limit,
                start=start,
                collection_keys=collection_keys,
                seed_library=False,
            )
            if not items and query:
                items = client.search_scoped(
                    query=query,
                    limit=limit,
                    start=start,
                    collection_keys=collection_keys,
                    seed_library=True,
                )
    elif not query and not collection:
        items = client.list_recent_items(limit=limit, start=start)
        if not items:
            items = _expand_searchable_items(client.list_top_items(limit), limit)
        scope_label = "recent library items"
    else:
        collections = client.list_collections()
        collection_keys = None
        if collection:
            root_key, err = resolve_collection_match(collection, collections)
            if err:
                return {"output": err, "exit_code": 1}
            if not root_key:
                return {"output": f"Could not resolve collection {collection!r}.", "exit_code": 1}
            collection_keys = client.collection_subtree_keys(root_key, collections)
            scope_label = next((c["path"] for c in collections if c["key"] == root_key), collection)
            scope_label += " (including subfolders)"

        items = client.search_scoped(
            query=query,
            limit=limit,
            start=start,
            collection_keys=collection_keys,
            seed_library=False,
        )
        if not items and query:
            items = client.search_scoped(
                query=query,
                limit=limit,
                start=start,
                collection_keys=collection_keys,
                seed_library=True,
            )

    findings = findings_from_items(
        client, creds["user_id"], items, extract_pdfs=bool(include_pdf),
        catalog_rows=catalog_hits if catalog_hits else None,
    )
    body, sources = format_zotero_search_context(findings)
    if not findings:
        ok, conn_msg, _info = client.test_connection()
        hint = (
            f"\n\nZotero connection: {conn_msg}."
            if ok else f"\n\nZotero connection issue: {conn_msg}."
        )
        if not load_catalog(owner):
            hint += " Sync your library in Settings → Search → Zotero (Sync catalog) for faster search and Links indexing."
        tops = client.list_top_items(10)
        if tops:
            hint += "\n\n" + _summarize_top_level_items(tops, limit=8)
        else:
            hint += (
                " If items exist locally but not here, open Zotero and sync to Zotero Cloud."
                " Try action=list_collections or search with an empty query to browse recent items."
            )
        body = body.rstrip() + hint
    elif include_pdf and not any((f.get("evidence") or "").strip() for f in findings):
        body = body.rstrip() + (
            "\n\n(PDF text could not be extracted. The file may be linked locally only — "
            "in Zotero use “Store Copy of File” and sync to cloud, then retry with include_pdf=true.)"
        )
    header = f"Zotero search — scope: {scope_label}"
    if query:
        header += f" | query: {query}"
    if start:
        header += f" | start: {start}"
    header += f" | returned: {len(findings)}"
    output = header + "\n\n" + body
    if sources:
        output += "\n\n<!-- SOURCES:" + __import__("json").dumps(sources) + " -->"
    return {"output": output, "exit_code": 0, "sources": sources}


def fetch_zotero_findings(
    query: str,
    owner: str = "",
    limit: int = 5,
    extract_pdfs: bool = True,
    seed_library: bool = False,
) -> List[dict]:
    """Search Zotero and return findings ready for the research pipeline."""
    from src.research_zotero import research_zotero_findings

    outcome = research_zotero_findings(
        query,
        owner,
        limit=limit,
        extract_pdfs=extract_pdfs,
        seed_library=seed_library,
    )
    return outcome.findings


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
