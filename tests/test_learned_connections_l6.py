"""L6 — additional learned-connection producers."""

import pytest

from src.knowledge_graph import save_graph
from src.pending_graph_edges import enqueue_proposals, load_pending_edges


def _seed_papers(tmp_path, monkeypatch, owner="tester"):
    monkeypatch.setattr("src.knowledge_graph.KNOWLEDGE_ROOT", tmp_path / "knowledge")
    nodes = {
        "paper:A": {"id": "paper:A", "type": "paper", "title": "Paper A", "snippet": "s", "meta": {}},
        "paper:B": {"id": "paper:B", "type": "paper", "title": "Paper B", "snippet": "s", "meta": {}},
    }
    save_graph(owner, nodes, [])
    return owner


def test_enqueue_applies_project_id(tmp_path, monkeypatch):
    owner = _seed_papers(tmp_path, monkeypatch)
    out = enqueue_proposals(owner, [{
        "from": "paper:A",
        "to": "paper:B",
        "kind": "relates",
        "reason": "Scoped",
    }], source="agent")
    assert out["added"] == 1
    pending = load_pending_edges(owner)
    assert pending[0].get("project_id") is None

    out2 = enqueue_proposals(owner, [{
        "from": "paper:B",
        "to": "paper:A",
        "kind": "supports",
        "reason": "Project scoped",
        "project_id": "proj-xyz",
    }], source="agent")
    assert out2["added"] == 1
    pending = load_pending_edges(owner)
    tagged = next(r for r in pending if r.get("kind") == "supports")
    assert tagged.get("project_id") == "proj-xyz"


def test_compare_papers_library_route(tmp_path, monkeypatch):
    from unittest.mock import patch

    from src.paper_compare import execute_compare_papers

    owner = _seed_papers(tmp_path, monkeypatch)
    fake_slice = {
        "zotero_key": "PAPER001",
        "title": "Paper A",
        "content": "methods text",
        "source_tier": "abstract",
        "source_label": "abstract",
    }
    with patch("src.paper_compare.gather_paper_slice", return_value=fake_slice):
        result = execute_compare_papers(
            {"paper_keys": ["PAPER001", "PAPER002"], "focus": "methods"},
            owner=owner,
        )
    assert result.get("exit_code") == 0
    assert isinstance(result.get("suggested_edges"), list)


def test_link_proposal_project_id_helper():
    from src.agent_loop import _link_proposal_project_id

    assert _link_proposal_project_id(None) is None
    assert _link_proposal_project_id("missing-session") is None


@pytest.mark.asyncio
async def test_maybe_extract_links_skips_without_graph_tools(tmp_path, monkeypatch):
    from src.link_extractor import maybe_extract_links

    class _Sess:
        def get_context_messages(self):
            return [
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "hi there"},
            ]

    monkeypatch.setattr("src.knowledge_graph.KNOWLEDGE_ROOT", tmp_path / "knowledge")
    out = await maybe_extract_links(_Sess(), "http://x", "m", {}, 3, 3, owner="tester")
    assert out is None


@pytest.mark.asyncio
async def test_maybe_extract_links_enqueues(monkeypatch, tmp_path):
    from src.link_extractor import maybe_extract_links

    monkeypatch.setattr("src.knowledge_graph.KNOWLEDGE_ROOT", tmp_path / "knowledge")
    _seed_papers(tmp_path, monkeypatch)

    class _Sess:
        def get_context_messages(self):
            return [
                {"role": "user", "content": "compare paper:A and paper:B"},
                {"role": "assistant", "content": "```compare_papers\\n{...}\\n``` supports link"},
            ]

    async def _fake_llm(*_a, **_k):
        return '[{"from":"paper:A","to":"paper:B","kind":"supports","reason":"Same cohort","confidence":0.9}]'

    monkeypatch.setattr("src.llm_core.llm_call_async", _fake_llm)
    monkeypatch.setattr(
        "src.project_tool_policy.get_session_project_id",
        lambda _sid: "proj-l6",
    )

    out = await maybe_extract_links(
        _Sess(), "http://x", "m", {}, 2, 2, owner="tester", session_id="sess-1",
    )
    assert out and out.get("added", 0) >= 1
    pending = load_pending_edges("tester")
    assert any(r.get("source") == "session_extract" for r in pending)
    row = next(r for r in pending if r.get("source") == "session_extract")
    assert row.get("project_id") == "proj-l6"
    assert row.get("source_session") == "chat:sess-1"
