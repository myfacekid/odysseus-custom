"""Phase B/C — project-scoped agent file and run tools."""

from types import SimpleNamespace

import pytest

import core.database as cdb
import core.session_manager as SM
from core.session_manager import SessionManager
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from src.project_files import write_text_file
from src.project_sessions import create_project_session
from src.project_tool_policy import (
    disabled_tools_outside_project_session,
    project_tool_block_reason,
)
from src.project_workspace import create_project


@pytest.fixture
def agent_tool_env(tmp_path, monkeypatch):
    db_path = tmp_path / "agent_tools.db"
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
        title="Agent tools project",
        working_dir=str(workspace),
        project_id="proj-agent",
    )
    manager = SessionManager()
    manager.sessions = {}
    created = create_project_session(
        manager,
        "alice",
        "proj-agent",
        name="Project chat",
    )
    regular_id = manager.create_session(
        session_id="regular-chat-id",
        name="Regular chat",
        endpoint_url="http://localhost:8000/v1",
        model="test-model",
        owner="alice",
        mode="agent",
    ).id
    return {
        "project_session_id": created["id"],
        "regular_session_id": regular_id,
        "project_id": "proj-agent",
        "workspace": workspace,
    }


def test_project_tools_disabled_outside_project_session():
    disabled = disabled_tools_outside_project_session()
    assert "read_project_file" in disabled
    assert "write_project_file" in disabled
    assert "run_project_script" in disabled


def test_project_tool_block_reason_rejects_outside_project(agent_tool_env):
    rid = agent_tool_env["regular_session_id"]
    assert project_tool_block_reason("read_project_file", rid) is not None
    assert project_tool_block_reason("write_project_file", rid) is not None
    assert project_tool_block_reason("run_project_script", rid) is not None


@pytest.mark.asyncio
async def test_read_project_file_round_trip(agent_tool_env):
    from src.tool_execution import execute_tool_block

    pid = agent_tool_env["project_session_id"]
    write_text_file("alice", agent_tool_env["project_id"], "hello.py", "print('hi')\n")

    desc, result = await execute_tool_block(
        SimpleNamespace(tool_type="read_project_file", content="hello.py"),
        session_id=pid,
        owner="alice",
    )
    assert desc == "read_project_file: hello.py"
    assert result["exit_code"] == 0
    assert "print('hi')" in result["output"]
    assert result["path"] == "hello.py"


@pytest.mark.asyncio
async def test_write_project_file_creates_file(agent_tool_env):
    from src.tool_execution import execute_tool_block

    pid = agent_tool_env["project_session_id"]
    desc, result = await execute_tool_block(
        SimpleNamespace(
            tool_type="write_project_file",
            content="src/analysis.py\nx = 42\n",
        ),
        session_id=pid,
        owner="alice",
    )
    assert desc == "write_project_file: src/analysis.py"
    assert result["exit_code"] == 0
    assert (agent_tool_env["workspace"] / "src" / "analysis.py").read_text() == "x = 42\n"


@pytest.mark.asyncio
async def test_read_project_file_rejects_traversal(agent_tool_env):
    from src.tool_execution import execute_tool_block

    desc, result = await execute_tool_block(
        SimpleNamespace(tool_type="read_project_file", content="../escape.py"),
        session_id=agent_tool_env["project_session_id"],
        owner="alice",
    )
    assert result["exit_code"] == 1
    assert "error" in result


@pytest.mark.asyncio
async def test_project_file_tools_blocked_in_regular_session(agent_tool_env):
    from src.tool_execution import execute_tool_block

    rid = agent_tool_env["regular_session_id"]
    desc, result = await execute_tool_block(
        SimpleNamespace(tool_type="read_project_file", content="hello.py"),
        session_id=rid,
        owner="alice",
    )
    assert desc == "read_project_file: BLOCKED"
    assert result["exit_code"] == 1
    assert "project workspace" in result["error"].lower()


