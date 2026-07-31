"""Paper Token Retrieval (Phase R0–R1) — tier defaults, caps, and section constants.
"""

from __future__ import annotations

# Tier 1 — abstract + metadata (default agent read on paper:… nodes)
PAPER_READ_DEFAULT_MAX_CHARS = 3000
PAPER_READ_DEFAULT_INCLUDE_PDF = False

# Tier 3 — full PDF extraction ceiling (policy cap per call)
PAPER_PDF_MAX_CHARS = 25000

# Tier 2 — single section extraction
PAPER_SECTION_DEFAULT_MAX_CHARS = 8000
PAPER_SECTION_PARSE_MAX_CHARS = 120000

# Non-paper knowledge read default
NON_PAPER_READ_DEFAULT_MAX_CHARS = 8000
