"""Phase D4 — project session context injection (linked graph summaries)."""

import pytest

from src.knowledge_graph import add_graph_link, execute_knowledge_tool, load_nodes, node_id, save_graph
from src.project_context import (
    build_active_project_file_block,
    build_linked_knowledge_block,
    build_project_session_preamble,
    build_project_tool_routing_block,
    build_proposed_connections_block,
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


def test_suggest_link_requires_reason(ctx_env):
    owner = ctx_env["owner"]
    nodes = {
        "document:a": {
            "id": "document:a", "type": "document", "title": "A", "snippet": "s", "meta": {},
        },
        "document:b": {
            "id": "document:b", "type": "document", "title": "B", "snippet": "s", "meta": {},
        },
    }
    save_graph(owner, nodes, [])

    bad = execute_knowledge_tool(
        {"action": "suggest_link", "from": "document:a", "to": "document:b", "kind": "relates"},
        owner=owner,
    )
    assert bad["exit_code"] == 1
    assert "reason is required" in bad["error"]

    good = execute_knowledge_tool(
        {
            "action": "suggest_link",
            "from": "document:a",
            "to": "document:b",
            "kind": "supports",
            "reason": "Same experiment cohort",
        },
        owner=owner,
    )
    assert good["exit_code"] == 0
    assert good.get("action") == "suggest_link"
    assert good.get("reason") == "Same experiment cohort"


def test_linked_knowledge_shows_reason_and_sorts_by_kind(ctx_env):
    owner = ctx_env["owner"]
    pid = ctx_env["project_id"]
    paper_a = node_id("paper", "PAPER_A")
    paper_b = node_id("paper", "PAPER_B")
    nodes = load_nodes(owner)
    nodes[paper_a] = {
        "id": paper_a, "type": "paper", "title": "Weak topic match", "snippet": "s", "meta": {},
    }
    nodes[paper_b] = {
        "id": paper_b, "type": "paper", "title": "Strong refutation", "snippet": "s", "meta": {},
    }
    save_graph(owner, nodes, [])
    add_graph_link(
        owner,
        project_node_id(pid),
        paper_a,
        kind="relates",
        reason="Same broad topic",
    )
    add_graph_link(
        owner,
        project_node_id(pid),
        paper_b,
        kind="refutes",
        reason="Benchmark contradicts our assumption",
    )

    block = build_linked_knowledge_block(owner, pid)
    assert "Reason:" in block or "_Reason:_" in block
    assert "Benchmark contradicts" in block
    assert block.index("Strong refutation") < block.index("Weak topic match")


def test_linked_knowledge_caps_weak_relates(ctx_env):
    owner = ctx_env["owner"]
    pid = ctx_env["project_id"]
    nodes = load_nodes(owner)
    for i in range(12):
        pid_paper = node_id("paper", f"REL{i:04d}")
        nodes[pid_paper] = {
            "id": pid_paper,
            "type": "paper",
            "title": f"Relates paper {i}",
            "snippet": "s",
            "meta": {},
        }
    save_graph(owner, nodes, [])
    for i in range(12):
        add_graph_link(owner, project_node_id(pid), node_id("paper", f"REL{i:04d}"), kind="relates")

    block = build_linked_knowledge_block(owner, pid, max_links=24)
    assert "Relates paper" in block
    assert "weak `relates`" in block.lower() or "cap" in block.lower()


def test_preamble_includes_proposed_connections(ctx_env):
    from src.pending_graph_edges import enqueue_proposals
    from src.project_workspace import get_project

    owner = ctx_env["owner"]
    pid = ctx_env["project_id"]
    paper_a = node_id("paper", "PROP_A")
    paper_b = node_id("paper", "PROP_B")
    nodes = load_nodes(owner)
    nodes[paper_a] = {"id": paper_a, "type": "paper", "title": "Alpha", "snippet": "s", "meta": {}}
    nodes[paper_b] = {"id": paper_b, "type": "paper", "title": "Beta", "snippet": "s", "meta": {}}
    save_graph(owner, nodes, [])
    add_graph_link(owner, project_node_id(pid), paper_a, kind="relates")

    enqueue_proposals(owner, [{
        "from": paper_a,
        "to": paper_b,
        "kind": "supports",
        "reason": "Shared benchmark",
        "project_id": pid,
    }], source="compare_papers")

    project = get_project(owner, pid)
    preamble = build_project_session_preamble(owner, pid, project)
    assert "[PROPOSED]" in preamble
    assert "PROP_B" in preamble or "Beta" in preamble
    assert "Shared benchmark" in preamble


def test_neighbors_include_proposed_flag(ctx_env):
    owner = ctx_env["owner"]
    paper_a = node_id("paper", "N_A")
    paper_b = node_id("paper", "N_B")
    save_graph(owner, {
        paper_a: {"id": paper_a, "type": "paper", "title": "A", "snippet": "s", "meta": {}},
        paper_b: {"id": paper_b, "type": "paper", "title": "B", "snippet": "s", "meta": {}},
    }, [])
    from src.pending_graph_edges import enqueue_proposals

    enqueue_proposals(owner, [{
        "from": paper_a,
        "to": paper_b,
        "kind": "refutes",
        "reason": "Pending contrast",
    }], source="agent")

    without = execute_knowledge_tool(
        {"action": "neighbors", "id": paper_a},
        owner=owner,
    )
    assert without["exit_code"] == 0
    assert "Pending contrast" not in without["output"]
    assert "Proposed (awaiting" not in without["output"]

    with_prop = execute_knowledge_tool(
        {"action": "neighbors", "id": paper_a, "include_proposed": True},
        owner=owner,
    )
    assert with_prop["exit_code"] == 0
    assert "[PROPOSED]" in with_prop["output"]
    assert "Pending contrast" in with_prop["output"]


def test_list_pending_action(ctx_env):
    owner = ctx_env["owner"]
    from src.pending_graph_edges import enqueue_proposals

    enqueue_proposals(owner, [{
        "from": "paper:X",
        "to": "paper:Y",
        "kind": "relates",
        "reason": "Queued link",
    }], source="agent")

    out = execute_knowledge_tool({"action": "list_pending"}, owner=owner)
    assert out["exit_code"] == 0
    assert "[PROPOSED]" in out["output"]
    assert out.get("count", 0) >= 1


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
