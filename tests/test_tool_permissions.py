"""Tests for agent Ask/Auto permissions, change tape, and context breakdown."""

from __future__ import annotations

import asyncio

import pytest

from src.model_context import estimate_context_breakdown
from src.tool_permissions import (
    MODE_ASK,
    MODE_AUTO,
    allow_tool_for_session,
    build_change_entry,
    denied_tool_result,
    format_steer_message,
    normalize_mode,
    session_allowlist,
    should_request_approval,
    tool_needs_approval,
    ApprovalRegistry,
)


def test_normalize_mode():
    assert normalize_mode("auto") == MODE_AUTO
    assert normalize_mode("ASK") == MODE_ASK
    assert normalize_mode(None) == MODE_ASK
    assert normalize_mode("nope") == MODE_ASK


def test_tool_needs_approval_mutating_and_mcp():
    assert tool_needs_approval("bash") is True
    assert tool_needs_approval("web_search") is False
    assert tool_needs_approval("mcp__foo__bar") is True
    assert tool_needs_approval("") is False
    assert tool_needs_approval(None) is False


def test_should_request_approval_ask_vs_auto_and_allowlist():
    assert should_request_approval("bash", mode="ask") is True
    assert should_request_approval("bash", mode="auto") is False
    assert should_request_approval("web_search", mode="ask") is False
    assert should_request_approval(
        "bash", mode="ask", permanent={"bash"}
    ) is False
    assert should_request_approval(
        "bash", mode="ask", session={"bash"}
    ) is False


def test_session_allowlist():
    sid = "sess-test-allow"
    session_allowlist(sid).clear()
    allow_tool_for_session(sid, "bash")
    assert "bash" in session_allowlist(sid)
    assert should_request_approval(
        "bash", mode="ask", session=session_allowlist(sid)
    ) is False


def test_build_change_entry_and_deny():
    row = build_change_entry(
        "bash",
        "echo hi",
        {"exit_code": 0, "output": "hi"},
        "hi",
    )
    assert row and row["tool"] == "bash" and "Shell" in row["summary"]

    assert build_change_entry(
        "bash", "rm -rf /", {"exit_code": 1, "error": "fail"}, "fail"
    ) is None

    assert build_change_entry("web_search", "q", {"exit_code": 0}, "ok") is None

    denied = denied_tool_result("bash")
    assert denied["exit_code"] == 1
    assert "permission denied" in denied["output"]


def test_format_steer_message():
    text = format_steer_message("use pytest instead")
    assert "User steering" in text
    assert "use pytest instead" in text


@pytest.mark.asyncio
async def test_approval_registry_resolve_and_timeout():
    reg = ApprovalRegistry()
    aid = await reg.create(
        tool="bash", command="ls", session_id="s1", owner="admin"
    )
    assert reg.peek(aid)["tool"] == "bash"

    async def _approve():
        await asyncio.sleep(0.05)
        assert await reg.resolve(aid, "approve")

    task = asyncio.create_task(_approve())
    fut = reg.get_future(aid)
    decision = await asyncio.wait_for(asyncio.shield(fut), timeout=2)
    await task
    assert decision == "approve"
    assert reg.peek(aid) is None

    aid2 = await reg.create(
        tool="python", command="1", session_id="s1", owner="admin"
    )
    decision2 = await reg.wait(aid2, timeout=0.05)
    assert decision2 == "deny"


@pytest.mark.asyncio
async def test_approval_cancel_session():
    reg = ApprovalRegistry()
    aid = await reg.create(
        tool="bash", command="x", session_id="sess-x", owner="u"
    )
    await reg.cancel_session("sess-x")
    fut = reg.get_future(aid)
    # cancelled entries are removed; future may still be done with deny
    assert reg.peek(aid) is None


def test_estimate_context_breakdown_buckets():
    messages = [
        {"role": "system", "content": "You are an AI assistant with tool access. ```bash"},
        {"role": "system", "content": "available skills index\n- foo"},
        {"role": "system", "content": "retrieved documents\nDoc A"},
        {"role": "user", "content": "hello world " * 50},
        {"role": "assistant", "content": "hi there"},
    ]
    bd = estimate_context_breakdown(messages, context_length=8000)
    assert bd["history"] > 0
    assert bd["system_tools"] > 0
    assert bd["skills"] > 0
    assert bd["memory_rag"] > 0
    assert bd["free"] >= 0
    assert bd["free"] == 8000 - (
        bd["history"] + bd["system_tools"] + bd["memory_rag"] + bd["skills"] + bd["other"]
    )
