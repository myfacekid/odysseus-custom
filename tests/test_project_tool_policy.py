"""Phase 0e — project session tool policy."""

import uuid
from types import SimpleNamespace

import pytest

import core.database as cdb
import core.session_manager as SM
from core.session_manager import SessionManager
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from src.project_sessions import create_project_session
from src.project_tool_policy import (
    PROJECT_DEPTH_DENIED_TOOLS,
    disabled_tools_for_project_session,
    disabled_tools_outside_project_session,
    is_project_depth_denied_tool,
    project_tool_block_reason,
    session_is_project,
)
from src.project_workspace import create_project


@pytest.fixture
def policy_env(tmp_path, monkeypatch):
    db_path = tmp_path / "phase0e.db"
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
        poolclass=NullPool,
    )
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    cdb.Base.metadata.create_all(engine)
    monkeypatch.setattr(cdb, "SessionLocal", Session)
    monkeypatch.setattr(SM, "SessionLocal", Session)
    monkeypatch.setattr(cdb, "DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setattr("src.project_workspace.PROJECTS_ROOT", tmp_path / "projects")

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    create_project(
        "alice",
        title="Policy project",
        working_dir=str(workspace),
        project_id="proj-policy",
    )
    manager = SessionManager()
    manager.sessions = {}
    created = create_project_session(
        manager,
        "alice",
        "proj-policy",
        name="Policy chat",
    )
    regular_id = str(uuid.uuid4())
    manager.create_session(
        session_id=regular_id,
        name="Regular chat",
        endpoint_url="http://localhost:8000/v1",
        model="test-model",
        owner="alice",
        mode="agent",
    )
    return {
        "project_session_id": created["id"],
        "regular_session_id": regular_id,
    }


def test_session_is_project(policy_env):
    assert session_is_project(policy_env["project_session_id"]) is True
    assert session_is_project(policy_env["regular_session_id"]) is False
    assert session_is_project(None) is False


def test_session_is_project_after_agent_mode(policy_env):
    """Chat send persists mode=agent; project sessions must still match via project_id."""
    from core.database import set_session_mode

    pid = policy_env["project_session_id"]
    set_session_mode(pid, "agent")
    assert session_is_project(pid) is True


def test_depth_denied_tools_include_escape_hatches():
    assert "bash" in PROJECT_DEPTH_DENIED_TOOLS
    assert "python" in PROJECT_DEPTH_DENIED_TOOLS
    assert "read_file" in PROJECT_DEPTH_DENIED_TOOLS
    assert "write_file" in PROJECT_DEPTH_DENIED_TOOLS
    assert is_project_depth_denied_tool("mcp__filesystem__read_file")
    assert not is_project_depth_denied_tool("search_knowledge")


def test_disabled_tools_for_project_session():
    disabled = disabled_tools_for_project_session()
    assert "bash" in disabled
    assert "python" in disabled
    assert "mcp__filesystem__read_file" in disabled


def test_disabled_tools_outside_project_session():
    disabled = disabled_tools_outside_project_session()
    assert "read_project_file" in disabled
    assert "write_project_file" in disabled
    assert "run_project_script" in disabled
    assert "bash" not in disabled


def test_project_tool_block_reason(policy_env):
    pid = policy_env["project_session_id"]
    rid = policy_env["regular_session_id"]

    assert project_tool_block_reason("bash", pid) is not None
    assert "read_project_file" in project_tool_block_reason("bash", pid)
    assert project_tool_block_reason("bash", rid) is None
    assert project_tool_block_reason("search_knowledge", pid) is None
    assert project_tool_block_reason("read_project_file", rid) is not None
    assert project_tool_block_reason("read_project_file", pid) is None
    assert project_tool_block_reason("run_project_script", pid) is None


@pytest.mark.asyncio
async def test_execute_tool_block_rejects_bash_in_project_session(policy_env):
    from src.tool_execution import execute_tool_block

    desc, result = await execute_tool_block(
        SimpleNamespace(tool_type="bash", content="echo hi"),
        session_id=policy_env["project_session_id"],
        owner="alice",
    )
    assert desc == "bash: BLOCKED"
    assert result["exit_code"] == 1
    assert "project workspace" in result["error"].lower()


@pytest.mark.asyncio
async def test_execute_tool_block_rejects_python_in_project_session(policy_env):
    from src.tool_execution import execute_tool_block

    desc, result = await execute_tool_block(
        SimpleNamespace(tool_type="python", content="print(1)"),
        session_id=policy_env["project_session_id"],
        owner="alice",
    )
    assert desc == "python: BLOCKED"
    assert result["exit_code"] == 1
