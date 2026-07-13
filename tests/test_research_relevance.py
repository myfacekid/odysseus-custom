"""Relevance gating for Deep Research evidence."""

from src.research_relevance import (
    build_relevance_query,
    extract_anchor_terms,
    filter_relevant_findings,
    heuristic_relevance_decision,
    is_extraction_irrelevant,
    is_finding_relevant,
    is_similar_paper_relevant,
    matches_avoid_topics,
    parse_relevance_yes_no,
    score_search_result,
    score_text_relevance,
    seed_knowledge_queries,
)


def test_score_text_relevance_requires_multiple_token_hits():
    q = "protein structure prediction alphafold"
    assert score_text_relevance("AlphaFold improves protein structure prediction", q) > 0.3
    assert score_text_relevance("Task management tips for astronomy clubs", q) < 0.15


def test_is_extraction_irrelevant_honors_flag_and_markers():
    assert is_extraction_irrelevant({"relevant": False, "summary": "Some text"})
    assert is_extraction_irrelevant({
        "relevant": True,
        "rational": "This page is completely unrelated to protein folding",
        "summary": "Astronomy overview",
    })
    assert not is_extraction_irrelevant({
        "relevant": True,
        "rational": "Directly discusses CASP15 protein structure benchmarks",
        "summary": "Benchmark results for structure prediction",
    })


def test_filter_relevant_findings_keeps_seeds():
    findings = [
        {"title": "Unrelated astronomy", "summary": "Stars and galaxies", "is_seed": True},
        {"title": "Off topic blog", "summary": "Cooking recipes"},
        {
            "title": "AlphaFold2 accuracy",
            "summary": "Protein structure prediction benchmark results",
        },
    ]
    kept = filter_relevant_findings(
        findings,
        "protein structure prediction alphafold",
    )
    titles = {f["title"] for f in kept}
    assert "Unrelated astronomy" in titles
    assert "AlphaFold2 accuracy" in titles
    assert "Off topic blog" not in titles


def test_score_search_result_uses_title_and_snippet():
    result = {
        "title": "CASP15 assessment of protein structure prediction",
        "content": "Methods for evaluating structure prediction accuracy",
    }
    assert score_search_result(result, "protein structure prediction CASP15") > 0.2
    assert score_search_result(result, "quantum computing qubits") < 0.15


def test_is_finding_relevant_respects_seed_flag():
    finding = {"title": "Astronomy", "summary": "Stars only", "is_seed": True}
    assert is_finding_relevant(finding, "protein folding")


def test_parse_relevance_yes_no():
    assert parse_relevance_yes_no("YES") is True
    assert parse_relevance_yes_no("NO — off topic") is False
    assert parse_relevance_yes_no("maybe") is None


def test_heuristic_relevance_decision():
    q = "protein structure prediction alphafold"
    assert heuristic_relevance_decision("AlphaFold2", "protein structure prediction", q) is True
    assert heuristic_relevance_decision("Astronomy club", "telescope schedule", q) is False
    assert heuristic_relevance_decision("Methods paper", "structure analysis methods", q) is False


def test_extract_anchor_terms_finds_model_names():
    terms = extract_anchor_terms(
        "Compare AlphaFold and ESM3 protein structure prediction",
        "Evolutionary-scale prediction with ESM3 language model",
    )
    assert "alphafold" in terms
    assert "esm3" in terms


def test_extract_anchor_terms_excludes_author_names():
    terms = extract_anchor_terms(
        "Highly accurate protein structure prediction with AlphaFold",
        exclude_terms={"jumper", "evans", "pritzel"},
    )
    assert "alphafold" in terms
    assert "jumper" not in terms
    assert "evans" not in terms


def test_build_relevance_query_includes_seed_titles():
    seeds = [{"is_seed": True, "title": "AlphaFold structure prediction", "summary": "CASP14 results"}]
    q = build_relevance_query("Compare AlphaFold and ESM3", seed_findings=seeds)
    assert "alphafold" in q.lower()
    assert "casp14" in q.lower()


def test_matches_avoid_topics_rejects_fusego():
    finding = {
        "title": "FuseGO",
        "summary": "Gene Ontology protein function prediction with language models.",
    }
    assert matches_avoid_topics(finding, ["gene ontology", "protein function prediction"])
    assert not matches_avoid_topics(finding, ["quantum computing"])


def test_is_finding_relevant_uses_avoid_topics():
    finding = {
        "title": "FuseGO",
        "summary": "Gene Ontology multi-label protein function prediction.",
    }
    assert not is_finding_relevant(
        finding,
        "Compare Foldseek and ESM3 structure representation",
        avoid_topics=["gene ontology", "protein function prediction"],
    )


def test_is_similar_paper_relevant_rejects_fusego_for_structure_compare():
    """Regression: S2 co-citation PLM papers must not enter a structure-compare run."""
    q = (
        "Compare ESM3 and Foldseek protein structure representation, 3Di alphabet, "
        "and whether one uses structure as a search space."
    )
    seeds = [
        {
            "is_seed": True,
            "title": "Simulating 500 million years of evolution with a language model",
            "summary": "ESM3 generative language model protein structure function evolution",
        },
        {
            "is_seed": True,
            "title": "Fast and accurate protein structure search with Foldseek",
            "summary": "Foldseek 3Di structural alphabet ultrafast structure search",
        },
    ]
    fusego = {
        "title": "FuseGO",
        "summary": (
            "Gene Ontology protein function prediction using pretrained language models "
            "and fusion for multi-label classification."
        ),
    }
    assert not is_similar_paper_relevant(
        fusego,
        q,
        seeds,
        research_mode="compare",
        avoid_topics=["gene ontology", "protein function prediction"],
    )


def test_is_similar_paper_relevant_rejects_fusego_with_representation_word():
    """S2 abstract mentions 'representation' in GO sense — must not match structure query."""
    q = (
        "Compare ESM3 and Foldseek structure representation, 3Di alphabet, search space."
    )
    seeds = [
        {
            "is_seed": True,
            "title": "Fast and accurate protein structure search with Foldseek",
            "summary": "Foldseek 3Di structural alphabet ultrafast structure search",
        },
    ]
    fusego = {
        "title": "FuseGO",
        "summary": (
            "Proteins are the workhorses of life. Gene Ontology GO vocabularies. "
            "Recent advances in protein function representation using language models "
            "for multi-label classification."
        ),
    }
    assert not is_similar_paper_relevant(
        fusego,
        q,
        seeds,
        research_mode="compare",
        avoid_topics=["gene ontology"],
    )


def test_is_similar_paper_relevant_rejects_rna_paper():
    seeds = [{
        "is_seed": True,
        "title": "AlphaFold protein structure prediction",
        "summary": "atomic-level protein structure with language models",
    }]
    unrelated = {
        "title": "RNA folding nearest neighbor parameters",
        "summary": "1-methyl-pseudouridine RNA thermodynamics",
        "evidence": "RNA nearest neighbor parameters for modified bases",
    }
    assert not is_similar_paper_relevant(
        unrelated,
        "compare alphafold esm3 protein structure prediction",
        seeds,
    )


def test_seed_knowledge_queries_from_seeds():
    seeds = [
        {"is_seed": True, "title": "Highly accurate protein structure prediction with AlphaFold"},
        {"is_seed": True, "title": "Evolutionary-scale prediction with ESM3", "summary": "ESM3 generative model"},
    ]
    queries = seed_knowledge_queries("Compare AlphaFold and ESM3", seeds, limit=8)
    joined = " ".join(queries).lower()
    assert "alphafold" in joined
    assert "esm3" in joined
