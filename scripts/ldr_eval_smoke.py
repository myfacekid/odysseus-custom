#!/usr/bin/env python3
"""Pre-flight evaluation bundle before a live LDR E2E run.

Runs offline-friendly checks (unit-adjacent smokes) and prints commands for live eval.

Usage:
  python scripts/ldr_eval_smoke.py
  python scripts/ldr_eval_smoke.py --live   # also run fulltext smoke (network)
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run(cmd: list[str], *, label: str) -> int:
    print(f"\n=== {label} ===")
    print(" ".join(cmd))
    proc = subprocess.run(cmd, cwd=ROOT)
    return proc.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description="LDR evaluation pre-flight")
    parser.add_argument("--live", action="store_true", help="Run network fulltext smoke")
    parser.add_argument("--pytest", action="store_true", help="Run LDR unit test subset")
    args = parser.parse_args()

    py = sys.executable
    codes = []

    if args.pytest or not args.live:
        codes.append(
            _run(
                [py, "-m", "pytest", "tests/test_ldr_sourcing_fixture.py", "tests/test_ldr_url_enrich.py",
                 "tests/test_ldr_fulltext_escalate.py", "tests/test_ldr_content_enrich.py", "-q"],
                label="LDR enrich unit tests",
            )
        )

    if args.live:
        codes.append(_run([py, "scripts/ldr_fulltext_smoke.py"], label="DOI fulltext ladder (live)"))

    print("\n=== Live E2E (manual) ===")
    print("  python scripts/ldr_e2e_smoke.py --max-time 420 --search-provider duckduckgo")
    print("  # Check log for sourcing: N/M abstract+ after enrich")

    if any(c != 0 for c in codes):
        print("\nFAIL: one or more pre-flight steps failed")
        return 1
    print("\nPASS: ready for live E2E evaluation")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
