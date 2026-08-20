"""Tests for Nobody academic synthesis after LDR gather."""

import pytest

from src.research.ldr_synthesis import (
    persistable_synthesis_report,
    prepare_synthesis_markdown,
    report_looks_like_gathering_dump,
    report_needs_rewrite,
    synthesize_academic_report,
)
from src.research_evidence import EvidenceRegistry
from src.research_templates import build_final_report_prompt

_VALID_REPORT = """\
# Folding mechanisms in proteins

## Executive Summary

Folding is important [1].

## Background

Proteins fold into functional shapes [1].

## Key Findings

Experimental work supports cooperative folding [1].

## Conflicting Evidence

None noted.

## Limitations of the Evidence

Single-source synthesis.

## Limitations of This Report

Automatic checks applied.

## Conclusion

Folding recovered [1].

## References
"""

_DUMP = (
    "[1] Source One: Finding about folding...\n"
    "[2] Source Two: Another excerpt...\n"
)

_NO_H1_REPORT = """\
## Executive Summary

Folding is important [1].

## Background

Context [1].

## Key Findings

Details [1].

## Conflicting Evidence

None.

## Limitations of the Evidence

Limited.

## Limitations of This Report

Limited.

## Conclusion

Done [1].
"""


def _registry_with_source():
    registry = EvidenceRegistry()
    finding = {
        "title": "Source One",
        "url": "https://doi.org/10.1/one",
        "content": "Finding about folding.",
        "evidence": "Finding about folding. " * 20,
    }
    registry.register(finding)
    return registry, finding


def test_final_report_prompt_labels_source_notes_not_draft():
    prompt = build_final_report_prompt(
        question="What is folding?",
        report=_DUMP,
        min_words=1200,
        mode="literature_review",
    )
    assert "Source notes (not the report)" in prompt
    assert "Do NOT copy" in prompt
    assert "draft synthesis" not in prompt.lower()
    assert prompt.index("**Question:**") < prompt.index("**Source notes")


def test_report_looks_like_gathering_dump():
    assert report_looks_like_gathering_dump(_DUMP)
    structured = (
        "# Folding review\n\n"
        "## Executive Summary\n\n"
        "Folding is important [1].\n\n"
        "## Key Findings\n\n"
        "Details [1].\n"
    )
    assert not report_looks_like_gathering_dump(structured)
    assert report_looks_like_gathering_dump("")


def test_executive_summary_plus_source_lines_is_still_a_dump():
    mixed = (
        "# Folding review\n\n"
        "## Executive Summary\n\n"
        "[1] Source One: Finding about folding...\n"
        "[2] Source Two: Another excerpt...\n"
        "## Key Findings\n\n"
        "[3] Source Three: More excerpt...\n"
    )
    assert report_looks_like_gathering_dump(mixed)


def test_missing_key_findings_is_incomplete_for_literature_review():
    incomplete = (
        "# Folding review\n\n"
        "## Executive Summary\n\n"
        "Folding is important [1].\n"
    )
    assert report_looks_like_gathering_dump(incomplete, research_mode="literature_review")


def test_no_h1_with_sections_is_not_a_dump_but_needs_rewrite():
    assert not report_looks_like_gathering_dump(_NO_H1_REPORT)
    assert report_needs_rewrite(_NO_H1_REPORT)


def test_prepare_synthesis_markdown_strips_thinking_and_junk_title():
    raw = (
        "We need answer user. Need write academic literature synthesis.\n\n"
        "Let's outline:\n\n"
        '# title specific. Maybe "Foldseek 3Di Search" or similar.\n\n'
        "## Executive Summary\n\n"
        "Foldseek uses 3Di [1].\n\n"
        "## Key Findings\n\n"
        "AlphaFold predicts structures [2].\n"
    )
    cleaned = prepare_synthesis_markdown(raw)
    assert not cleaned.lower().startswith("we need")
    assert "title specific" not in cleaned.lower()
    assert cleaned.lstrip().startswith("## Executive Summary")


def test_persistable_keeps_no_h1_writeup_and_injects_title():
    registry, finding = _registry_with_source()
    out = persistable_synthesis_report(
        _NO_H1_REPORT,
        question="What is folding?",
        registry=registry,
        findings=[finding],
    )
    assert out.lstrip().startswith("# What is folding?")
    assert "## Executive Summary" in out
    assert "Automatic synthesis did not complete" not in out
    assert "Folding is important" in out


def test_persistable_synthesis_replaces_dump_with_fallback():
    registry, finding = _registry_with_source()
    out = persistable_synthesis_report(
        _DUMP,
        question="What is folding?",
        registry=registry,
        findings=[finding],
    )
    assert "## Executive Summary" in out
    assert "Automatic synthesis did not complete" in out
    assert not report_looks_like_gathering_dump(out)


def test_sourcing_limitations_uses_finding_body_not_stale_thin_tier():
    registry = EvidenceRegistry()
    finding = {
        "title": "Foldseek",
        "url": "https://doi.org/10.1/fold",
        "evidence": (
            "Foldseek encodes tertiary residue interactions as a 20-state 3Di alphabet "
            "so structure search can use sequence aligners. It is orders of magnitude "
            "faster than Dali and TM-align while remaining sensitive on SCOPe40 benchmarks "
            "and large AlphaFold database searches."
        ),
        "pdf_extracted": True,
    }
    registry.register(finding)
    # Simulate a stale thin tier on the registry row.
    registry.sources()[0].sourcing_tier = "metadata_only"
    block = registry.sourcing_limitations_block([finding])
    assert "NOT adequately retrieved" not in block
    assert "adequate text" in block.lower()


