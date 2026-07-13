"""Edge taxonomy tests (T0/T3)."""

from src.edge_taxonomy import (
    format_edge_for_agent,
    infer_stance_from_text,
    is_inhibitory_kind,
    normalize_semantic_kind,
)


def test_normalize_semantic_kind_maps_legacy():
    assert normalize_semantic_kind("link") == "relates"
    assert normalize_semantic_kind("related") == "relates"
    assert normalize_semantic_kind("derives_from") == "derives_from"


def test_infer_stance_refutes_from_contrast():
    kind, reason = infer_stance_from_text(
        "AlphaFold remains accurate; however ESMFold challenges the MSA requirement.",
        anchor="ESMFold",
    )
    assert kind == "refutes"
    assert reason


def test_format_edge_for_agent_marks_inhibitory():
    out = format_edge_for_agent("refutes", reason="Contradicts prior claim")
    assert "INHIBITORY" in out
    assert is_inhibitory_kind("refutes")
