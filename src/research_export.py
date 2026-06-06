"""Export Deep Research artifacts from the evidence registry (Phase 3d)."""
from __future__ import annotations

import json
import re
from typing import List, Optional, Tuple

from src.research_evidence import EvidenceRegistry, EvidenceSource, extract_citation_nums

EXPORT_FORMATS = frozenset({"markdown", "bibtex", "csl-json"})
EXPORT_SCOPES = frozenset({"cited", "all"})

_MEDIA_TYPES = {
    "markdown": "text/markdown; charset=utf-8",
    "bibtex": "application/x-bibtex; charset=utf-8",
    "csl-json": "application/json; charset=utf-8",
}

_FILE_EXTENSIONS = {
    "markdown": ".md",
    "bibtex": ".bib",
    "csl-json": ".json",
}


def _sanitize_filename(name: str) -> str:
    name = name if isinstance(name, str) else ""
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name.strip())
    return (name[:80] or "research").strip("._-")


def export_filename(session_id: str, fmt: str, query: str = "") -> str:
    """Build a safe attachment filename for an export."""
    slug = _sanitize_filename(query) if query else _sanitize_filename(session_id)
    ext = _FILE_EXTENSIONS.get(fmt, ".txt")
    return f"{slug}{ext}"


def _report_text(data: dict) -> str:
    return (data.get("raw_report") or data.get("result") or "").strip()


def _load_registry(data: dict) -> EvidenceRegistry:
    raw = data.get("evidence_registry") or {}
    if isinstance(raw, dict) and raw.get("sources"):
        return EvidenceRegistry.from_dict(raw)
    return EvidenceRegistry()


def select_export_sources(
    registry: EvidenceRegistry,
    report_md: str,
    *,
    scope: str = "cited",
) -> List[EvidenceSource]:
    """Return registry sources for BibTeX/CSL export."""
    scope = (scope or "cited").strip().lower()
    if scope == "all":
        return registry.sources()
    cited = extract_citation_nums(report_md or "")
    if not cited:
        return registry.sources()
    return [src for src in registry.sources() if src.citation_num in cited]


def export_markdown(data: dict) -> str:
    """Canonical markdown export from stored session data."""
    report = _report_text(data)
    if not report:
        raise ValueError("No report content available for export")
    query = (data.get("query") or "").strip()
    if query and not report.lstrip().startswith("#"):
        return f"# {query}\n\n{report}"
    return report


def _bibtex_escape(value: str) -> str:
    return (value or "").replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")


def _bibtex_key(src: EvidenceSource) -> str:
    author = (src.authors or "").split(",")[0].split(" and ")[0].strip()
    author_slug = re.sub(r"[^A-Za-z]", "", author.split()[-1] if author else "")
    year = re.sub(r"[^0-9]", "", src.year or "") or "nd"
    base = (author_slug or "research")[:24]
    return f"{base}{year}{src.citation_num}"


def _bibtex_entry_type(src: EvidenceSource) -> str:
    study = (src.study_type or "").lower()
    if src.peer_review_status == "preprint" or "arxiv" in (src.url or "").lower():
        return "misc"
    if "review" in study:
        return "article"
    if src.doi_or_id.startswith("10."):
        return "article"
    return "misc"


def source_to_bibtex(src: EvidenceSource) -> str:
    """Render one BibTeX entry from a registry source."""
    entry_type = _bibtex_entry_type(src)
    fields = []
    notes: List[str] = []
    if src.authors:
        fields.append(f"  author = {{{_bibtex_escape(src.authors)}}}")
    if src.title:
        fields.append(f"  title = {{{_bibtex_escape(src.title)}}}")
    if src.year:
        fields.append(f"  year = {{{_bibtex_escape(src.year)}}}")
    if src.doi_or_id.startswith("10."):
        fields.append(f"  doi = {{{_bibtex_escape(src.doi_or_id)}}}")
    elif src.doi_or_id:
        notes.append(src.doi_or_id)
    if src.url:
        fields.append(f"  url = {{{_bibtex_escape(src.url)}}}")
    if src.study_type:
        fields.append(f"  howpublished = {{{_bibtex_escape(src.study_type)}}}")
    if src.peer_review_status == "preprint":
        notes.append("preprint")
    if notes:
        fields.append(f"  note = {{{_bibtex_escape('; '.join(notes))}}}")
    if not fields:
        fields.append(f"  title = {{{_bibtex_escape(src.title or src.source_id)}}}")
    key = _bibtex_key(src)
    body = ",\n".join(fields)
    return f"@{entry_type}{{{key},\n{body}\n}}"


