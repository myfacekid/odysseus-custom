"""Mode-aware academic report templates for Deep Research (Phase 3b)."""
from __future__ import annotations

from typing import Dict, List

RESEARCH_MODES = frozenset({
    "literature_review",
    "similar_papers",
    "gap_analysis",
    "compare",
})

_SHARED_REQUIREMENTS = """\
- Write at MINIMUM {min_words} words — thorough but scientifically precise, not promotional
- Use numbered inline citations [1], [2], etc. for every substantive claim
- Engage with EVERY gathered source that bears on the question — do not rely on
  only a handful. Integrate and cite all relevant sources from the evidence
  registry so the synthesis reflects the full body of retrieved literature
- Include specific data (effect sizes, sample sizes, p-values) ONLY when listed in the quantitative evidence block — never invent numbers
- Distinguish peer-reviewed sources from preprints where known
- Note where evidence is strong, weak, or absent
- If a source is marked metadata-only or retrieval-failed, do NOT describe its methods, results, or conclusions — state explicitly that full text was unavailable
- **Limitations of This Report** MUST list every source that could not be retrieved adequately (see source retrieval status block)
- End with a ## References section listing every cited source as:
  [N] Author et al. (Year). Title. Venue/Journal. URL or DOI
- Use cautious academic language — avoid overstating conclusions
"""

_MODE_TEMPLATES: Dict[str, dict] = {
    "literature_review": {
        "title": "literature synthesis",
        "sections": [
            "Executive Summary",
            "Background",
            "Key Findings",
            "Conflicting Evidence",
            "Limitations of the Evidence",
            "Limitations of This Report",
            "Conclusion",
            "References",
        ],
        "focus": (
            "Synthesize the research question across all gathered sources. "
            "Organize Key Findings by theme where possible."
        ),
    },
    "similar_papers": {
        "title": "related-work synthesis",
        "sections": [
            "Executive Summary",
            "Seed Papers Overview",
            "Related Work by Theme",
            "Methods and Designs",
            "Overlaps and Distinctions vs Seeds",
            "Limitations of the Evidence",
            "Limitations of This Report",
            "Conclusion",
            "References",
        ],
        "focus": (
            "Prioritize papers related to the user's seed papers. "
            "Explain why each related source matters and how it connects to the seeds."
        ),
    },
    "gap_analysis": {
        "title": "gap analysis",
        "sections": [
            "Executive Summary",
            "What the Seed Evidence Covers",
            "Identified Gaps",
            "Evidence Addressing Gaps",
            "Conflicting or Missing Evidence",
            "Limitations of the Evidence",
            "Limitations of This Report",
            "Conclusion",
            "References",
        ],
        "focus": (
            "Identify what the seed papers and gathered sources do NOT cover: "
            "populations, methods, outcomes, time periods, and contradictory findings."
        ),
    },
    "compare": {
        "title": "comparative synthesis",
        "sections": [
            "Executive Summary",
            "Papers Compared",
            "Methods Comparison",
            "Findings Comparison",
            "Limitations Compared",
            "Conflicting Evidence",
            "Limitations of This Report",
            "Conclusion",
            "References",
        ],
        "focus": (
            "Contrast the seed papers directly: methods, findings, limitations, and conclusions. "
            "Use parallel structure when comparing two or more seeds."
        ),
    },
}

ACADEMIC_REPORT_OVERRIDE = """\
IMPORTANT — this is exclusively an ACADEMIC research report:
- Prioritize primary literature, systematic reviews, and meta-analyses over secondary summaries
- Label preprints explicitly when used
- Never cite a source not present in the collected evidence
- The References section must match every [N] citation in the body
- Do NOT invent sample sizes, effect sizes, p-values, or confidence intervals unless they appear in the quantitative evidence block for that citation
- Do NOT infer what a paper concludes from its title, author names, or venue alone
- When a source lacks full text (metadata-only / retrieval-failed), cite it only to note its existence and state that substantive claims about that paper are omitted pending full text
- **Limitations of This Report** must explicitly name any such poorly sourced papers by citation number [N]
"""


def normalize_mode(mode: str) -> str:
    m = (mode or "literature_review").strip().lower()
    return m if m in RESEARCH_MODES else "literature_review"


def section_headings(mode: str) -> List[str]:
    return list(_MODE_TEMPLATES[normalize_mode(mode)]["sections"])


def build_final_report_prompt(
    *,
    question: str,
    report: str,
    min_words: int,
    mode: str = "literature_review",
) -> str:
    """Build the final-report LLM prompt for a research mode."""
    mode = normalize_mode(mode)
    spec = _MODE_TEMPLATES[mode]
    sections = ", ".join(f"## {s}" for s in spec["sections"] if s != "References")
    return f"""\
Write a rigorous **academic {spec['title']}** answering this research question:

**Question:** {question}

**Mode focus:** {spec['focus']}

**Collected evidence and draft synthesis:**
{report}

Requirements:
{_SHARED_REQUIREMENTS.format(min_words=min_words)}
- Begin the report with a single "# " top-level title on its own line that is
  SPECIFIC to this question and its findings (e.g. name the intervention,
  population, or debate). Do NOT use a generic word like "Report", "Background",
  "Summary", or a section name as the title.
- After the title, structure the body with clear ## headings: {sections}, References
"""


def expansion_user_message(min_words: int) -> str:
    return (
        "This academic synthesis is too brief. Expand it significantly:\n"
        "- Add detailed paragraphs for the main body sections\n"
        "- Include specific data from the quantitative evidence block only — do not invent statistics\n"
        "- Add Limitations of the Evidence and Limitations of This Report sections\n"
        "- Use numbered citations [1], [2] and a complete ## References section\n"
        f"- Target at least {max(min_words - 200, 800)} words\n"
        "Write the full expanded synthesis now."
    )
