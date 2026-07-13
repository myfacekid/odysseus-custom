"""L6 golden fixture — sourcing tier regression for Foldseek-shaped enrich output."""

import json
from pathlib import Path

from src.research_sourcing import assess_finding_sourcing

FIXTURE = Path(__file__).parent / "fixtures" / "research" / "ldr_sourcing_foldseek.json"


def _load():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_sourcing_fixture_expected_tiers():
    data = _load()
    counts: dict[str, int] = {}
    for row in data["findings_after_enrich"]:
        tier, _, _ = assess_finding_sourcing(row)
        counts[tier] = counts.get(tier, 0) + 1
    assert counts == data["expected_tier_counts"]


def test_sourcing_fixture_usable_fraction():
    data = _load()
    rows = data["findings_after_enrich"]
    usable = sum(
        1
        for row in rows
        if assess_finding_sourcing(row)[0] in ("abstract_only", "adequate")
    )
    assert usable / len(rows) >= data["expected_usable_fraction_min"]


def test_sourcing_fixture_metadata_only_stays_thin():
    data = _load()
    thin = [r for r in data["findings_after_enrich"] if r["citation_num"] == 4][0]
    tier, _, allow = assess_finding_sourcing(thin)
    assert tier == "metadata_only"
    assert allow is False
