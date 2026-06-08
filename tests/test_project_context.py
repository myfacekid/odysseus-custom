"""Phase D4 — project session context injection (linked graph summaries)."""

import pytest

from src.knowledge_graph import add_graph_link, load_nodes, node_id, save_graph
from src.project_context import (
    build_active_project_file_block,
    build_linked_knowledge_block,
    build_project_session_preamble,
    build_project_tool_routing_block,
    sanitize_active_project_file_path,
)
from src.project_files import write_text_file
from src.project_graph import project_node_id
from src.project_workspace import create_project
from src.research_graph import research_node_dict


@pytest.fixture
def ctx_env(tmp_path, monkeypatch):
    monkeypatch.setattr("src.project_workspace.PROJECTS_ROOT", tmp_path / "projects")
    monkeypatch.setattr("src.project_graph.PROJECTS_ROOT", tmp_path / "projects")
    monkeypatch.setattr("src.knowledge_graph.KNOWLEDGE_ROOT", tmp_path / "knowledge")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    owner = "alice"
    create_project(
        owner,
        title="Context project",
        description="Study fibril structures",
        working_dir=str(workspace),
        project_id="proj-ctx",
    )
    return {"owner": owner, "project_id": "proj-ctx"}


def test_linked_knowledge_empty(ctx_env):
    block = build_linked_knowledge_block(ctx_env["owner"], ctx_env["project_id"])
    assert "No explicit graph links" in block
    assert "breadth boundary" in block


def test_linked_knowledge_includes_research_id(ctx_env):
    owner = ctx_env["owner"]
    pid = ctx_env["project_id"]
    research_id = node_id("research", "rs-alpha")
    nodes = load_nodes(owner)
    nodes[research_id] = research_node_dict(
        "rs-alpha",
        {
            "query": "Alpha synuclein fibrils",
            "research_mode": "literature_review",
            "status": "done",
            "stats": {"Rounds": 2},
        },
    )
    save_graph(owner, nodes, [])
    add_graph_link(owner, project_node_id(pid), research_id, kind="related")

    block = build_linked_knowledge_block(owner, pid)
    assert research_id in block
    assert "Alpha synuclein fibrils" in block
    assert "literature_review" in block.lower() or "Literature" in block


def test_linked_knowledge_stale_link(ctx_env):
    owner = ctx_env["owner"]
    pid = ctx_env["project_id"]
    stale_id = node_id("paper", "MISSING999")
    from src.knowledge_graph import load_edges

    edges = load_edges(owner)
    edges.append({"from": project_node_id(pid), "to": stale_id, "kind": "related"})
    save_graph(owner, load_nodes(owner), edges)

    block = build_linked_knowledge_block(owner, pid)
    assert "missing from graph" in block
    assert stale_id in block


def test_project_session_preamble_includes_description_and_links(ctx_env):
    owner = ctx_env["owner"]
    pid = ctx_env["project_id"]
    paper_id = node_id("paper", "PAPER1")
    nodes = load_nodes(owner)
    nodes[paper_id] = {
        "id": paper_id,
        "type": "paper",
        "title": "Seed paper",
        "snippet": "Key methods",
        "updated_at": "",
        "meta": {"zotero_key": "PAPER1"},
    }
    save_graph(owner, nodes, [])
    add_graph_link(owner, project_node_id(pid), paper_id, kind="cites")

    from src.project_workspace import get_project

    project = get_project(owner, pid)
    preamble = build_project_session_preamble(owner, pid, project)
    assert "Study fibril structures" in preamble
    assert paper_id in preamble
    assert "Seed paper" in preamble
    assert "Three file paradigms" in preamble
    assert "run_project_script" in preamble
    assert "Tool routing (project chat" in preamble


def test_tool_routing_block_lists_blocked_tools():
    block = build_project_tool_routing_block()
    assert "write_project_file" in block
    assert "edit_document" in block
    assert "read_file" in block


def test_sanitize_active_project_file_path():
    assert sanitize_active_project_file_path("src/run.py") == "src/run.py"
    assert sanitize_active_project_file_path("../escape.py") is None
    assert sanitize_active_project_file_path("/etc/passwd") is None


def test_active_project_file_block(ctx_env):
    owner = ctx_env["owner"]
    pid = ctx_env["project_id"]
    write_text_file(owner, pid, "hello.py", "print('hi')\n")
    block = build_active_project_file_block(owner, pid, "hello.py")
    assert "hello.py" in block
    assert "write_project_file" in block
    assert "print('hi')" in block


def test_preamble_with_active_file(ctx_env):
    owner = ctx_env["owner"]
    pid = ctx_env["project_id"]
    write_text_file(owner, pid, "main.py", "x = 1\n")
    from src.project_workspace import get_project

    project = get_project(owner, pid)
    preamble = build_project_session_preamble(
        owner, pid, project, active_file_path="main.py",
    )
    assert "Active project file" in preamble
    assert "main.py" in preamble
    assert "x = 1" in preamble
