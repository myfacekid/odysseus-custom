"""Link suggestion SSE emit-once + prompt batching guidance.

Chat UI mounts suggestions inline; embedding the same payload on tool_output
caused a double-dispatch race. Prompts must tell models to queue the full set
in one tool round (not dribble across rounds / floating toast wording).
"""

from pathlib import Path

_AGENT_LOOP = Path(__file__).resolve().parents[1] / "src" / "agent_loop.py"
_TOOL_SCHEMAS = Path(__file__).resolve().parents[1] / "src" / "tool_schemas.py"
_TOOL_INDEX = Path(__file__).resolve().parents[1] / "src" / "tool_index.py"


def test_tool_output_does_not_reembed_link_suggestion_payloads():
    """Standalone link_suggestion / graph_merge_proposals SSE only — not on tool_output."""
    src = _AGENT_LOOP.read_text(encoding="utf-8")
    assert 'tool_output_data["link_suggestion"]' not in src
    assert 'tool_output_data["graph_merge_proposals"]' not in src
    # Standalone events must still exist.
    assert '"type": "link_suggestion"' in src
    assert '"type": "graph_merge_proposals"' in src


def test_search_knowledge_section_batches_in_one_round():
    src = _AGENT_LOOP.read_text(encoding="utf-8")
    # Locate the search_knowledge TOOL_SECTIONS entry.
    start = src.index('"search_knowledge":')
    end = src.index('""",', start) + 3
    section = src[start:end]
    assert "tool round" in section.lower()
    assert "dribble" in section.lower()
    assert "in-chat review" in section.lower()
    assert "Confirm toast" not in section
    assert "pop-up" not in section.lower()


def test_routing_prompt_rejects_drip_and_toast_wording():
    src = _AGENT_LOOP.read_text(encoding="utf-8")
    assert "Confirm toast / Connections inbox" not in src
    assert "Do **not** dribble more `suggest_link`" in src
    assert "in-chat review card" in src


def test_tool_schema_and_index_mention_one_shot_batching():
    schemas = _TOOL_SCHEMAS.read_text(encoding="utf-8")
    index = _TOOL_INDEX.read_text(encoding="utf-8")
    assert "all in one tool round" in schemas or "same tool round" in schemas
    assert "dribble" in schemas.lower()
    assert "same tool round" in index or "do not dribble" in index.lower()