@pytest.mark.asyncio
async def test_synthesize_academic_report_calls_llm(monkeypatch):
    registry, _finding = _registry_with_source()

    calls = []

    async def fake_llm_call_async(**kwargs):
        calls.append(kwargs)
        return _VALID_REPORT

    monkeypatch.setattr("src.llm_core.llm_call_async", fake_llm_call_async)

    report = await synthesize_academic_report(
        question="What is folding?",
        draft_report="draft",
        registry=registry,
        llm_endpoint="http://localhost/v1/chat/completions",
        llm_model="test",
        research_mode="literature_review",
        report_length="standard",
        max_report_tokens=2048,
    )

    assert "Folding is important" in report
    assert calls
    assert calls[0]["model"] == "test"


@pytest.mark.asyncio
async def test_synthesize_falls_back_when_llm_raises(monkeypatch):
    registry, finding = _registry_with_source()

    async def fake_llm_call_async(**kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("src.llm_core.llm_call_async", fake_llm_call_async)

    report = await synthesize_academic_report(
        question="What is folding?",
        draft_report=_DUMP,
        registry=registry,
        llm_endpoint="http://localhost/v1/chat/completions",
        llm_model="test",
        findings=[finding],
    )
    assert "## Executive Summary" in report
    assert "Automatic synthesis did not complete" in report
    assert "Source One" in report
    assert not report_looks_like_gathering_dump(report)


@pytest.mark.asyncio
async def test_synthesize_retries_then_falls_back_on_draft_echo(monkeypatch):
    registry, finding = _registry_with_source()
    calls = []

    async def fake_llm_call_async(**kwargs):
        calls.append(kwargs)
        return _DUMP

    monkeypatch.setattr("src.llm_core.llm_call_async", fake_llm_call_async)

    report = await synthesize_academic_report(
        question="What is folding?",
        draft_report=_DUMP,
        registry=registry,
        llm_endpoint="http://localhost/v1/chat/completions",
        llm_model="test",
        findings=[finding],
    )
    assert len(calls) >= 3
    assert "## Executive Summary" in report
    assert "## Key Findings" in report
    assert "Automatic synthesis did not complete" in report


@pytest.mark.asyncio
async def test_synthesize_keeps_no_h1_after_failed_title_rewrites(monkeypatch):
    registry, finding = _registry_with_source()

    async def fake_llm_call_async(**kwargs):
        return _NO_H1_REPORT

    monkeypatch.setattr("src.llm_core.llm_call_async", fake_llm_call_async)

    report = await synthesize_academic_report(
        question="What is folding?",
        draft_report=_DUMP,
        registry=registry,
        llm_endpoint="http://localhost/v1/chat/completions",
        llm_model="test",
        findings=[finding],
    )
    assert report.lstrip().startswith("# What is folding?")
    assert "Folding is important" in report
    assert "Automatic synthesis did not complete" not in report


@pytest.mark.asyncio
async def test_synthesize_second_rewrite_can_recover(monkeypatch):
    registry, finding = _registry_with_source()
    compose_calls = []

    async def fake_llm_call_async(**kwargs):
        msgs = kwargs.get("messages") or []
        if any("too brief" in (m.get("content") or "") for m in msgs):
            return _VALID_REPORT
        compose_calls.append(kwargs)
        if len(compose_calls) < 3:
            return _DUMP
        return _VALID_REPORT

    monkeypatch.setattr("src.llm_core.llm_call_async", fake_llm_call_async)

    report = await synthesize_academic_report(
        question="What is folding?",
        draft_report=_DUMP,
        registry=registry,
        llm_endpoint="http://localhost/v1/chat/completions",
        llm_model="test",
        findings=[finding],
    )
    assert "Folding recovered" in report
    assert "## Executive Summary" in report
    assert len(compose_calls) == 3
    rewrite = compose_calls[-1]["messages"]
    assert rewrite[0]["role"] == "user"
    assert rewrite[1]["role"] == "user"
    assert "source notes are evidence" in rewrite[1]["content"]
    for call in compose_calls:
        for msg in call.get("messages") or []:
            if msg.get("role") == "assistant":
                assert _DUMP.strip() not in (msg.get("content") or "")


@pytest.mark.asyncio
async def test_synthesize_retry_can_recover_from_dump(monkeypatch):
    registry, finding = _registry_with_source()
    calls = []

    async def fake_llm_call_async(**kwargs):
        calls.append(kwargs)
        msgs = kwargs.get("messages") or []
        if any("too brief" in (m.get("content") or "") for m in msgs):
            return _VALID_REPORT
        if any("source notes are evidence" in (m.get("content") or "") for m in msgs):
            return _VALID_REPORT
        return _DUMP

    monkeypatch.setattr("src.llm_core.llm_call_async", fake_llm_call_async)

    report = await synthesize_academic_report(
        question="What is folding?",
        draft_report=_DUMP,
        registry=registry,
        llm_endpoint="http://localhost/v1/chat/completions",
        llm_model="test",
        findings=[finding],
    )
    assert "Folding recovered" in report
    assert "## Executive Summary" in report
    for call in calls:
        for msg in call.get("messages") or []:
            if msg.get("role") == "assistant":
                assert _DUMP.strip() not in (msg.get("content") or "")


def test_structured_fallback_uses_mode_section_headings():
    registry = EvidenceRegistry()
    finding = {
        "title": "Source One",
        "url": "https://doi.org/10.1/one",
        "evidence": "Finding about folding. " * 20,
    }
    registry.register(finding)
    text = registry.build_structured_fallback(
        "Compare folding",
        [finding],
        research_mode="compare",
    )
    assert "## Executive Summary" in text
    assert "## Papers Compared" in text
    assert "## Findings Comparison" in text
    assert "Source One" in text
