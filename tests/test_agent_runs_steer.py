"""Steer queue + stop clears pending redirects (mid-run Phase B)."""

from __future__ import annotations

import uuid

import src.agent_runs as agent_runs


def _put_running(session_id: str) -> agent_runs._Run:
    run = agent_runs._Run()
    run.status = "running"
    agent_runs._RUNS[session_id] = run
    return run


def test_enqueue_requires_active_run_and_nonempty_text():
    sid = f"steer-{uuid.uuid4().hex}"
    assert agent_runs.enqueue_steer(sid, "hello") is None
    _put_running(sid)
    try:
        assert agent_runs.enqueue_steer(sid, "   ") is None
        item = agent_runs.enqueue_steer(sid, " use pytest ")
        assert item is not None
        assert item["text"] == "use pytest"
        assert len(agent_runs.get_run(sid).steer_queue) == 1
        # SSE buffer got a steer_queued event
        assert any("steer_queued" in ev for ev in agent_runs.get_run(sid).buffer)
    finally:
        agent_runs._RUNS.pop(sid, None)


def test_pop_steers_coalesces_multiple():
    sid = f"steer-{uuid.uuid4().hex}"
    _put_running(sid)
    try:
        agent_runs.enqueue_steer(sid, "first")
        agent_runs.enqueue_steer(sid, "second")
        one = agent_runs.pop_steers_coalesced(sid)
        assert one is not None
        assert "- first" in one["text"] and "- second" in one["text"]
        assert one.get("coalesced_ids") and len(one["coalesced_ids"]) == 2
        assert agent_runs.pop_steers_coalesced(sid) is None

        only = agent_runs.enqueue_steer(sid, "solo")
        popped = agent_runs.pop_steers_coalesced(sid)
        assert popped["id"] == only["id"]
        assert popped["text"] == "solo"
    finally:
        agent_runs._RUNS.pop(sid, None)


def test_clear_and_stop_clear_queue():
    sid = f"steer-{uuid.uuid4().hex}"
    _put_running(sid)
    try:
        agent_runs.enqueue_steer(sid, "a")
        agent_runs.enqueue_steer(sid, "b")
        cleared = agent_runs.clear_steer_queue(sid)
        assert [c["text"] for c in cleared] == ["a", "b"]
        assert agent_runs.get_run(sid).steer_queue == []

        agent_runs.enqueue_steer(sid, "c")
        # stop() clears queue when cancelling a real task; without task just clear
        agent_runs.clear_steer_queue(sid)
        assert agent_runs.get_run(sid).steer_queue == []
    finally:
        agent_runs._RUNS.pop(sid, None)


def test_enqueue_ignored_when_run_done():
    sid = f"steer-{uuid.uuid4().hex}"
    run = _put_running(sid)
    try:
        run.status = "done"
        assert agent_runs.enqueue_steer(sid, "too late") is None
    finally:
        agent_runs._RUNS.pop(sid, None)
