"""Tests for Nobody academic synthesis after LDR gather."""

import pytest

from src.research.ldr_synthesis import synthesize_academic_report
from src.research_evidence import EvidenceRegistry


@pytest.mark.asyncio
async def test_synthesize_academic_report_calls_llm(monkeypatch):
    registry = EvidenceRegistry()
    registry.register(
        {
            "title": "Source One",
            "url": "https://doi.org/10.1/one",
            "content": "Finding about folding.",
        }
    )

    calls = []

    async def fake_llm_call_async(**kwargs):
        calls.append(kwargs)
        return "## Executive Summary\n\nFolding is important [1].\n\n## References\n\n[1] Source One."

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