@pytest.mark.asyncio
async def test_project_file_tools_owner_isolation(agent_tool_env, tmp_path, monkeypatch):
    from src.tool_execution import execute_tool_block

    other_workspace = tmp_path / "other"
    other_workspace.mkdir()
    create_project(
        "bob",
        title="Bob project",
        working_dir=str(other_workspace),
        project_id="proj-bob",
    )
    manager = SessionManager()
    manager.sessions = {}
    bob_session = create_project_session(
        manager,
        "bob",
        "proj-bob",
        name="Bob chat",
    )

    desc, result = await execute_tool_block(
        SimpleNamespace(tool_type="read_project_file", content="secret.py"),
        session_id=bob_session["id"],
        owner="alice",
    )
    assert result["exit_code"] == 1
    assert "not found" in result["error"].lower()


@pytest.mark.asyncio
async def test_run_project_script_success(agent_tool_env):
    from src.tool_execution import execute_tool_block

    write_text_file(
        "alice",
        agent_tool_env["project_id"],
        "run_me.py",
        "print('agent run ok')\n",
    )
    pid = agent_tool_env["project_session_id"]
    desc, result = await execute_tool_block(
        SimpleNamespace(tool_type="run_project_script", content="run_me.py"),
        session_id=pid,
        owner="alice",
    )
    assert desc == "run_project_script: run_me.py"
    assert result["exit_code"] == 0
    assert "agent run ok" in result["output"]
    assert result.get("network_allowed") is False


@pytest.mark.asyncio
async def test_run_project_script_with_args(agent_tool_env):
    from src.tool_execution import execute_tool_block

    write_text_file(
        "alice",
        agent_tool_env["project_id"],
        "args_run.py",
        "import sys\nprint(sys.argv[1])\n",
    )
    pid = agent_tool_env["project_session_id"]
    desc, result = await execute_tool_block(
        SimpleNamespace(
            tool_type="run_project_script",
            content='args_run.py\n{"args": ["world"]}',
        ),
        session_id=pid,
        owner="alice",
    )
    assert result["exit_code"] == 0
    assert "world" in result["output"]


@pytest.mark.asyncio
async def test_run_project_script_rejects_non_python(agent_tool_env):
    from src.tool_execution import execute_tool_block

    write_text_file("alice", agent_tool_env["project_id"], "notes.txt", "nope\n")
    desc, result = await execute_tool_block(
        SimpleNamespace(tool_type="run_project_script", content="notes.txt"),
        session_id=agent_tool_env["project_session_id"],
        owner="alice",
    )
    assert result["exit_code"] == 1
    assert "only .py" in result["error"].lower()


@pytest.mark.asyncio
async def test_run_project_script_blocked_in_regular_session(agent_tool_env):
    from src.tool_execution import execute_tool_block

    desc, result = await execute_tool_block(
        SimpleNamespace(tool_type="run_project_script", content="run_me.py"),
        session_id=agent_tool_env["regular_session_id"],
        owner="alice",
    )
    assert desc == "run_project_script: BLOCKED"
    assert result["exit_code"] == 1


@pytest.mark.asyncio
async def test_run_project_script_rejects_path_traversal(agent_tool_env):
    from src.tool_execution import execute_tool_block

    write_text_file("alice", agent_tool_env["project_id"], "local.py", "print('ok')\n")
    desc, result = await execute_tool_block(
        SimpleNamespace(tool_type="run_project_script", content="../outside.py"),
        session_id=agent_tool_env["project_session_id"],
        owner="alice",
    )
    assert result["exit_code"] == 1
    assert "run_project_script" in (result.get("error") or "")


@pytest.mark.asyncio
async def test_run_project_script_truncates_large_output(agent_tool_env):
    from src.tool_execution import MAX_OUTPUT_CHARS, execute_tool_block

    write_text_file(
        "alice",
        agent_tool_env["project_id"],
        "big_out.py",
        f"print('{'x' * (MAX_OUTPUT_CHARS + 5000)}')\n",
    )
    desc, result = await execute_tool_block(
        SimpleNamespace(tool_type="run_project_script", content="big_out.py"),
        session_id=agent_tool_env["project_session_id"],
        owner="alice",
    )
    assert result["exit_code"] == 0
    assert result.get("output_truncated") is True
    assert len(result["output"]) <= MAX_OUTPUT_CHARS + 80
    assert "truncated" in result["output"]
