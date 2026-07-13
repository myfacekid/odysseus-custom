"""Paper section parsing and lookup (Paper Token Retrieval R1).

Regex + heading heuristics on PDF-extracted plain text. See docs/paper-token-retrieval-roadmap_v1.md.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

# Canonical slug → heading phrases (lowercase)
SECTION_ALIASES: Dict[str, Tuple[str, ...]] = {
    "introduction": ("introduction", "intro", "background", "related work", "literature review"),
    "methods": (
        "methods",
        "materials and methods",
        "materials & methods",
        "methodology",
        "experimental setup",
        "materials",
        "experimental procedures",
    ),
    "results": ("results", "findings", "experiments", "experimental results"),
    "discussion": ("discussion", "conclusions", "conclusion", "concluding remarks", "concluding remarks"),
    "limitations": ("limitations", "limitation"),
    "abstract": ("abstract",),
}


def list_section_slugs() -> List[str]:
    return list(SECTION_ALIASES.keys())


def normalize_section_slug(query: str) -> Optional[str]:
    """Map user/agent section string to a canonical slug."""
    q = (query or "").strip().lower()
    if not q:
        return None
    q = re.sub(r"\s+", " ", q)
    for slug, aliases in SECTION_ALIASES.items():
        if q == slug:
            return slug
        for alias in aliases:
            if q == alias or alias in q or q in alias:
                return slug
    return None


def section_display_label(slug: str) -> str:
    return slug.replace("_", " ").title()


def _clean_heading_title(line: str) -> str:
    title = re.sub(r"^\s*\d+\.?\s*", "", line.strip())
    title = re.sub(r"^#+\s*", "", title)
    return re.sub(r"\s+", " ", title).strip()


def _line_looks_like_heading(line: str) -> bool:
    s = line.strip()
    if not s or len(s) > 120:
        return False
    words = s.split()
    if len(words) > 12:
        return False
    if re.match(r"^\d+\.?\s+[A-Za-z]", s):
        return True
    letters = [c for c in s if c.isalpha()]
    if letters and sum(1 for c in letters if c.isupper()) / len(letters) > 0.85 and len(s) >= 4:
        return True
    if s.istitle() and len(words) <= 8:
        return True
    return False


def _heading_to_slug(line: str) -> Optional[str]:
    title = _clean_heading_title(line).lower()
    if not title:
        return None
    slug = normalize_section_slug(title)
    if slug:
        return slug
    # Strip trailing punctuation common in PDF extracts
    title = title.rstrip(".:-—")
    return normalize_section_slug(title)


def parse_pdf_sections(full_text: str) -> Dict[str, str]:
    """Split PDF plain text into canonical section bodies.

    Returns slug → body text. Empty dict when no headings detected.
    """
    text = (full_text or "").replace("\r\n", "\n").replace("\r", "\n")
    if not text.strip():
        return {}

    lines = text.split("\n")
    sections: Dict[str, List[str]] = {}
    current_slug: Optional[str] = None

    for line in lines:
        if _line_looks_like_heading(line):
            slug = _heading_to_slug(line)
            if slug and slug != "abstract":
                current_slug = slug
                sections.setdefault(slug, [])
                continue
        if current_slug:
            sections[current_slug].append(line)

    out: Dict[str, str] = {}
    for slug, body_lines in sections.items():
        body = "\n".join(body_lines).strip()
        if body:
            out[slug] = body
    return out


def extract_section_text(
    full_text: str,
    section_query: str,
    *,
    max_chars: int = 8000,
) -> Tuple[str, Optional[str], List[str]]:
    """Extract one section from full PDF text.

    Returns (text, matched_slug, available_slugs).
    """
    slug = normalize_section_slug(section_query)
    if not slug:
        return "", None, []

    parsed = parse_pdf_sections(full_text)
    available = sorted(parsed.keys())
    if not parsed:
        return "", None, available

    body = parsed.get(slug, "")
    if not body:
        return "", None, available

    if len(body) > max_chars:
        body = body[:max_chars] + "\n… [section truncated]"
    return body, slug, available
