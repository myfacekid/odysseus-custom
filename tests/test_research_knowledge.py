"""Phase 1c — Links / knowledge graph for Deep Research."""

import json
from unittest.mock import patch

from src.knowledge_graph import KnowledgeEdge, KnowledgeNode, node_id, save_graph
from src.research_evidence import source_id_for_finding
from src.research_knowledge import (
    ResearchEvidenceGatherer,
    node_to_finding,
    research_knowledge_findings,
)


def _write_catalog(tmp_path, owner, rows, collections=None):
    zdir = tmp_path / "zotero" / "users" / owner
    zdir.mkdir(parents=True)
    (zdir / "catalog.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n",
        encoding="utf-8",
    )
    (zdir / "manifest.json").write_text(
        json.dumps({"synced_at": "2026-01-01T00:00:00Z", "user_id": "1"}) + "\n",
        encoding="utf-8",
    )
    cols = collections or []
    (zdir / "collections.json").write_text(json.dumps(cols), encoding="utf-8")


def test_node_to_finding_paper_includes_paper_key(tmp_path, monkeypatch):
    monkeypatch.setattr("src.knowledge_graph.KNOWLEDGE_ROOT", tmp_path / "knowledge")
    owner = "tester"
    node = {
        "id": "paper:PAPER1",
        "type": "paper",
        "title": "Attention Is All You Need",
        "snippet": "Transformers.",
        "meta": {"authors": "Vaswani", "year": "2017", "doi": "10.1234/abc"},
    }

    with patch(
        "src.knowledge_graph.read_knowledge_content",
        return_value={
            "exit_code": 0,
            "body": "Full abstract and PDF text.",
            "meta": {"zotero_key": "PAPER1", "url": "https://doi.org/10.1234/abc", "pdf_extracted": True},
        },
    ):
        finding = node_to_finding(owner, node, graph_source="graph_search")

    assert finding["paper_key"] == "PAPER1"
    assert finding["graph_node_id"] == "paper:PAPER1"
    assert finding["graph_source"] == "graph_search"
    assert "Full abstract" in finding["evidence"]
    assert source_id_for_finding(finding) == "src:zotero:PAPER1"


def test_research_knowledge_search_hits(tmp_path, monkeypatch):
    monkeypatch.setattr("src.knowledge_graph.KNOWLEDGE_ROOT", tmp_path / "knowledge")
    owner = "tester"
    nodes = {
        "paper:PAPER1": KnowledgeNode(
            id="paper:PAPER1",
            type="paper",
            title="Sleep deprivation and cognition",
            snippet="sleep deprivation methods in humans",
            meta={"zotero_key": "PAPER1", "authors": "Smith", "year": "2024"},
        ).to_dict(),
    }
    save_graph(owner, nodes, [])

    with patch(
        "src.knowledge_graph.read_knowledge_content",
        return_value={
            "exit_code": 0,
            "body": "Detailed sleep protocol.",
            "meta": {"zotero_key": "PAPER1"},
        },
    ):
        outcome = research_knowledge_findings("sleep deprivation", owner, limit=3)

    assert outcome.source == "graph_search"
    assert len(outcome.findings) == 1
    assert outcome.findings[0]["title"] == "Sleep deprivation and cognition"
    assert outcome.findings[0]["graph_source"] == "graph_search"


def test_research_knowledge_neighbors_from_seed_paper(tmp_path, monkeypatch):
    monkeypatch.setattr("src.knowledge_graph.KNOWLEDGE_ROOT", tmp_path / "knowledge")
    owner = "tester"
    paper_id = node_id("paper", "SEED1")
    doc_id = node_id("document", "doc-1")
    nodes = {
        paper_id: KnowledgeNode(
            id=paper_id,
            type="paper",
            title="Seed paper",
            snippet="seed abstract",
            meta={"zotero_key": "SEED1"},
        ).to_dict(),
        doc_id: KnowledgeNode(
            id=doc_id,
            type="document",
            title="Related lab note",
            snippet="linked methods",
        ).to_dict(),
    }
    edges = [KnowledgeEdge(paper_id, doc_id, "related").to_dict()]
    save_graph(owner, nodes, edges)

    seed = [{"paper_key": "SEED1", "zotero_key": "SEED1", "title": "Seed paper"}]

    with patch(
        "src.knowledge_graph.read_knowledge_content",
        return_value={"exit_code": 0, "body": "Neighbor body.", "meta": {}},
    ):
        outcome = research_knowledge_findings("", owner, seed_findings=seed, limit=5)

    titles = {f["title"] for f in outcome.findings}
    assert "Related lab note" in titles
    neighbor = next(f for f in outcome.findings if f["title"] == "Related lab note")
    assert neighbor["graph_source"] == "graph_neighbor"
    assert source_id_for_finding(neighbor) == "src:graph:document:doc-1"


