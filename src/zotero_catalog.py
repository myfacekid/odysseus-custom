"""Local metadata catalog for Zotero libraries (no PDF indexing).

Synced to ``data/zotero/users/{owner}/`` and consumed by the knowledge graph
and ``search_zotero`` for fast collection-aware browse/search.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.constants import DATA_DIR
from src.zotero_client import (
    ZoteroClient,
    _format_authors,
    _is_bibliographic_item,
    _is_pdf_attachment,
    _attachment_parent_key,
    _item_display_title,
    _pick_best_pdf_attachment,
    _title_matches_query,
    enrich_pdf_attachments_from_children,
    list_pdf_attachments_by_parent,
    resolve_zotero_credentials,
)

logger = logging.getLogger(__name__)

ZOTERO_ROOT = Path(DATA_DIR) / "zotero"
DEFAULT_MAX_ITEMS = 5000


def _owner_dir(owner: str) -> Path:
    safe = re.sub(r"[^\w.-]", "_", (owner or "default").strip()) or "default"
    return ZOTERO_ROOT / "users" / safe


def catalog_path(owner: str) -> Path:
    return _owner_dir(owner) / "catalog.jsonl"


def collections_path(owner: str) -> Path:
    return _owner_dir(owner) / "collections.json"


def manifest_path(owner: str) -> Path:
    return _owner_dir(owner) / "manifest.json"


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def _write_jsonl(path: Path, rows: List[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    body = "\n".join(json.dumps(r, ensure_ascii=False) for r in rows)
    if body:
        body += "\n"
    tmp.write_text(body, encoding="utf-8")
    tmp.replace(path)


def load_catalog(owner: str) -> List[dict]:
    path = catalog_path(owner)
    if not path.is_file():
        return []
    rows: List[dict] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
                if isinstance(row, dict) and row.get("zotero_key"):
                    if _is_legacy_attachment_paper(row):
                        continue
                    rows.append(row)
            except json.JSONDecodeError:
                continue
    except OSError as e:
        logger.debug(f"load_catalog failed for {owner}: {e}")
    return rows


def load_collections(owner: str) -> List[dict]:
    path = collections_path(owner)
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def load_manifest(owner: str) -> dict:
    path = manifest_path(owner)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def catalog_stats(owner: str) -> dict:
    manifest = load_manifest(owner)
    rows = load_catalog(owner)
    cols = load_collections(owner)
    return {
        "synced": bool(rows),
        "item_count": len(rows),
        "collection_count": len(cols),
        "synced_at": manifest.get("synced_at"),
        "user_id": manifest.get("user_id"),
    }


def _year_from_date(date_str: str) -> str:
    m = re.search(r"\d{4}", str(date_str or ""))
    return m.group(0) if m else ""


def _is_legacy_attachment_paper(row: dict) -> bool:
    """Drop child PDF attachments that were wrongly indexed as papers."""
    if (row.get("item_type") or "") != "attachment":
        return False
    if row.get("standalone_attachment"):
        return False
    return True


def _catalog_row_from_item(
    item: dict,
    *,
    path_by_key: Dict[str, str],
    user_id: str,
    pdf_attachment: Optional[dict] = None,
    standalone_attachment: bool = False,
) -> dict:
    data = item.get("data") or {}
    key = (item.get("key") or data.get("key") or "").strip()
    col_keys = [k for k in (data.get("collections") or []) if k]
    col_paths = [path_by_key[k] for k in col_keys if k in path_by_key]
    abstract = (data.get("abstractNote") or "").strip()
    title = _item_display_title(item)
    authors = _format_authors(data.get("creators") or [])
    item_type = (data.get("itemType") or "").strip()
    doi = (data.get("DOI") or "").strip()
    pdf_key = ""
    if pdf_attachment:
        pdf_key = (pdf_attachment.get("key") or (pdf_attachment.get("data") or {}).get("key") or "").strip()
    elif standalone_attachment:
        pdf_key = key
    has_pdf = bool(pdf_key)
    url = doi if doi.startswith("http") else (f"https://doi.org/{doi}" if doi else f"https://www.zotero.org/users/{user_id}/items/{key}")
    return {
        "zotero_key": key,
        "title": title,
        "authors": authors,
        "year": _year_from_date(data.get("date") or ""),
        "item_type": item_type,
        "doi": doi,
        "abstract": abstract[:4000],
        "collection_keys": col_keys,
        "collection_paths": col_paths,
        "has_pdf": has_pdf,
        "pdf_attachment_key": pdf_key,
        "standalone_attachment": standalone_attachment,
        "url": url,
        "date_added": (data.get("dateAdded") or "").strip(),
        "date_modified": (data.get("dateModified") or "").strip(),
    }


def _fetch_all_catalog_items(
    client: ZoteroClient,
    *,
    max_items: int,
) -> Tuple[List[dict], Dict[str, List[dict]], List[dict]]:
    """Paginate /items into bibliographic papers, child PDFs by parent, and standalone PDFs."""
    bibliographic: List[dict] = []
    pdfs_by_parent: Dict[str, List[dict]] = {}
    standalone_attachments: List[dict] = []
    seen: set[str] = set()
    start = 0
    page = 100
    max_items = min(max(max_items, 1), 10000)

    while len(bibliographic) + len(standalone_attachments) < max_items:
        try:
            import httpx

            params = [
                ("limit", str(page)),
                ("start", str(start)),
                ("sort", "dateModified"),
                ("direction", "desc"),
            ]
            with httpx.Client(timeout=30, headers=client._headers) as http:
                r = http.get(client._url("/items"), params=params)
                r.raise_for_status()
                batch = r.json()
        except Exception as e:
            logger.warning(f"Zotero catalog fetch page start={start} failed: {e}")
            break

        if not isinstance(batch, list) or not batch:
            break

        for item in batch:
            data = item.get("data") or {}
            key = (item.get("key") or data.get("key") or "").strip()
            if not key or key in seen:
                continue
            seen.add(key)
            itype = data.get("itemType") or ""

            if _is_bibliographic_item(item):
                bibliographic.append(item)
            elif itype == "attachment" and _is_pdf_attachment(data):
                parent = _attachment_parent_key(data)
                if parent:
                    pdfs_by_parent.setdefault(parent, []).append(item)
                else:
                    standalone_attachments.append(item)

            if len(bibliographic) + len(standalone_attachments) >= max_items:
                break

        if len(batch) < page:
            break
        start += page

    return bibliographic, pdfs_by_parent, standalone_attachments


def sync_zotero_catalog(owner: str, *, max_items: int = DEFAULT_MAX_ITEMS) -> dict:
    """Pull metadata from Zotero Cloud into the local catalog."""
    if not owner:
        return {"ok": False, "error": "owner required"}

    creds = resolve_zotero_credentials(owner)
    if not creds:
        return {"ok": False, "error": "Zotero not configured"}

    client = ZoteroClient(creds["api_key"], creds["user_id"])
    collections = client.list_collections()
    path_by_key = {c["key"]: c["path"] for c in collections if c.get("key")}

    items, pdfs_by_parent, standalone_attachments = _fetch_all_catalog_items(
        client, max_items=max_items,
    )
    # Dedicated attachment pass + per-item fallback — flat /items pagination often
    # misses child PDF metadata (has_pdf was false despite a visible PDF in Zotero).
    scanned = list_pdf_attachments_by_parent(client)
    for parent_key, attachments in scanned.items():
        bucket = pdfs_by_parent.setdefault(parent_key, [])
        seen_keys = {
            (a.get("key") or (a.get("data") or {}).get("key") or "")
            for a in bucket
        }
        for att in attachments:
            ak = att.get("key") or (att.get("data") or {}).get("key") or ""
            if ak and ak not in seen_keys:
                bucket.append(att)
                seen_keys.add(ak)
    enrich_pdf_attachments_from_children(client, items, pdfs_by_parent)
    rows: List[dict] = []
    for item in items:
        key = (item.get("key") or (item.get("data") or {}).get("key") or "").strip()
        pdf_attachment = _pick_best_pdf_attachment(pdfs_by_parent.get(key, []))
        rows.append(
            _catalog_row_from_item(
                item,
                path_by_key=path_by_key,
                user_id=creds["user_id"],
                pdf_attachment=pdf_attachment,
            )
        )
    for item in standalone_attachments:
        rows.append(
            _catalog_row_from_item(
                item,
                path_by_key=path_by_key,
                user_id=creds["user_id"],
                standalone_attachment=True,
            )
        )
    rows.sort(key=lambda r: (r.get("date_modified") or r.get("date_added") or ""), reverse=True)

    _write_jsonl(catalog_path(owner), rows)
    _write_json(collections_path(owner), collections)
    from datetime import datetime, timezone

    manifest = {
        "owner": owner,
        "user_id": creds["user_id"],
        "synced_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "item_count": len(rows),
        "collection_count": len(collections),
        "max_items": max_items,
    }
    _write_json(manifest_path(owner), manifest)

    try:
        from src.knowledge_sync import after_zotero_sync

        after_zotero_sync(owner)
    except Exception as e:
        logger.warning(f"Knowledge graph rebuild after Zotero sync failed: {e}")

    return {
        "ok": True,
        "items": len(rows),
        "collections": len(collections),
        "synced_at": manifest["synced_at"],
    }


def clear_zotero_catalog(owner: str) -> None:
    d = _owner_dir(owner)
    for name in ("catalog.jsonl", "collections.json", "manifest.json"):
        p = d / name
        if p.is_file():
            p.unlink()


def _collection_matches(row: dict, collection: str, path_by_key: Dict[str, str]) -> bool:
    needle = (collection or "").strip().lower()
    if not needle:
        return True
    for path in row.get("collection_paths") or []:
        pl = path.lower()
        if needle == pl or needle in pl or pl in needle:
            return True
    for key in row.get("collection_keys") or []:
        if needle == key.lower():
            return True
        path = (path_by_key.get(key) or "").lower()
        if path and (needle == path or needle in path or path in needle):
            return True
    return False


def search_catalog(
    owner: str,
    query: str = "",
    *,
    collection: str = "",
    limit: int = 10,
) -> List[dict]:
    rows = load_catalog(owner)
    if not rows:
        return []

    path_by_key = {c["key"]: c["path"] for c in load_collections(owner) if c.get("key")}
    limit = min(max(limit, 1), 100)
    q = (query or "").strip()

    if not q and not collection:
        return rows[:limit]

    out: List[dict] = []
    for row in rows:
        if collection and not _collection_matches(row, collection, path_by_key):
            continue
        if q:
            title = row.get("title") or ""
            if not _title_matches_query(title, q):
                hay = " ".join(
                    str(row.get(k) or "")
                    for k in ("title", "authors", "abstract", "doi", "year")
                ).lower()
                tokens = [t for t in re.findall(r"[a-z0-9]+", q.lower()) if len(t) >= 2]
                if tokens and not all(t in hay for t in tokens):
                    continue
        out.append(row)
        if len(out) >= limit:
            break
    return out


def catalog_row_to_item(row: dict) -> dict:
    """Shape a catalog row like a Zotero API item for findings_from_items."""
    key = row.get("zotero_key") or ""
    return {
        "key": key,
        "data": {
            "key": key,
            "itemType": row.get("item_type") or "journalArticle",
            "title": row.get("title") or "Untitled",
            "creators": [],
            "date": row.get("year") or "",
            "DOI": row.get("doi") or "",
            "abstractNote": row.get("abstract") or "",
            "url": row.get("url") or "",
        },
        "_catalog_pdf_key": row.get("pdf_attachment_key") or "",
    }


def catalog_row_to_library_item(row: dict) -> dict:
    """Shape a catalog row for the Documents library grid."""
    key = (row.get("zotero_key") or "").strip()
    authors = (row.get("authors") or "").strip()
    year = (row.get("year") or "").strip()
    abstract = (row.get("abstract") or "").strip()
    preview_parts = [p for p in (authors, f"({year})" if year else "", abstract) if p]
    preview = "\n\n".join(preview_parts)[:500]
    updated = (row.get("date_modified") or row.get("date_added") or "").strip() or None
    created = (row.get("date_added") or "").strip() or None
    return {
        "id": f"zotero:{key}",
        "source": "zotero",
        "zotero_key": key,
        "session_id": None,
        "session_name": "Zotero",
        "title": row.get("title") or "Untitled",
        "language": "paper",
        "preview": preview,
        "version_count": 1,
        "created_at": created,
        "updated_at": updated,
        "authors": authors,
        "year": year,
        "has_pdf": bool(row.get("has_pdf")),
        "url": row.get("url") or "",
        "collection_paths": row.get("collection_paths") or [],
    }


def _library_matches_search(row: dict, query: str) -> bool:
    q = (query or "").strip()
    if not q:
        return True
    title = row.get("title") or ""
    if _title_matches_query(title, q):
        return True
    hay = " ".join(
        str(row.get(k) or "")
        for k in ("title", "authors", "abstract", "doi", "year", "preview")
    ).lower()
    tokens = [t for t in re.findall(r"[a-z0-9]+", q.lower()) if len(t) >= 2]
    return not tokens or all(t in hay for t in tokens)


def library_items_from_catalog(owner: str, *, search: str = "") -> List[dict]:
    rows = load_catalog(owner)
    if not rows:
        return []
    out: List[dict] = []
    for row in rows:
        item = catalog_row_to_library_item(row)
        if _library_matches_search(item, search):
            out.append(item)
    return out


def format_collections_text(owner: str) -> str:
    cols = load_collections(owner)
    if cols:
        lines = [
            "Zotero collections (pass `collection` as the path or key in search_zotero):",
            "",
        ]
        for col in sorted(cols, key=lambda c: (c.get("path") or "").lower()):
            lines.append(f"- {col.get('path')}  (key: {col.get('key')})")
        manifest = load_manifest(owner)
        if manifest.get("synced_at"):
            lines.append("")
            lines.append(f"(Local catalog synced {manifest['synced_at']} — {manifest.get('item_count', len(load_catalog(owner)))} items)")
        return "\n".join(lines)
    return ""
