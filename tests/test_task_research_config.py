"""research_config encode/decode and task dict round-trip."""

import json
from types import SimpleNamespace

from routes.task_routes import (
    decode_research_config,
    encode_research_config,
    _run_research_id,
    _task_to_dict,
)


def test_encode_research_config_omits_blank_key_topics():
    encoded = encode_research_config({
        "mode": "compare",
        "seed_papers": ["ABC12345", " ABC12345 ", "DEF67890"],
        "approved_plan": {
            "search_keywords": ["foldseek structure"],
            "key_topics": [],
            "scope": "narrow_compare",
        },
        "report_length": "extended",
    })
    data = json.loads(encoded)
    assert data["mode"] == "compare"
    assert data["seed_papers"] == ["ABC12345", "DEF67890"]
    assert "key_topics" not in data["approved_plan"]
    assert data["approved_plan"]["search_keywords"] == ["foldseek structure"]
    assert data["report_length"] == "extended"


def test_decode_research_config_roundtrip():
    raw = encode_research_config({
        "mode": "gap_analysis",
        "seed_papers": ["KEY12345"],
        "approved_plan": {"search_keywords": ["gap"], "key_topics": ["coverage"]},
    })
    decoded = decode_research_config(raw)
    assert decoded["mode"] == "gap_analysis"
    assert decoded["seed_papers"] == ["KEY12345"]
    assert decoded["approved_plan"]["key_topics"] == ["coverage"]
    assert decode_research_config(None) is None
    assert decode_research_config("not-json") is None


def test_task_to_dict_includes_research_config():
    cfg = encode_research_config({
        "mode": "literature_review",
        "approved_plan": {"search_keywords": ["rna folding"]},
    })
    task = SimpleNamespace(
        id="t1",
        name="Weekly lit review",
        prompt="RNA folding",
        task_type="research",
        action=None,
        schedule="weekly",
        scheduled_time="09:00",
        scheduled_day=0,
        scheduled_date=None,
        cron_expression=None,
        trigger_type="schedule",
        trigger_event=None,
        trigger_count=None,
        trigger_counter=0,
        next_run=None,
        last_run=None,
        status="active",
        output_target="session",
        session_id="chat-1",
        crew_member_id=None,
        model=None,
        endpoint_url=None,
        run_count=0,
        then_task_id=None,
        notifications_enabled=True,
        webhook_token=None,
        created_at=None,
        updated_at=None,
        research_config=cfg,
        runs=[],
    )
    d = _task_to_dict(task)
    assert d["research_config"]["mode"] == "literature_review"
    assert d["research_config"]["approved_plan"]["search_keywords"] == ["rna folding"]


def test_run_research_id_prefers_per_run_id():
    task = SimpleNamespace(task_type="research", session_id="chat-old")
    run = SimpleNamespace(research_id="rp-abcdef123456")
    assert _run_research_id(task, run) == "rp-abcdef123456"
    assert _run_research_id(task, SimpleNamespace(research_id="")) == "chat-old"
    assert _run_research_id(SimpleNamespace(task_type="llm", session_id="x")) == ""
