#!/usr/bin/env python3
"""Smoke test for LDR full-text escalation ladder (Phase L7).

Exercises known DOIs from the Foldseek E2E run without a full LangGraph gather.
Requires network for live API/PDF fetches.

Usage:
  python scripts/ldr_fulltext_smoke.py
  python scripts/ldr_fulltext_smoke.py --doi 10.1038/s41587-023-01773-0
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Foldseek E2E anchors — papers the agent identified but often failed to fetch.
DEFAULT_DOIS = [
    ("10.1038/s41587-023-01773-0", "Foldseek Nature Biotech"),
    ("10.1038/s41586-023-06510-w", "AFDB clustering"),
    ("10.1126/science.adl5899", "ESM3 Science (PubMed abstract)"),
]


def _check_doi(doi: str, label: str) -> tuple[bool, bool, str]:
    from src.research.ldr_fulltext_escalate import escalate_fulltext_by_doi

    resolved = escalate_fulltext_by_doi(doi, title=label, fetch_fulltext=True)
    abstract = (resolved.get("abstract") or "").strip()
    fulltext = (resolved.get("fulltext") or "").strip()
    abstract_ok = len(abstract) >= 400
    full_ok = len(fulltext) >= 900
    detail = (
        f"abstract={len(abstract)} chars ({resolved.get('source', 'none')})"
        f" fulltext={len(fulltext)} chars"
    )
    if fulltext:
        detail += f" via {resolved.get('source_url', '')[:60]}"
    return abstract_ok, full_ok, detail


def main() -> int:
    parser = argparse.ArgumentParser(description="LDR full-text escalation smoke test")
    parser.add_argument("--doi", action="append", default=[], help="Extra DOI to test (repeatable)")
    args = parser.parse_args()

    cases = list(DEFAULT_DOIS)
    for raw in args.doi:
        cases.append((raw.strip(), raw.strip()))

    abstract_hits = 0
    full_hits = 0
    print(f"Testing {len(cases)} DOI(s)…\n")
    for doi, label in cases:
        try:
            abstract_ok, full_ok, detail = _check_doi(doi, label)
        except Exception as exc:
            print(f"FAIL {doi} ({label}): {exc}")
            continue
        abstract_hits += int(abstract_ok)
        full_hits += int(full_ok)
        status = "OK" if abstract_ok or full_ok else "MISS"
        print(f"{status} {doi}")
        print(f"     {label}")
        print(f"     {detail}\n")

    n = len(cases) or 1
    print(f"Abstract ≥400 chars: {abstract_hits}/{n}")
    print(f"Full text ≥900 chars: {full_hits}/{n}")

    try:
        import pypdf  # noqa: F401
        has_pypdf = True
    except ImportError:
        has_pypdf = False
        print("\nNote: pypdf not installed — skipping full-text pass gate")

    # Initial L7 pass criteria (see docs/deep-research-ldr-migration.md Phase L7)
    if abstract_hits < max(1, (n * 2) // 3):
        print("\nWARN: abstract hit rate below 2/3 threshold")
        return 1
    if has_pypdf and full_hits < 1:
        print("\nWARN: no DOI resolved full text ≥900 chars")
        return 1
    print("\nPASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
