"""Structured retrieval plan parsing and fallbacks."""

from src.research_retrieval_plan import (
    derive_retrieval_plan_fallback,
    parse_retrieval_plan,
    plan_to_display_text,
)


def test_derive_retrieval_plan_fallback_from_seeds():
    seeds = [
        {
            "is_seed": True,
            "title": "Fast and accurate protein structure search with Foldseek",
            "abstract": "Foldseek uses 3Di structural alphabet for ultrafast structure search.",
        },
    ]
    plan = derive_retrieval_plan_fallback(
        "Compare Foldseek and ESM3 structure representation",
        seeds,
        research_mode="compare",
    )
    assert plan.normalized_scope() == "narrow_compare"
    assert plan.must_stay_close_to_seeds
    assert "foldseek" in {t.lower() for t in plan.anchor_terms}
    assert plan.expansion_queries


def test_parse_retrieval_plan_merges_planner_json():
    seeds = [{"is_seed": True, "title": "ESM3 generative model", "abstract": "ESM3 protein"}]
    raw = {
        "sub_questions": ["How does ESM3 encode structure?"],
        "key_topics": ["structure representation"],
        "success_criteria": "Clear comparison.",
        "anchor_terms": ["esm3", "foldseek"],
        "search_keywords": ["esm3 structure", "foldseek 3di"],
        "scope": "narrow_compare",
        "must_stay_close_to_seeds": True,
        "foundational_ok": False,
        "expansion_queries": ["ESM3 structure site:pubmed.ncbi.nlm.nih.gov"],
        "avoid_topics": ["gene ontology", "protein function prediction"],
    }
    plan = parse_retrieval_plan(raw, "Compare ESM3 and Foldseek", seeds, research_mode="compare")
    assert plan.sub_questions == ["How does ESM3 encode structure?"]
    assert plan.key_topics == ["structure representation"]
    assert "gene ontology" in plan.avoid_topics
    assert plan.expansion_queries[0].startswith("ESM3")
    text = plan_to_display_text(plan)
    assert "Avoid topics" in text
    assert "narrow_compare" in text


def test_parse_retrieval_plan_drops_key_topics_copied_from_anchors():
    raw = {
        "key_topics": ["Foldseek", "esm3", "search space coverage"],
        "anchor_terms": ["foldseek", "esm3", "3di"],
        "search_keywords": ["foldseek structure"],
    }
    plan = parse_retrieval_plan(raw, "Compare Foldseek and ESM3", [], research_mode="compare")
    assert plan.key_topics == ["search space coverage"]
    assert "foldseek" in {t.lower() for t in plan.anchor_terms}


def test_plan_to_dict_roundtrip_fields():
    plan = derive_retrieval_plan_fallback(
        "Foldseek protein search",
        [],
        research_mode="literature_review",
    )
    from src.research_retrieval_plan import plan_to_dict

    data = plan_to_dict(plan)
    assert "search_keywords" in data
    assert "scope" in data
    assert data["scope"] in ("balanced", "narrow_compare", "gap_analysis", "field_overview")


def test_parse_retrieval_plan_falls_back_on_empty_json():
    plan = parse_retrieval_plan(None, "RNA folding thermodynamics", [], research_mode="literature_review")
    assert plan.normalized_scope() == "balanced"
    assert plan.search_keywords
