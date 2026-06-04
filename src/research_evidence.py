"""Stable evidence registry for Deep Research (Phase 0).

Assigns permanent source IDs and citation numbers so synthesis rounds and the
final report cannot drift References away from inline [N] citations.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import urlparse, urlunparse


@dataclass
class EvidenceSource:
    source_id: str
    citation_num: int
    title: str = ""
    url: str = ""
    authors: str = ""
    year: str = ""
    doi_or_id: str = ""
    peer_review_status: str = ""
    study_type: str = ""
    source_type: str = ""
    is_seed: bool = False
    search_query: str = ""
    search_provider: str = ""
    search_kind: str = ""
    zotero_source: str = ""

    def reference_line(self) -> str:
        """Format a single References entry."""
        author_bit = f"{self.authors} " if self.authors else ""
        year_bit = f"({self.year}). " if self.year else ""
        line = f"{author_bit}{year_bit}{self.title or 'Untitled'}."
        if self.doi_or_id and str(self.doi_or_id).startswith("10."):
            line += f" https://doi.org/{self.doi_or_id}"
        elif self.url:
            line += f" {self.url}"
        return line.strip()

    def to_dict(self) -> dict:
        return asdict(self)


def source_id_for_finding(finding: dict) -> str:
    """Build a stable registry key for a finding dict."""
    zkey = (finding.get("zotero_key") or "").strip()
    if zkey:
        return f"src:zotero:{zkey.upper()}"

    paper_key = (finding.get("paper_key") or finding.get("catalog_key") or "").strip()
    if paper_key:
        return f"src:paper:{paper_key.upper()}"

    graph_id = (finding.get("graph_node_id") or "").strip()
    if graph_id:
        return f"src:graph:{graph_id.lower()}"

    url = (finding.get("url") or "").strip()
    if url:
        parsed = urlparse(url)
        scheme = (parsed.scheme or "https").lower()
        netloc = parsed.netloc.lower()
        path = parsed.path.rstrip("/") or "/"
        normalized = urlunparse((scheme, netloc, path, "", "", ""))
        return f"src:web:{normalized}"

    title = (finding.get("title") or "unknown").strip()
    digest = hashlib.sha256(title.encode("utf-8")).hexdigest()[:16]
    return f"src:unknown:{digest}"


def extract_citation_nums(text: str) -> Set[int]:
    """Return inline citation numbers like [1], excluding markdown links [1](url)."""
    if not text:
        return set()
    nums: Set[int] = set()
    for match in re.finditer(r"\[(\d+)\](?!\()", text):
        try:
            nums.add(int(match.group(1)))
        except ValueError:
            continue
    return nums


def split_references_section(report: str) -> Tuple[str, str]:
    """Split report body from an existing ## References section."""
    if not report:
        return "", ""
    match = re.search(r"^##\s+References\s*$", report, re.MULTILINE | re.IGNORECASE)
    if not match:
        return report.strip(), ""
    body = report[: match.start()].rstrip()
    refs = report[match.start() :].strip()
    return body, refs


