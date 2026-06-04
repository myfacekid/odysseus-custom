"""Deep Research Links / knowledge graph integration (Phase 1c).

Uses ``search_knowledge``, ``get_neighbors``, and ``read_knowledge_content``
— the same backends as chat ``search_knowledge`` — to gather internal evidence
from papers, documents, tasks, and collections.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

_DEFAULT_TYPES = ["paper", "document", "task", "collection"]


@dataclass
class ResearchKnowledgeOutcome:
    findings: List[dict]
    query: str
    source: str  # graph_search | graph_neighbor | collection | mixed | none
    graph_nodes: int = 0
    note: str = ""


def _paper_key_from_finding(finding: dict) -> str:
    return (
        (finding.get("paper_key") or finding.get("zotero_key") or "")
        .strip()
        .upper()
    )


def _collection_keys_from_findings(findings: List[dict]) -> Set[str]:
    keys: Set[str] = set()
    for f in findings or []:
        for ckey in f.get("collection_keys") or []:
            if ckey:
                keys.add(str(ckey))
        paths = f.get("collection_paths") or []
        if paths and f.get("paper_key"):
            # collection_paths alone — resolved via catalog search by path
            for path in paths:
                if path:
                    keys.add(str(path))
    return keys


def node_to_finding(
    owner: str,
    node: dict,
    *,
    graph_source: str,
    content_max_chars: int = 15000,
    include_pdf: bool = True,
) -> Optional[dict]:
    """Convert a graph node into a Deep Research finding dict."""
    from src.knowledge_graph import read_knowledge_content

    nid = (node.get("id") or "").strip()
    if not nid:
        return None

    ntype = (node.get("type") or "").strip().lower()
    title = (node.get("title") or "Untitled").strip()
    snippet = (node.get("snippet") or "").strip()

    read = read_knowledge_content(
        owner,
        nid,
        max_chars=content_max_chars,
        include_pdf=include_pdf and ntype == "paper",
    )
    if read.get("exit_code") != 0:
        body = snippet
        meta: dict = {}
    else:
        body = (read.get("body") or snippet or "").strip()
        meta = read.get("meta") or {}

    summary = snippet[:2000] if snippet else (body[:800] if body else f"Links: {title}")
    evidence = body[:content_max_chars] if body else summary

    url = (meta.get("url") or "").strip()
    if not url and ntype == "paper":
        doi = (meta.get("doi") or node.get("meta", {}).get("doi") or "").strip()
        zkey = (meta.get("zotero_key") or nid.split(":", 1)[-1]).strip()
        if doi.startswith("http"):
            url = doi
        elif doi:
            url = f"https://doi.org/{doi}"
        elif zkey:
            url = f"https://www.zotero.org/items/{zkey}"

    rational = {
        "graph_search": "Matched from Links knowledge graph search",
        "graph_neighbor": "Related item from Links graph neighbors",
        "collection": "Sibling paper from the same Zotero collection",
        "graph_seed": "Seed item from Links knowledge graph",
    }.get(graph_source, "From Links knowledge graph")

    finding: dict = {
        "url": url or f"links://{nid}",
        "title": title,
        "rational": rational,
        "evidence": evidence,
        "summary": summary,
        "source_type": "knowledge",
        "graph_node_id": nid,
        "graph_source": graph_source,
        "knowledge_source": "links",
        "node_type": ntype,
    }

    if ntype == "paper":
        zkey = (meta.get("zotero_key") or nid.split(":", 1)[-1]).strip()
        if zkey:
            finding["paper_key"] = zkey
            finding["zotero_key"] = zkey
        finding["authors"] = node.get("meta", {}).get("authors") or meta.get("authors") or ""
        finding["year"] = str(node.get("meta", {}).get("year") or meta.get("year") or "")
        finding["doi_or_id"] = node.get("meta", {}).get("doi") or meta.get("doi") or zkey
        finding["collection_paths"] = list(node.get("meta", {}).get("collection_paths") or [])
        finding["collection_keys"] = list(node.get("meta", {}).get("collection_keys") or [])
        if meta.get("pdf_extracted"):
            finding["pdf_extracted"] = True
        if meta.get("has_pdf") is not None:
            finding["has_pdf"] = bool(meta.get("has_pdf"))

    return finding


def _collect_neighbor_nodes(
    owner: str,
    seed_node_ids: List[str],
    *,
    limit_per_seed: int = 4,
) -> List[Tuple[dict, str]]:
    from src.knowledge_graph import get_neighbors

    out: List[Tuple[dict, str]] = []
    seen: Set[str] = set()
    for sid in seed_node_ids:
        if not sid or sid in seen:
            continue
        seen.add(sid)
        nb = get_neighbors(owner, sid)
        rows = (nb.get("outgoing") or []) + (nb.get("incoming") or [])
        added = 0
        for row in rows:
            node = row.get("node")
            if not node:
                continue
            nid = node.get("id") or ""
            if not nid or nid in seen:
                continue
            seen.add(nid)
            out.append((node, "graph_neighbor"))
            added += 1
            if added >= limit_per_seed:
                break
    return out


def _collection_sibling_rows(
    owner: str,
    seed_findings: List[dict],
    *,
    limit: int,
    exclude_keys: Set[str],
) -> List[dict]:
    from src.zotero_catalog import load_catalog, load_collections, search_catalog

    collections = load_collections(owner)
    path_by_key = {c["key"]: c["path"] for c in collections if c.get("key")}
    key_by_path = {v: k for k, v in path_by_key.items() if v}

    targets: Set[str] = set()
    for f in seed_findings or []:
        for ckey in f.get("collection_keys") or []:
            if ckey:
                targets.add(str(ckey))
        for path in f.get("collection_paths") or []:
            if path in key_by_path:
                targets.add(key_by_path[path])
            elif path:
                targets.add(str(path))

    rows: List[dict] = []
    seen_keys: Set[str] = set(exclude_keys)
    catalog = load_catalog(owner)

    for target in sorted(targets):
        hits = search_catalog(owner, "", collection=target, limit=limit)
        if not hits and target in path_by_key.values():
            # target may be a path string
            hits = [
                r for r in catalog
                if target in (r.get("collection_paths") or [])
            ][:limit]
        for row in hits:
            zkey = (row.get("zotero_key") or "").strip().upper()
            if not zkey or zkey in seen_keys:
                continue
            seen_keys.add(zkey)
            rows.append(row)
            if len(rows) >= limit:
                return rows
    return rows


def research_knowledge_findings(
    query: str,
    owner: str = "",
    *,
    seed_findings: Optional[List[dict]] = None,
    limit: int = 5,
    seed_graph: bool = False,
    expand_hops: int = 1,
    content_max_chars: int = 15000,
    types: Optional[List[str]] = None,
) -> ResearchKnowledgeOutcome:
    """Gather internal evidence from the Links knowledge graph."""
    from src.knowledge_graph import get_node, node_id, search_knowledge

    owner = (owner or "").strip()
    if not owner:
        return ResearchKnowledgeOutcome([], query, "none", note="No research owner")

    limit = max(limit, 1)
    type_filter = types or _DEFAULT_TYPES
    seed_findings = seed_findings or []

    candidates: List[Tuple[dict, str]] = []
    sources_used: Set[str] = set()
    seen_ids: Set[str] = set()

    def _add_node(node: Optional[dict], source: str) -> None:
        if not node:
            return
        nid = (node.get("id") or "").strip()
        if not nid or nid in seen_ids:
            return
        seen_ids.add(nid)
        candidates.append((node, source))
        sources_used.add(source)

    q = (query or "").strip()
    if q or seed_graph:
        sk = search_knowledge(
            owner,
            q,
            types=type_filter,
            limit=limit,
            expand_hops=expand_hops if q else 0,
        )
        src_label = "graph_seed" if seed_graph and not q else "graph_search"
        for node in sk.get("hits") or []:
            _add_node(node, src_label)
        for node in sk.get("neighbors") or []:
            _add_node(node, "graph_neighbor")

    seed_paper_ids: List[str] = []
    exclude_paper_keys: Set[str] = set()
    for f in seed_findings:
        pk = _paper_key_from_finding(f)
        if pk:
            exclude_paper_keys.add(pk)
            seed_paper_ids.append(node_id("paper", pk))

    for f in seed_findings:
        gid = (f.get("graph_node_id") or "").strip()
        if gid and gid not in seed_paper_ids:
            seed_paper_ids.append(gid)

    if seed_paper_ids:
        for node, src in _collect_neighbor_nodes(owner, seed_paper_ids, limit_per_seed=4):
            _add_node(node, src)

    if seed_findings:
        sibling_rows = _collection_sibling_rows(
            owner,
            seed_findings,
            limit=limit,
            exclude_keys=exclude_paper_keys,
        )
        for row in sibling_rows:
            zkey = (row.get("zotero_key") or "").strip()
            if not zkey:
                continue
            node = get_node(owner, node_id("paper", zkey))
            if node:
                _add_node(node, "collection")
            else:
                # Minimal node when graph not rebuilt yet
                _add_node(
                    {
                        "id": node_id("paper", zkey),
                        "type": "paper",
                        "title": row.get("title") or "Untitled",
                        "snippet": (row.get("abstract") or "")[:500],
                        "meta": {
                            "authors": row.get("authors"),
                            "year": row.get("year"),
                            "doi": row.get("doi"),
                            "collection_paths": row.get("collection_paths") or [],
                            "collection_keys": row.get("collection_keys") or [],
                            "zotero_key": zkey,
                            "has_pdf": row.get("has_pdf"),
                        },
                    },
                    "collection",
                )

    findings: List[dict] = []
    for node, src in candidates[: limit * 2]:
        finding = node_to_finding(
            owner,
            node,
            graph_source=src,
            content_max_chars=content_max_chars,
        )
        if finding:
            findings.append(finding)
        if len(findings) >= limit:
            break

    source = "none"
    if len(sources_used) == 1:
        source = next(iter(sources_used))
    elif sources_used:
        source = "mixed"

    note = ""
    if not findings:
        note = "No Links graph matches"
    else:
        note = f"Links graph ({len(findings)} item(s) via {source})"

    logger.info(
        "Research knowledge (%s): %d finding(s) for %r (seed_graph=%s)",
        source,
        len(findings),
        q[:80] if q else "(neighbors/collection)",
        seed_graph,
    )
    return ResearchKnowledgeOutcome(findings, query, source, len(seen_ids), note)


class ResearchEvidenceGatherer:
    """Unified facade for research evidence channels (Phase 1 deliverable)."""

    def web_search(self, query: str, **kwargs):
        from src.research_web_search import research_web_search

        return research_web_search(query, **kwargs)

    def zotero(self, query: str, owner: str = "", **kwargs):
        from src.research_zotero import research_zotero_findings

        return research_zotero_findings(query, owner, **kwargs)

    def knowledge(self, query: str, owner: str = "", **kwargs):
        return research_knowledge_findings(query, owner, **kwargs)
