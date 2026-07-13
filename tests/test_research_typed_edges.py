"""Deep Research typed graph edges (T3)."""

import json
from pathlib import Path

from src.research_typed_edges import build_research_graph_edges


def test_build_research_graph_edges_compare_mode():
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" / "research" / "compare_alphafold_esm.json").read_text(
            encoding="utf-8"
        )
    )
    edges = build_research_graph_edges("fixture-compare-alphafold-esm", fixture)
    assert edges
    research_edges = [e for e in edges if e["from"].startswith("research:")]
    assert research_edges
    assert all(e["kind"] in {"relates", "supports", "refutes", "derives_from", "depends_on"} for e in edges)
    assert all(e.get("reason") for e in edges)
    paper_pairs = [e for e in edges if e["from"].startswith("paper:") and e["to"].startswith("paper:")]
    assert paper_pairs