def test_research_knowledge_collection_siblings(tmp_path, monkeypatch):
    monkeypatch.setattr("src.knowledge_graph.KNOWLEDGE_ROOT", tmp_path / "knowledge")
    monkeypatch.setattr("src.zotero_catalog.ZOTERO_ROOT", tmp_path / "zotero")
    owner = "tester"
    _write_catalog(
        tmp_path,
        owner,
        [
            {
                "zotero_key": "SEED1",
                "title": "Seed paper",
                "abstract": "seed",
                "collection_keys": ["COL1"],
                "collection_paths": ["Reading"],
                "has_pdf": False,
            },
            {
                "zotero_key": "SIB1",
                "title": "Sibling paper",
                "abstract": "sibling in same collection",
                "collection_keys": ["COL1"],
                "collection_paths": ["Reading"],
                "has_pdf": False,
            },
        ],
        collections=[{"key": "COL1", "path": "Reading", "name": "Reading", "parent": ""}],
    )

    paper_seed = node_id("paper", "SEED1")
    paper_sib = node_id("paper", "SIB1")
    nodes = {
        paper_seed: KnowledgeNode(
            id=paper_seed,
            type="paper",
            title="Seed paper",
            snippet="seed",
            meta={"zotero_key": "SEED1", "collection_keys": ["COL1"], "collection_paths": ["Reading"]},
        ).to_dict(),
        paper_sib: KnowledgeNode(
            id=paper_sib,
            type="paper",
            title="Sibling paper",
            snippet="sibling",
            meta={"zotero_key": "SIB1", "collection_keys": ["COL1"], "collection_paths": ["Reading"]},
        ).to_dict(),
    }
    save_graph(owner, nodes, [])

    seed = [{
        "paper_key": "SEED1",
        "zotero_key": "SEED1",
        "collection_keys": ["COL1"],
        "collection_paths": ["Reading"],
    }]

    with patch(
        "src.knowledge_graph.read_knowledge_content",
        return_value={"exit_code": 0, "body": "Sibling abstract.", "meta": {"zotero_key": "SIB1"}},
    ):
        outcome = research_knowledge_findings("", owner, seed_findings=seed, limit=5)

    sib = next((f for f in outcome.findings if f.get("paper_key") == "SIB1"), None)
    assert sib is not None
    assert sib["graph_source"] == "collection"


def test_research_knowledge_collection_siblings_require_topic_overlap(tmp_path, monkeypatch):
    monkeypatch.setattr("src.knowledge_graph.KNOWLEDGE_ROOT", tmp_path / "knowledge")
    monkeypatch.setattr("src.zotero_catalog.ZOTERO_ROOT", tmp_path / "zotero")
    owner = "tester"
    _write_catalog(
        tmp_path,
        owner,
        [
            {
                "zotero_key": "SEED1",
                "title": "AlphaFold protein structure",
                "abstract": "protein structure prediction",
                "collection_keys": ["COL1"],
                "collection_paths": ["Reading"],
                "has_pdf": False,
            },
            {
                "zotero_key": "SIB1",
                "title": "Astronomy survey techniques",
                "abstract": "telescope observing schedule",
                "collection_keys": ["COL1"],
                "collection_paths": ["Reading"],
                "has_pdf": False,
            },
        ],
        collections=[{"key": "COL1", "path": "Reading", "name": "Reading", "parent": ""}],
    )

    paper_seed = node_id("paper", "SEED1")
    paper_sib = node_id("paper", "SIB1")
    nodes = {
        paper_seed: KnowledgeNode(
            id=paper_seed,
            type="paper",
            title="AlphaFold protein structure",
            snippet="protein structure prediction",
            meta={"zotero_key": "SEED1", "collection_keys": ["COL1"], "collection_paths": ["Reading"]},
        ).to_dict(),
        paper_sib: KnowledgeNode(
            id=paper_sib,
            type="paper",
            title="Astronomy survey techniques",
            snippet="telescope observing schedule",
            meta={"zotero_key": "SIB1", "collection_keys": ["COL1"], "collection_paths": ["Reading"]},
        ).to_dict(),
    }
    save_graph(owner, nodes, [])

    seed = [{
        "paper_key": "SEED1",
        "zotero_key": "SEED1",
        "collection_keys": ["COL1"],
        "collection_paths": ["Reading"],
    }]

    with patch(
        "src.knowledge_graph.read_knowledge_content",
        return_value={"exit_code": 0, "body": "Sibling abstract.", "meta": {"zotero_key": "SIB1"}},
    ):
        outcome = research_knowledge_findings(
            "",
            owner,
            seed_findings=seed,
            limit=5,
            relevance_query="protein structure prediction alphafold",
        )

    keys = {f.get("paper_key") for f in outcome.findings}
    assert "SIB1" not in keys
    for finding in outcome.findings:
        assert "astronomy" not in (finding.get("title") or "").lower()


