"""LDR migration — adapter, progress, runner (optional LDR install for smoke)."""

import pytest

from src.research.ldr_availability import ldr_stack_available, research_engine_mode
from src.research.ldr_llm_adapter import (
    api_key_from_headers,
    openai_api_base_from_endpoint,
)
from src.research.ldr_progress import ldr_event_to_progress, normalize_ldr_phase
from src.research.ldr_runner import LdrResearchNotReadyError


def test_openai_api_base_from_openai_style_endpoint():
    base = openai_api_base_from_endpoint("https://api.example.com/v1/chat/completions")
    assert base == "https://api.example.com/v1"


def test_openai_api_base_from_local_openai_compat():
    base = openai_api_base_from_endpoint("http://127.0.0.1:8080/v1/chat/completions")
    assert base == "http://127.0.0.1:8080/v1"


def test_api_key_from_bearer_header():
    assert api_key_from_headers({"Authorization": "Bearer sk-test"}) == "sk-test"
    assert api_key_from_headers({}) == "none"


def test_ldr_event_to_progress_maps_searching():
    out = ldr_event_to_progress({"phase": "search", "message": "PubMed query"})
    assert out["phase"] == "searching"
    assert "PubMed" in out["message"]


def test_normalize_ldr_phase_synthesis():
    assert normalize_ldr_phase("writing") == "synthesizing"


def test_research_engine_mode_default(monkeypatch):
    monkeypatch.setattr("src.settings.get_setting", lambda k, d=None: d)
    expected = "ldr" if ldr_stack_available() else "iterresearch"
    assert research_engine_mode() == expected


def test_research_engine_mode_explicit_iterresearch(monkeypatch):
    monkeypatch.setattr(
        "src.settings.get_setting",
        lambda k, d=None: "iterresearch" if k == "research_engine" else d,
    )
    assert research_engine_mode() == "iterresearch"


def test_research_engine_mode_falls_back_without_ldr_stack(monkeypatch):
    monkeypatch.setattr(
        "src.settings.get_setting",
        lambda k, d=None: "ldr" if k == "research_engine" else d,
    )
    monkeypatch.setattr("src.research.ldr_availability.ldr_stack_available", lambda: False)
    assert research_engine_mode() == "iterresearch"


def test_ldr_stack_available_without_install():
    assert isinstance(ldr_stack_available(), bool)


def test_ldr_event_to_progress_preserves_rejection_metadata():
    out = ldr_event_to_progress(
        {
            "phase": "warning",
            "event": "source_rejected",
            "reason": "preprint_excluded",
            "message": "Skipped source",
        }
    )
    assert out["phase"] == "warning"
    assert out["event"] == "source_rejected"
    assert out["reason"] == "preprint_excluded"
    err = LdrResearchNotReadyError("missing")
    assert "missing" in str(err)


@pytest.mark.skipif(not ldr_stack_available(), reason="optional LDR stack not installed")
def test_build_langchain_chat_model_smoke():
    from src.research.ldr_llm_adapter import build_langchain_chat_model

    model = build_langchain_chat_model(
        chat_endpoint="http://127.0.0.1:11434/v1/chat/completions",
        model="test-model",
        headers={},
    )
    assert model.model_name == "test-model"
