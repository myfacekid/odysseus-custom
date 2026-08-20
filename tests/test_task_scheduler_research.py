"""Scheduled research executes through ResearchHandler, not a private JSON path."""

import asyncio
import json
from types import SimpleNamespace

import pytest


class _FakeQuery:
    def filter(self, *a, **k):
        return self

    def first(self):
        return None

    def all(self):
        return []


class _FakeDb:
    def query(self, model):
        return _FakeQuery()

    def add(self, obj):
        pass

    def commit(self):
        pass


@pytest.mark.asyncio
async def test_execute_research_task_calls_handler_with_unique_id():
    captured = {}

    class FakeHandler:
        async def run_and_wait(self, session_id, **kwargs):
            captured["session_id"] = session_id
            captured["kwargs"] = kwargs
            return "## Research Summary\n\nDone."

    from src.task_scheduler import TaskScheduler

    scheduler = TaskScheduler.__new__(TaskScheduler)
    scheduler._session_manager = None
    scheduler._research_handler = FakeHandler()
    scheduler._research_session_by_task = {}
    scheduler._last_run_model = None

    cfg = json.dumps({
        "mode": "compare",
        "seed_papers": ["ABC12345", "DEF67890"],
        "approved_plan": {"search_keywords": ["foldseek structure"], "scope": "narrow_compare"},
        "include_zotero": True,
        "include_knowledge": False,
        "include_preprints": True,
        "report_length": "standard",
    })
    task = SimpleNamespace(
        id="task-1",
        name="Compare papers",
        prompt="Compare Foldseek and ESM3",
        endpoint_url="http://localhost:8000/v1",
        model="test-model",
        session_id="chat-session-keep",
        owner="alice",
        research_config=cfg,
    )
    report = await scheduler._execute_research_task(task, _FakeDb(), run_id="run-1")
    assert report.startswith("## Research Summary")
    sid = captured["session_id"]
    assert sid.startswith("rp-")
    assert sid != "chat-session-keep"
    kwargs = captured["kwargs"]
    assert kwargs["query"] == "Compare Foldseek and ESM3"
    assert kwargs["research_mode"] == "compare"
    assert kwargs["seed_papers"] == ["ABC12345", "DEF67890"]
    assert kwargs["approved_plan"]["search_keywords"] == ["foldseek structure"]
    assert "key_topics" not in (kwargs["approved_plan"] or {})
    assert kwargs["include_knowledge"] is False
    assert kwargs["owner"] == "alice"
    assert kwargs["max_rounds"] == 20
    assert task.session_id == "chat-session-keep"


def test_stop_task_cancels_research_session():
    cancelled = []

    class FakeHandler:
        def cancel_research(self, session_id):
            cancelled.append(session_id)
            return True

    from src.task_scheduler import TaskScheduler

    async def drive():
        scheduler = TaskScheduler.__new__(TaskScheduler)
        scheduler._task_handles = {}
        scheduler._executing = set()
        scheduler._executing_lock = asyncio.Lock()
        scheduler._research_handler = FakeHandler()
        scheduler._research_session_by_task = {"task-1": "rp-abc"}
        scheduler._mark_run_aborted = lambda task_id: False
        assert await scheduler.stop_task("task-1") is True
        assert cancelled == ["rp-abc"]
        assert "task-1" not in scheduler._research_session_by_task

    asyncio.run(drive())
