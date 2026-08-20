"""Phase 3 — registry hardening, mode templates, thematic clustering, evidence tables."""

from src.research_evidence import EvidenceRegistry
from src.research_finding_enrich import (
    enrich_web_finding,
    extract_doi,
    infer_peer_review_status,
    normalize_finding_fields,
)
from src.research_templates import (
    build_final_report_prompt,
    normalize_mode,
    section_headings,
)
from src.research_synthesis import (
    build_evidence_table,
    build_thematic_outline_prompt,
    combine_final_context_blocks,
    format_thematic_outline,
    heuristic_thematic_outline,
    should_cluster_thematically,
    should_include_evidence_table,
)


def test_extract_doi_from_url():
    assert extract_doi("https://doi.org/10.1234/abc.def") == "10.1234/abc.def"
    assert extract_doi("doi:10.5555/xyz") == "10.5555/xyz"
    assert extract_doi("https://www.science.org/doi/10.1126/science.ade2574") == "10.1126/science.ade2574"


def test_infer_preprint_from_arxiv():
    assert infer_peer_review_status("https://arxiv.org/abs/1234.5678") == "preprint"
    assert infer_peer_review_status("https://doi.org/10.1234/journal") == "peer-reviewed"


def test_normalize_finding_fields_strips_unknown_quant():
    f = normalize_finding_fields({
        "url": "https://example.com",
        "sample_size": "unknown",
        "effect_size": "N=50",
    })
    assert f["sample_size"] == ""
    assert f["effect_size"] == "N=50"


def test_enrich_web_finding_sets_doi_and_preprint():
    f = enrich_web_finding(
        {"title": "Paper", "summary": "Results"},
        url="https://arxiv.org/pdf/1234.pdf",
        content="See doi:10.1234/embedded",
    )
    assert f["peer_review_status"] == "preprint"
    assert f["doi_or_id"] == "10.1234/embedded"


def test_registry_stores_quantitative_fields():
    reg = EvidenceRegistry()
    num = reg.register({
        "url": "https://ex.com/a",
        "title": "Trial A",
        "sample_size": "N=120",
        "effect_size": "OR 0.8",
        "outcome": "mortality",
    })
    src = reg.get(reg.sources()[0].source_id)
    assert src.sample_size == "N=120"
    assert src.effect_size == "OR 0.8"
    assert src.outcome == "mortality"
    block = reg.quantitative_evidence_block()
    assert "[1]" in block
    assert "N=120" in block


def test_registry_merge_quantitative_on_reregister():
    reg = EvidenceRegistry()
    reg.register({"url": "https://ex.com/a", "title": "Trial A"})
    reg.register({
        "url": "https://ex.com/a",
        "title": "Trial A",
        "sample_size": "N=40",
    })
    src = reg.sources()[0]
    assert src.sample_size == "N=40"


def test_compare_mode_template_sections():
    sections = section_headings("compare")
    assert "Methods Comparison" in sections
    assert "Findings Comparison" in sections


def test_build_final_report_prompt_includes_mode_focus():
    prompt = build_final_report_prompt(
        question="How do A and B differ?",
        report="Draft",
        min_words=1200,
        mode="compare",
    )
    assert "comparative synthesis" in prompt.lower()
    assert "Methods Comparison" in prompt
    assert "Source notes (not the report)" in prompt
    assert "draft synthesis" not in prompt.lower()
    assert "Do NOT copy" in prompt
    assert normalize_mode("invalid") == "literature_review"


def test_gap_analysis_template_differs_from_literature_review():
    lit = section_headings("literature_review")
    gap = section_headings("gap_analysis")
    assert "Identified Gaps" in gap
    assert "Identified Gaps" not in lit


def _register_table_sources(reg: EvidenceRegistry):
    reg.register({
        "url": "https://ex.com/1",
        "title": "Trial One",
        "authors": "Smith et al.",
        "study_type": "RCT",
        "sample_size": "N=100",
        "outcome": "survival",
    })
    reg.register({
        "url": "https://ex.com/2",
        "title": "Cohort Study",
        "authors": "Jones",
        "study_type": "cohort",
        "sample_size": "N=500",
    })
    reg.register({
        "url": "https://ex.com/3",
        "title": "Review",
        "authors": "Lee",
        "study_type": "systematic review",
    })


def test_evidence_table_requires_three_sources():
    reg = EvidenceRegistry()
    assert not should_include_evidence_table(reg)
    _register_table_sources(reg)
    assert should_include_evidence_table(reg)
    table = build_evidence_table(reg)
    assert "| Study | Design | N | Outcome | Ref |" in table
    assert "Smith et al." in table
    assert "N=100" in table
    assert "[1]" in table
    assert "—" in table  # missing outcome on row 2


def test_thematic_clustering_threshold():
    reg = EvidenceRegistry()
    assert not should_cluster_thematically(reg)
    for i in range(5):
        reg.register({"url": f"https://ex.com/{i}", "title": f"Paper {i}"})
    assert should_cluster_thematically(reg)


def test_thematic_outline_prompt_lists_sources():
    reg = EvidenceRegistry()
    reg.register({"url": "https://ex.com/a", "title": "Alpha", "summary": "Methods trial"})
    prompt = build_thematic_outline_prompt(
        "What works?",
        reg,
        [{"citation_num": 1, "summary": "Methods trial"}],
    )
    assert "[1]" in prompt
    assert "Alpha" in prompt
    assert "What works?" in prompt


def test_format_thematic_outline_wraps_llm_output():
    raw = "### Theme: Interventions\n- [1] — primary trial"
    formatted = format_thematic_outline(raw)
    assert "Thematic outline" in formatted
    assert "### Theme: Interventions" in formatted


def test_heuristic_thematic_outline_groups_by_study_type():
    reg = EvidenceRegistry()
    reg.register({"url": "https://ex.com/a", "title": "A", "study_type": "RCT"})
    reg.register({"url": "https://ex.com/b", "title": "B", "study_type": "RCT"})
    reg.register({"url": "https://ex.com/c", "title": "C", "study_type": "review"})
    outline = heuristic_thematic_outline(reg)
    assert "RCT" in outline
    assert "[1]" in outline
    assert "[3]" in outline


def test_combine_final_context_blocks():
    combined = combine_final_context_blocks("outline text", "table text")
    assert "outline text" in combined
    assert "table text" in combined
    assert combine_final_context_blocks("", "") == ""