def test_research_knowledge_filters_unrelated_graph_hits(tmp_path, monkeypatch):
    monkeypatch.setattr("src.knowledge_graph.KNOWLEDGE_ROOT", tmp_path / "knowledge")
    owner = "tester"
    nodes = {
        "document:astro": {
            "id": "document:astro",
            "type": "document",
            "title": "Astronomy club notes",
            "snippet": "telescope observing schedule",
        },
        "paper:PAPER1": {
            "id": "paper:PAPER1",
            "type": "paper",
            "title": "AlphaFold protein structure prediction",
            "snippet": "protein structure prediction benchmark",
            "meta": {"zotero_key": "PAPER1"},
        },
    }
    save_graph(owner, nodes, [])

    with patch(
        "src.knowledge_graph.read_knowledge_content",
        return_value={"exit_code": 0, "body": "Body text.", "meta": {}},
    ):
        outcome = research_knowledge_findings(
            "protein structure prediction alphafold",
            owner,
            limit=5,
            relevance_query="protein structure prediction alphafold",
        )

    titles = {f["title"] for f in outcome.findings}
    assert "AlphaFold protein structure prediction" in titles
    assert "Astronomy club notes" not in titles


def test_research_knowledge_finds_document_by_body_term(tmp_path, monkeypatch):
    monkeypatch.setattr("src.knowledge_graph.KNOWLEDGE_ROOT", tmp_path / "knowledge")
    owner = "tester"
    doc_id = node_id("document", "vault:notes.md")
    nodes = {
        doc_id: KnowledgeNode(
            id=doc_id,
            type="document",
            title="Research notes",
            snippet="General notes about methods",
        ).to_dict(),
    }
    save_graph(owner, nodes, [])

    seed = [{
        "is_seed": True,
        "paper_key": "SEED1",
        "title": "Evolutionary-scale prediction with ESM3",
        "summary": "ESM3 protein language model",
    }]

    def _read(owner_arg, nid, **kwargs):
        if nid == doc_id:
            return {
                "exit_code": 0,
                "body": "Detailed comparison of ESM3 vs AlphaFold on structure benchmarks.",
                "meta": {},
            }
        return {"exit_code": 0, "body": "", "meta": {}}

    with patch("src.knowledge_graph.read_knowledge_content", side_effect=_read):
        outcome = research_knowledge_findings(
            "Compare AlphaFold and ESM3",
            owner,
            seed_findings=seed,
            limit=5,
            relevance_query="compare alphafold esm3 protein structure prediction",
        )

    titles = {f["title"] for f in outcome.findings}
    assert "Research notes" in titles


def test_research_evidence_gatherer_delegates():
    gatherer = ResearchEvidenceGatherer()
    with patch("src.research_web_search.research_web_search") as mock_web:
        mock_web.return_value = type("O", (), {"results": [], "error": "", "provider": "test"})()
        gatherer.web_search("query", search_kind="discovery")
        mock_web.assert_called_once()

    with patch("src.research_zotero.research_zotero_findings") as mock_z:
        mock_z.return_value = type("O", (), {"findings": []})()
        gatherer.zotero("query", "owner")
        mock_z.assert_called_once()

    with patch("src.research_knowledge.research_knowledge_findings") as mock_k:
        mock_k.return_value = type("O", (), {"findings": []})()
        gatherer.knowledge("query", "owner")
        mock_k.assert_called_once()
