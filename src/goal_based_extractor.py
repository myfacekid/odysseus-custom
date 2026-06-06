# src/goal_based_extractor.py
"""
Goal-based content extraction prompt for academic deep research.
"""

EXTRACTOR_PROMPT = """Please process the following scholarly webpage content and research goal to extract relevant academic information:

## **Webpage Content**
{webpage_content}

## **User Goal**
{goal}

## **Task Guidelines**
1. **Relevance**: Locate sections directly related to the research goal — methods, results, conclusions, limitations.
2. **Evidence**: Extract verbatim quotes for any statistics, effect sizes, sample sizes, p-values, or quantitative claims. Preserve author wording where possible.
3. **Metadata**: Identify authors, publication year, journal/venue, DOI or arXiv ID if visible on the page.
4. **Critical reading**: Note study design (RCT, cohort, review, meta-analysis, opinion), stated limitations, and whether the source appears peer-reviewed or a preprint.
5. **Summary**: Concise paragraph on how this source contributes to answering the goal.
6. **Thin pages**: If the page contains only a title, author list, or citation metadata with no abstract or body text, set `"relevant": false`, leave quantitative fields empty, and explain that substantive extraction is not possible without full text.

**Final Output Format — JSON with these fields:**
- "relevant": true if this page materially helps answer the research goal; false if off-topic, boilerplate, or unrelated (when false, other fields may be brief)
- "rational": Why this content is relevant (or why it is not, if relevant is false)
- "evidence": Full quotes and context (prefer verbatim for numbers and key claims)
- "summary": Concise synthesis of contribution to the goal
- "authors": Author names if found, else ""
- "year": Publication year if found, else ""
- "doi_or_id": DOI, PMID, or arXiv ID if found, else ""
- "study_type": One of: RCT, cohort, case-control, systematic_review, meta_analysis, review, opinion, preprint, other, unknown
- "peer_review_status": One of: peer_reviewed, preprint, unknown
- "sample_size": Sample size or N if stated (e.g. "N=120", "n=45 participants") — empty string if not found
- "effect_size": Effect size, OR, HR, RR, Cohen's d, etc. if stated — empty string if not found
- "outcome": Primary outcome measure if stated — empty string if not found
- "quality_notes": Brief note on study quality or risk of bias if mentioned — empty string if not found

Example output:
{{
    "relevant": true,
    "rational": "This RCT directly tests the intervention described in the research goal",
    "evidence": "Full quotes including methods and key results...",
    "summary": "This source provides Level I evidence that...",
    "authors": "Smith et al.",
    "year": "2023",
    "doi_or_id": "10.1234/example",
    "study_type": "RCT",
    "peer_review_status": "peer_reviewed",
    "sample_size": "N=120",
    "effect_size": "OR 0.72 (95% CI 0.55–0.94)",
    "outcome": "30-day mortality",
    "quality_notes": "Double-blind; low attrition"
}}
"""