def export_bibtex(data: dict, *, scope: str = "cited") -> str:
    registry = _load_registry(data)
    sources = select_export_sources(registry, _report_text(data), scope=scope)
    if not sources:
        raise ValueError("No sources available for BibTeX export")
    return "\n\n".join(source_to_bibtex(src) for src in sources).strip() + "\n"


def _parse_csl_authors(authors: str) -> List[dict]:
    text = (authors or "").strip()
    if not text:
        return []
    parts = re.split(r"\s+and\s+|;\s*", text, flags=re.I)
    out: List[dict] = []
    for part in parts:
        part = part.strip().strip(",")
        if not part:
            continue
        if "," in part:
            family, given = part.split(",", 1)
            author = {"family": family.strip()}
            given = given.strip()
            if given:
                author["given"] = given
            out.append(author)
        else:
            tokens = part.split()
            if len(tokens) >= 2:
                out.append({"family": tokens[-1], "given": " ".join(tokens[:-1])})
            else:
                out.append({"literal": part})
    return out


def _csl_item_type(src: EvidenceSource) -> str:
    study = (src.study_type or "").lower()
    if src.peer_review_status == "preprint":
        return "article"
    if "review" in study:
        return "review"
    if src.doi_or_id.startswith("10."):
        return "article-journal"
    return "document"


def source_to_csl_item(src: EvidenceSource) -> dict:
    """Render one CSL-JSON item from a registry source."""
    item = {
        "id": src.source_id or f"ref{src.citation_num}",
        "type": _csl_item_type(src),
        "title": src.title or "Untitled",
    }
    authors = _parse_csl_authors(src.authors)
    if authors:
        item["author"] = authors
    year_match = re.search(r"\d{4}", src.year or "")
    if year_match:
        item["issued"] = {"date-parts": [[int(year_match.group())]]}
    if src.doi_or_id.startswith("10."):
        item["DOI"] = src.doi_or_id
    elif src.doi_or_id:
        item["number"] = src.doi_or_id
    if src.url:
        item["URL"] = src.url
    if src.peer_review_status == "preprint":
        item["genre"] = "preprint"
    if src.study_type:
        item["note"] = src.study_type
    return item


def export_csl_json(data: dict, *, scope: str = "cited") -> str:
    registry = _load_registry(data)
    sources = select_export_sources(registry, _report_text(data), scope=scope)
    if not sources:
        raise ValueError("No sources available for CSL JSON export")
    items = [source_to_csl_item(src) for src in sources]
    return json.dumps(items, indent=2, ensure_ascii=False) + "\n"


def normalize_export_format(fmt: str) -> str:
    normalized = (fmt or "markdown").strip().lower().replace("_", "-")
    if normalized == "csljson":
        normalized = "csl-json"
    if normalized not in EXPORT_FORMATS:
        raise ValueError(f"Unsupported export format: {fmt}")
    return normalized


def normalize_export_scope(scope: str) -> str:
    normalized = (scope or "cited").strip().lower()
    if normalized not in EXPORT_SCOPES:
        raise ValueError(f"Unsupported export scope: {scope}")
    return normalized


def build_export(
    data: dict,
    fmt: str,
    *,
    scope: str = "cited",
    session_id: str = "",
) -> Tuple[str, str, str]:
    """Return (content, media_type, filename) for a research session export."""
    fmt = normalize_export_format(fmt)
    scope = normalize_export_scope(scope)
    query = (data.get("query") or "").strip()
    sid = session_id or (data.get("session_id") or "research")

    if fmt == "markdown":
        content = export_markdown(data)
    elif fmt == "bibtex":
        content = export_bibtex(data, scope=scope)
    else:
        content = export_csl_json(data, scope=scope)

    filename = export_filename(sid, fmt, query=query)
    return content, _MEDIA_TYPES[fmt], filename
