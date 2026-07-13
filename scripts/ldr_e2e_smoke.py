#!/usr/bin/env python3
"""One-shot LDR end-to-end smoke test.

Requires:
  - Python 3.12–3.13 with local-deep-research installed
  - Configured LLM endpoint in data/app.db (Gemini, DeepSeek, etc.)
  - Network for search (duckduckgo or SearXNG)

Usage:
  python scripts/ldr_e2e_smoke.py
  python scripts/ldr_e2e_smoke.py --search-provider searxng --max-time 180
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


async def main() -> int:
    parser = argparse.ArgumentParser(description="LDR end-to-end smoke test")
    parser.add_argument(
        "--query",
        default="What is Foldseek protein structure search? Keep the answer brief.",
    )
    parser.add_argument("--max-time", type=int, default=120)
    parser.add_argument("--max-rounds", type=int, default=10)
    parser.add_argument("--search-provider", default="duckduckgo")
    parser.add_argument("--endpoint-id", default="", help="Force a specific endpoint id from app.db")
    parser.add_argument("--model", default="", help="Override model name")
    parser.add_argument("--dry-run", action="store_true", help="Only check deps + endpoint")
    args = parser.parse_args()

    from src.research.ldr_availability import ldr_stack_available

    if not ldr_stack_available():
        print("FAIL: local-deep-research / langgraph not importable (need Python 3.12–3.13)")
        return 1
    print("OK: LDR stack importable")

    from src.endpoint_resolver import resolve_endpoint, resolve_endpoint_by_id

    if args.endpoint_id:
        resolved = resolve_endpoint_by_id(args.endpoint_id, model=args.model or None)
        if not resolved:
            print(f"FAIL: endpoint id {args.endpoint_id!r} not found or disabled")
            return 1
        ep_url, ep_model, ep_headers = resolved
    else:
        ep_url, ep_model, ep_headers = resolve_endpoint("research")
        if not ep_url:
            ep_url, ep_model, ep_headers = resolve_endpoint("utility")
        if not ep_url:
            ep_url, ep_model, ep_headers = resolve_endpoint("default")
    if args.model:
        ep_model = args.model
    if not ep_url or not ep_model:
        print("FAIL: no enabled LLM endpoint in data/app.db")
        return 1
    print(f"OK: endpoint model={ep_model!r} url={ep_url[:60]}...")

    if args.dry_run:
        return 0

    from src.research.ldr_runner import run_ldr_research

    events: list = []
    holder: dict = {}

    def on_progress(event: dict) -> None:
        events.append(event)
        phase = event.get("phase", "?")
        msg = (event.get("message") or "")[:72]
        extra = ""
        if event.get("event") == "source_rejected":
            extra = f" [{event.get('reason')}]"
        print(f"  {phase}: {msg}{extra}")

    t0 = time.time()
    print(f"Running LDR research (search={args.search_provider}, max_time={args.max_time}s)...")
    try:
        report = await run_ldr_research(
            args.query,
            llm_endpoint=ep_url,
            llm_model=ep_model,
            llm_headers=ep_headers,
            max_iterations=args.max_rounds,
            max_time=args.max_time,
            search_provider=args.search_provider,
            include_preprints=True,
            include_zotero=False,
            include_knowledge=False,
            progress_callback=on_progress,
            result_holder=holder,
        )
    except Exception as exc:
        print(f"FAIL: {exc}")
        return 1

    elapsed = time.time() - t0
    session = holder.get("researcher")
    n_sources = len(session.evidence_registry) if session else 0
    n_findings = len(session.findings) if session else 0
    phases = [e.get("phase") for e in events]
    rejections = [e for e in events if e.get("event") == "source_rejected"]

    print(f"\nOK in {elapsed:.1f}s")
    print(f"  Registry sources: {n_sources}")
    print(f"  Raw findings: {n_findings}")
    print(f"  Report chars: {len(report)}")
    print(f"  Phases: {phases}")
    print(f"  Rejections: {len(rejections)}")
    if session:
        print(f"  Stats: {session.get_stats()}")
        try:
            from src.research.ldr_fulltext_escalate import format_sourcing_summary

            print(f"  {format_sourcing_summary(session.evidence_registry, session.findings)}")
        except Exception:
            pass
    print("\n--- report preview ---")
    print(report[:1200])
    if n_sources < 1:
        print("\nWARN: no sources ingested — check search provider / network")
        return 1

    try:
        from src.research.ldr_fulltext_escalate import sourcing_tier_counts
        from src.research_sourcing import SOURCING_TIER_ABSTRACT_ONLY, SOURCING_TIER_ADEQUATE

        if session:
            counts = sourcing_tier_counts(session.evidence_registry, session.findings)
            total = sum(counts.values()) or 1
            usable = counts.get(SOURCING_TIER_ADEQUATE, 0) + counts.get(SOURCING_TIER_ABSTRACT_ONLY, 0)
            pct = usable * 100 // total
            if pct < 30:
                print(f"\nWARN: sourcing usable {usable}/{total} ({pct}%) below 30% — check enrich ladder / network")
    except Exception:
        pass

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
