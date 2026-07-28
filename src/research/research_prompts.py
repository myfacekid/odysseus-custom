"""Shared research prompts and report specs (LDR + IterResearch)."""
from __future__ import annotations

from datetime import datetime


def current_date_context() -> str:
    """Preamble that grounds query-generation/planning LLMs in the real current date."""
    now = datetime.now().astimezone()
    return (
        f"Today's date is {now.strftime('%B %d, %Y')} ({now.strftime('%Y-%m-%d')}). "
        f"Use the correct calendar year only when the user asks for recent, current, "
        f"or time-bounded literature — do not bias searches toward the latest papers "
        f"by default. Never infer a year from training data.\n\n"
    )


RESEARCH_PLAN_PROMPT = """\
You are an academic research strategist preparing a scholarly literature review plan.

**Research question:** {question}

Break this question down for rigorous academic investigation:
1. What sub-questions must be answered from primary literature?
2. What study types matter (systematic reviews, RCTs, meta-analyses, cohort studies)?
3. What would a scientifically sound synthesis include — including gaps and limitations?

Also derive retrieval parameters so search and relevance gating stay on-topic.
Keep these three lists DISTINCT — do not copy the same phrases into each field:

- **anchor_terms**: Short named entities that fence relevance (model names, tool names,
  acronyms, method brands). Prefer 1–3 token proper nouns / acronyms from the question
  and seeds. Used as a hard on-topic filter — papers should mention these.
- **key_topics**: Broader thematic coverage goals for the synthesis (concepts, mechanisms,
  study populations, outcome classes). Phrases, not product names. Should NOT be a copy
  of anchor_terms. Ask: "what themes must the final review cover?"
- **search_keywords**: Query strings for academic APIs. May mix anchors + topical phrases.
- **avoid_topics**: Unrelated subfields that share broad vocabulary and should be rejected.

Return a JSON object with:
- "sub_questions": Array of 3-6 specific scholarly sub-questions
- "key_topics": 3–6 thematic coverage phrases (concepts/populations — not the same as anchors)
- "success_criteria": One sentence describing what a complete academic answer looks like
- "anchor_terms": 3–8 distinctive named entities for relevance gating
- "search_keywords": Keywords for academic search APIs (may overlap anchor_terms)
- "scope": One of "narrow_compare", "field_overview", "gap_analysis", "balanced"
- "must_stay_close_to_seeds": true when the question compares or builds on specific seed papers
- "foundational_ok": true when broad background and classic papers are appropriate
- "expansion_queries": 2-6 ready-to-run PubMed/Scholar query strings
- "avoid_topics": Phrases for unrelated subfields to reject (e.g. "gene ontology" for a structure-compare question)
- "openalex_search_queries": Optional OpenAlex keyword queries (defaults to search_keywords)

Example (note anchors ≠ topics):
{{
  "sub_questions": ["How does method A represent structure?", "How does method B search structure space?"],
  "key_topics": ["structural alphabet", "search space coverage", "representation trade-offs"],
  "success_criteria": "A comparison grounded in the named methods with explicit limitations.",
  "anchor_terms": ["foldseek", "esm3", "3di"],
  "search_keywords": ["foldseek", "esm3", "3di", "structure representation", "structural alphabet"],
  "scope": "narrow_compare",
  "must_stay_close_to_seeds": true,
  "foundational_ok": false,
  "expansion_queries": [
    "Foldseek 3Di structural alphabet site:pubmed.ncbi.nlm.nih.gov",
    "ESM3 protein structure representation site:scholar.google.com"
  ],
  "avoid_topics": ["gene ontology", "protein function prediction", "multi-label classification"],
  "openalex_search_queries": ["foldseek structure search", "esm3 structure representation"]
}}
"""

MODE_PLAN_CONTEXT = {
    "literature_review": (
        "Mode: literature review — synthesize the user's seed papers (if any) with related "
        "peer-reviewed work and reviews."
    ),
    "similar_papers": (
        "Mode: similar papers — prioritize finding, reading, and summarizing work related to "
        "the seed papers; de-emphasize generic background."
    ),
    "gap_analysis": (
        "Mode: gap analysis — identify what the seed papers do NOT cover; search for missing "
        "populations, methods, outcomes, and contradictory evidence."
    ),
    "compare": (
        "Mode: compare — contrast methods, findings, limitations, and conclusions across "
        "two or more seed papers explicitly."
    ),
}

REPORT_LENGTH_SPECS = {
    "standard": {"min_words": 1200, "expand_threshold": 400},
    "extended": {"min_words": 3000, "expand_threshold": 1200},
}
