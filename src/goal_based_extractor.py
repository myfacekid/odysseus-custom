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

**Final Output Format — JSON with these fields:**
- "rational": Why this content is relevant
- "evidence": Full quotes and context (prefer verbatim for numbers and key claims)
- "summary": Concise synthesis of contribution to the goal
- "authors": Author names if found, else ""
- "year": Publication year if found, else ""
- "doi_or_id": DOI, PMID, or arXiv ID if found, else ""
- "study_type": One of: RCT, cohort, case-control, systematic_review, meta_analysis, review, opinion, preprint, other, unknown
- "peer_review_status": One of: peer_reviewed, preprint, unknown

Example output:
{{
    "rational": "This RCT directly tests the intervention described in the research goal",
    "evidence": "Full quotes including methods and key results...",
    "summary": "This source provides Level I evidence that...",
    "authors": "Smith et al.",
    "year": "2023",
    "doi_or_id": "10.1234/example",
    "study_type": "RCT",
    "peer_review_status": "peer_reviewed"
}}
"""
