"""Regression tests for send_to_session and tool schema parity."""

import json

import pytest

from src.agent_tools import TOOL_TAGS
from src.memory import MemoryManager
from core.session_manager import SessionManager
import src.ai_interaction as ai
from src.agent_tools import ToolBlock
from src.tool_execution import execute_tool_block
from src.tool_schemas import FUNCTION_TOOL_SCHEMAS, function_call_to_tool_block


@pytest.fixture
def wired_managers(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    sessions_file = tmp_path / "sessions.json"
    sm = SessionManager(str(sessions_file))
    mm = MemoryManager(str(data_dir))
    ai.set_session_manager(sm)
    ai.set_memory_manager(mm)
    yield sm, mm
    ai.set_session_manager(None)
    ai.set_memory_manager(None)


@pytest.mark.asyncio
async def test_send_to_session_missing_id_returns_error_not_keyerror(wired_managers):
    _, _ = wired_managers
    desc, result = await execute_tool_block(
        ToolBlock("send_to_session", "__nonexistent__\nhi"),
        session_id=None,
        owner="tester",
    )
    assert "send_to_session" in desc
    assert result.get("exit_code") == 1
    assert "not found" in result.get("error", "").lower()


@pytest.mark.asyncio
async def test_list_sessions_sets_exit_code_with_managers(wired_managers):
    _, _ = wired_managers
    _, result = await execute_tool_block(
        ToolBlock("list_sessions", ""),
        session_id=None,
        owner="tester",
    )
    assert result.get("exit_code") == 0
    assert "results" in result


def test_function_schemas_cover_all_tool_tags():
    schema_names = {s["function"]["name"] for s in FUNCTION_TOOL_SCHEMAS}
    assert schema_names == set(TOOL_TAGS)


def test_generate_image_function_call_roundtrip():
    blk = function_call_to_tool_block(
        "generate_image",
        json.dumps({"prompt": "a red circle", "size": "512x512"}),
    )
    assert blk is not None
    assert blk.tool_type == "generate_image"
    assert blk.content.split("\n")[0] == "a red circle"
    assert "512x512" in blk.content


def test_manage_research_function_call_roundtrip():
    blk = function_call_to_tool_block(
        "manage_research",
        json.dumps({"action": "list", "search": "ml"}),
    )
    assert blk is not None
    assert blk.tool_type == "manage_research"
    assert json.loads(blk.content)["action"] == "list"
