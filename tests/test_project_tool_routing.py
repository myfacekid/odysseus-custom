"""Phase D5/D6 — project session tool routing + agent-loop integration."""

import uuid
from types import SimpleNamespace

import pytest

import core.database as cdb
import core.session_manager as SM
from core.session_manager import SessionManager
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from src.agent_loop import _build_system_prompt
from src.knowledge_graph import add_graph_link, load_nodes, node_id, save_graph
from src.project_graph import project_node_id
from src.project_sessions import create_project_session
from src.project_tool_policy import (
    PROJECT_BREADTH_TOOL_EXAMPLES,
    apply_session_tool_policy,
    disabled_tools_for_project_session,
)
from src.project_workspace import create_project
from src.research_graph import research_node_dict
from src.tool_schemas import FUNCTION_TOOL_SCHEMAS


@pytest.fixture
def routing_env(tmp_path, monkeypatch):
    db_path = tmp_path / "routing.db"
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
    monkeypatch.setattr("src.project_graph.PROJECTS_ROOT", tmp_path / "projects")
    monkeypatch.setattr("src.knowledge_graph.KNOWLEDGE_ROOT", tmp_path / "knowledge")

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    create_project(
        "alice",
        title="Routing project",
        description="Tool routing integration",
        working_dir=str(workspace),
        project_id="proj-route",
    )

    research_id = node_id("research", "rs-route")
    nodes = load_nodes("alice")
    nodes[research_id] = research_node_dict(
        "rs-route",
        {
            "query": "Protein folding benchmarks",
            "research_mode": "literature_review",
            "status": "done",
            "stats": {"Rounds": 1},
        },
    )
    save_graph("alice", nodes, [])
    add_graph_link("alice", project_node_id("proj-route"), research_id, kind="related")

    manager = SessionManager()
    manager.sessions = {}
    created = create_project_session(
        manager,
        "alice",
        "proj-route",
        name="Routing chat",
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
        "research_id": research_id,
    }


def _visible_tool_names(disabled: set) -> set:
    return {
        t.get("function", {}).get("name")
        for t in FUNCTION_TOOL_SCHEMAS
        if t.get("function", {}).get("name") not in disabled
    }


def test_apply_session_tool_policy_project_session(routing_env):
    disabled = apply_session_tool_policy(set(), routing_env["project_session_id"])
    assert disabled_tools_for_project_session().issubset(disabled)
    for breadth in PROJECT_BREADTH_TOOL_EXAMPLES:
        assert breadth not in disabled


def test_apply_session_tool_policy_regular_session(routing_env):
    disabled = apply_session_tool_policy(set(), routing_env["regular_session_id"])
    assert "read_project_file" in disabled
    assert "write_project_file" in disabled
    assert "run_project_script" in disabled
    assert "bash" not in disabled


def test_project_session_tool_schema_filter(routing_env):
    disabled = apply_session_tool_policy(set(), routing_env["project_session_id"])
    names = _visible_tool_names(disabled)
    assert {"read_project_file", "write_project_file", "run_project_script", "promote_project_file"}.issubset(names)
    assert "search_knowledge" in names
    assert "create_document" in names
    assert "bash" not in names
    assert "python" not in names
    assert "read_file" not in names
    assert "write_file" not in names


def test_regular_session_hides_project_tools(routing_env):
    disabled = apply_session_tool_policy(set(), routing_env["regular_session_id"])
    names = _visible_tool_names(disabled)
    assert "read_project_file" not in names
    assert "run_project_script" not in names
    assert "promote_project_file" not in names
    assert "bash" in names


def test_build_system_prompt_injects_project_context(routing_env):
    pid = routing_env["project_session_id"]
    disabled = apply_session_tool_policy(set(), pid)
    messages, _ = _build_system_prompt(
        messages=[{"role": "user", "content": "Summarize linked research"}],
        model="test-model",
        active_document=None,
        mcp_mgr=None,
        disabled_tools=disabled,
        owner="alice",
        session_id=pid,
    )
    system_text = "\n".join(
        m.get("content") or "" for m in messages if m.get("role") == "system"
    )
    assert "Three file paradigms" in system_text
    assert "Tool routing (project chat" in system_text
    assert routing_env["research_id"] in system_text
    assert "Protein folding benchmarks" in system_text
    assert "read_project_file" in system_text


def test_build_system_prompt_skips_project_block_for_regular_session(routing_env):
    rid = routing_env["regular_session_id"]
    disabled = apply_session_tool_policy(set(), rid)
    messages, _ = _build_system_prompt(
        messages=[{"role": "user", "content": "hello"}],
        model="test-model",
        active_document=None,
        mcp_mgr=None,
        disabled_tools=disabled,
        owner="alice",
        session_id=rid,
    )
    system_text = "\n".join(
        m.get("content") or "" for m in messages if m.get("role") == "system"
    )
    assert "Three file paradigms" not in system_text
    assert routing_env["research_id"] not in system_text


@pytest.mark.asyncio
async def test_execute_tool_block_mcp_filesystem_denied_in_project(routing_env):
    from src.tool_execution import execute_tool_block

    desc, result = await execute_tool_block(
        SimpleNamespace(tool_type="mcp__filesystem__read_file", content="/etc/passwd"),
        session_id=routing_env["project_session_id"],
        owner="alice",
    )
    assert desc == "mcp__filesystem__read_file: BLOCKED"
    assert result["exit_code"] == 1
    assert "project workspace" in result["error"].lower()


@pytest.mark.asyncio
async def test_execute_tool_block_breadth_tool_allowed_in_project(routing_env):
    """Breadth tools are not blocked by project depth policy at execution."""
    from src.project_tool_policy import project_tool_block_reason

    assert project_tool_block_reason("search_knowledge", routing_env["project_session_id"]) is None
    assert project_tool_block_reason("create_document", routing_env["project_session_id"]) is None