class EvidenceRegistry:
    """Maps findings to stable source IDs and citation numbers."""

    def __init__(self) -> None:
        self._sources: List[EvidenceSource] = []
        self._by_id: Dict[str, EvidenceSource] = {}

    def __len__(self) -> int:
        return len(self._sources)

    def register(self, finding: dict, *, is_seed: bool = False) -> int:
        """Register a finding; return its stable citation number."""
        sid = source_id_for_finding(finding)
        existing = self._by_id.get(sid)
        if existing:
            if is_seed:
                existing.is_seed = True
                finding["is_seed"] = True
            finding["source_id"] = sid
            finding["citation_num"] = existing.citation_num
            return existing.citation_num

        num = len(self._sources) + 1
        src = EvidenceSource(
            source_id=sid,
            citation_num=num,
            title=(finding.get("title") or "").strip(),
            url=(finding.get("url") or "").strip(),
            authors=(finding.get("authors") or "").strip(),
            year=str(finding.get("year") or "").strip(),
            doi_or_id=(finding.get("doi_or_id") or "").strip(),
            peer_review_status=(finding.get("peer_review_status") or "").strip(),
            study_type=(finding.get("study_type") or "").strip(),
            source_type=(finding.get("source_type") or "web").strip(),
            is_seed=bool(is_seed or finding.get("is_seed")),
            search_query=(finding.get("search_query") or "").strip(),
            search_provider=(finding.get("search_provider") or "").strip(),
            search_kind=(finding.get("search_kind") or "").strip(),
            zotero_source=(finding.get("zotero_source") or "").strip(),
        )
        self._sources.append(src)
        self._by_id[sid] = src
        finding["source_id"] = sid
        finding["citation_num"] = num
        if is_seed:
            finding["is_seed"] = True
        return num

    def sync_findings(self, findings: List[dict]) -> None:
        """Ensure every finding in the list is registered."""
        for f in findings or []:
            self.register(f, is_seed=bool(f.get("is_seed")))

    def get(self, source_id: str) -> Optional[EvidenceSource]:
        return self._by_id.get(source_id)

    def sources(self) -> List[EvidenceSource]:
        return list(self._sources)

    def select_for_synthesis(self, findings: List[dict], window: int) -> List[dict]:
        """Tiered context: always include seed sources + last *window* others."""
        if not findings:
            return []

        self.sync_findings(findings)
        seen: Set[str] = set()
        seeds: List[dict] = []
        others: List[dict] = []

        for f in findings:
            sid = f.get("source_id") or source_id_for_finding(f)
            if sid in seen:
                continue
            seen.add(sid)
            if f.get("is_seed") or (self._by_id.get(sid) and self._by_id[sid].is_seed):
                seeds.append(f)
            else:
                others.append(f)

        if window < 1:
            window = 1
        recent = others[-window:] if len(others) > window else others
        return seeds + recent

    def format_registry_block(self, findings: List[dict]) -> str:
        """Prompt block listing citation numbers tied to stable source IDs."""
        if not findings:
            return ""
        lines = [
            "**Source registry — reuse these citation numbers for the same source:**",
        ]
        for f in findings:
            num = f.get("citation_num")
            sid = f.get("source_id", "")
            title = f.get("title") or "Untitled"
            lines.append(f"[{num}] {sid} — {title}")
        return "\n".join(lines)

    def format_findings(self, findings: List[dict]) -> str:
        """Format findings for synthesis prompts with registry citation numbers."""
        parts: List[str] = []
        for f in findings:
            num = f.get("citation_num")
            if num is None:
                num = self.register(f, is_seed=bool(f.get("is_seed")))
            url = f.get("url", "unknown")
            title = f.get("title", "")
            summary = f.get("summary", "")
            evidence = f.get("evidence", "")
            meta_bits = []
            if f.get("authors"):
                meta_bits.append(f"Authors: {f['authors']}")
            if f.get("year"):
                meta_bits.append(f"Year: {f['year']}")
            if f.get("doi_or_id"):
                meta_bits.append(f"ID: {f['doi_or_id']}")
            if f.get("study_type"):
                meta_bits.append(f"Type: {f['study_type']}")
            if f.get("peer_review_status"):
                meta_bits.append(f"Status: {f['peer_review_status']}")
            if f.get("source_id"):
                meta_bits.append(f"Registry: {f['source_id']}")
            if f.get("search_provider"):
                meta_bits.append(f"Search: {f['search_provider']}")
            if f.get("search_kind"):
                meta_bits.append(f"Kind: {f['search_kind']}")
            if f.get("zotero_source"):
                meta_bits.append(f"Zotero: {f['zotero_source']}")
            if f.get("collection_paths"):
                meta_bits.append(f"Collections: {', '.join(f['collection_paths'][:2])}")
            meta = " | ".join(meta_bits)
            content = summary if summary else (evidence[:1000] if evidence else "(no content)")
            header = f"**[{num}]** — [{title}]({url})"
            if meta:
                header += f"\n*{meta}*"
            parts.append(f"{header}\n{content}")
        return "\n\n".join(parts)

    def build_references_section(
        self,
        cited_nums: Optional[Set[int]] = None,
        *,
        include_all_if_empty: bool = True,
    ) -> str:
        """Build a ## References section from the registry."""
        lines = ["## References", ""]
        pool = self._sources
        if cited_nums is not None:
            pool = [s for s in self._sources if s.citation_num in cited_nums]
            if not pool and include_all_if_empty:
                pool = self._sources
        for src in pool:
            lines.append(f"[{src.citation_num}] {src.reference_line()}")
        return "\n".join(lines).strip()

    def validate_and_repair_report(self, report: str) -> Tuple[str, List[str]]:
        """Ensure inline [N] citations match the registry; rebuild References."""
        warnings: List[str] = []
        if not report:
            return report, warnings

        max_num = len(self._sources)
        cited = extract_citation_nums(report)
        invalid = {n for n in cited if n < 1 or n > max_num}
        if invalid:
            warnings.append(f"Removed invalid citations: {sorted(invalid)}")
            for n in sorted(invalid):
                report = re.sub(rf"\[{n}\](?!\()", "", report)

        cited = extract_citation_nums(report)
        body, _old_refs = split_references_section(report)
        refs = self.build_references_section(
            cited if cited else None,
            include_all_if_empty=True,
        )
        repaired = f"{body.rstrip()}\n\n{refs}" if body.strip() else refs
        return repaired.strip(), warnings

    def build_structured_fallback(self, question: str, findings: List[dict]) -> str:
        """Academic-style fallback when LLM synthesis fails."""
        self.sync_findings(findings)
        if not self._sources:
            return f"# {question}\n\nNo sources were gathered."

        lines = [
            f"# {question}",
            "",
            "## Executive Summary",
            (
                "_Automatic synthesis did not complete. This report summarizes "
                f"{len(self._sources)} source(s) gathered during research._"
            ),
            "",
            "## Key Findings",
        ]
        for src in self._sources:
            f = next(
                (item for item in findings if item.get("source_id") == src.source_id),
                {},
            )
            summary = (f.get("summary") or f.get("evidence") or "").strip()
            if summary:
                summary = summary[:1200]
            else:
                summary = "(No extract available.)"
            seed_note = " _(seed source)_" if src.is_seed else ""
            lines.append(f"- **[{src.citation_num}]** {src.title}{seed_note}: {summary}")
        lines.append("")
        lines.append(self.build_references_section(None))
        return "\n".join(lines).strip()

    def registry_prompt_block(self) -> str:
        """Full registry listing for the final-report prompt."""
        if not self._sources:
            return ""
        lines = [
            "**Evidence registry (only cite sources listed here):**",
        ]
        for src in self._sources:
            lines.append(f"[{src.citation_num}] {src.source_id} — {src.title}")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "sources": [s.to_dict() for s in self._sources],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "EvidenceRegistry":
        reg = cls()
        for raw in (data or {}).get("sources") or []:
            src = EvidenceSource(
                source_id=raw.get("source_id") or "",
                citation_num=int(raw.get("citation_num") or 0),
                title=raw.get("title") or "",
                url=raw.get("url") or "",
                authors=raw.get("authors") or "",
                year=str(raw.get("year") or ""),
                doi_or_id=raw.get("doi_or_id") or "",
                peer_review_status=raw.get("peer_review_status") or "",
                study_type=raw.get("study_type") or "",
                source_type=raw.get("source_type") or "",
                is_seed=bool(raw.get("is_seed")),
                search_query=raw.get("search_query") or "",
                search_provider=raw.get("search_provider") or "",
                search_kind=raw.get("search_kind") or "",
                zotero_source=raw.get("zotero_source") or "",
            )
            if not src.source_id or not src.citation_num:
                continue
            reg._sources.append(src)
            reg._by_id[src.source_id] = src
        return reg
