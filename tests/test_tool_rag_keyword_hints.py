"""Regression for issue #1707 — the agent tool-RAG force-included the entire
email toolset on any "tell me ..." query, crowding out the relevant tools so the
model believed it only had email tools and refused web/other tasks.

Root cause: `_KEYWORD_HINTS` in src/tool_index.py listed "tell" under the email
intent, and `get_tools_for_query` force-includes a hint's tools whenever any of
its keywords appears (word-boundary match). "tell" appears in a huge fraction of
requests (the reporter's was "visit <url> and tell me the title"), so email tools
were force-included for non-email queries.

These hints are deterministic string matching — no embeddings — so we can test
`get_tools_for_query` directly with retrieval stubbed out (no ChromaDB needed).

Also covers Links / Todos / panel / memory keyword coverage from the tool-calling
awareness pass.
"""

from src.agent_tools import TOOL_TAGS
from src.tool_index import ToolIndex, ALWAYS_AVAILABLE
from src.tool_schemas import FUNCTION_TOOL_SCHEMAS

_EMAIL_TOOLS = {
    "list_emails", "read_email", "send_email", "reply_to_email",
    "bulk_email", "delete_email", "archive_email", "mark_email_read",
}


def _index_without_embeddings():
    """A ToolIndex whose retrieval returns nothing, so get_tools_for_query
    exercises only the deterministic base + keyword-hint logic."""
    ti = ToolIndex.__new__(ToolIndex)        # skip __init__ (no ChromaDB/fastembed)
    ti.retrieve = lambda query, k=8: []
    return ti


def test_tell_in_web_query_does_not_force_email_tools():
    """The #1707 repro: a web request that merely contains the word 'tell' must
    NOT drag in the email toolset."""
    ti = _index_without_embeddings()
    q = "visit https://www.youtube.com/user/PewDiePie and tell me the title of his latest video"
    tools = ti.get_tools_for_query(q)
    leaked = _EMAIL_TOOLS & tools
    assert not leaked, f"'tell me' must not force-include email tools, got {sorted(leaked)}"
    # web_search / web_fetch are always-available and must remain present.
    assert "web_search" in tools and "web_fetch" in tools


def test_genuine_email_query_does_not_require_builtin_email_hints():
    """Email is MCP-backed now — keyword hints no longer map inbox phrases to
    builtin list_emails/send_email. A real inbox query must still avoid the
    #1707 failure mode of crowding the toolset with a fake email suite."""
    ti = _index_without_embeddings()
    tools = ti.get_tools_for_query("reply to the unread email in my inbox")
    assert not (_EMAIL_TOOLS & tools)


def test_plain_tell_request_stays_minimal():
    """A bare 'tell me a joke' must not pull in email tools either."""
    ti = _index_without_embeddings()
    tools = ti.get_tools_for_query("tell me a joke")
    assert not (_EMAIL_TOOLS & tools)
    # Always-available baseline is still there.
    assert set(ALWAYS_AVAILABLE) <= tools


def test_suggest_links_force_includes_search_knowledge():
    ti = _index_without_embeddings()
    for q in (
        "suggest links between these papers",
        "set up links for these documents",
        "propose a link",
        "connect these",
        "link these",
    ):
        tools = ti.get_tools_for_query(q)
        assert "search_knowledge" in tools, f"{q!r} must include search_knowledge"


def test_suggest_doc_improvements_does_not_force_graph_tools():
    """Document review phrasing must not force search_knowledge via bare 'suggest'."""
    ti = _index_without_embeddings()
    tools = ti.get_tools_for_query("suggest improvements to the doc")
    assert "suggest_document" in tools or "edit_document" in tools
    assert "search_knowledge" not in tools


def test_open_research_prefers_ui_control_not_manage_research():
    ti = _index_without_embeddings()
    tools = ti.get_tools_for_query("open research")
    assert "ui_control" in tools
    assert "manage_research" not in tools
    assert "trigger_research" not in tools


def test_read_research_still_gets_manage_research():
    ti = _index_without_embeddings()
    tools = ti.get_tools_for_query("read research about epistasis")
    assert "manage_research" in tools


def test_remember_that_gets_memory_not_notes():
    ti = _index_without_embeddings()
    tools = ti.get_tools_for_query("remember that my name is Ada")
    assert "manage_memory" in tools


def test_remember_to_still_gets_notes():
    ti = _index_without_embeddings()
    tools = ti.get_tools_for_query("remember to buy milk")
    assert "manage_notes" in tools


def test_open_todos_gets_ui_control():
    ti = _index_without_embeddings()
    tools = ti.get_tools_for_query("open todos")
    assert "ui_control" in tools


def test_generate_image_keywords():
    ti = _index_without_embeddings()
    tools = ti.get_tools_for_query("generate an image of a cat")
    assert "generate_image" in tools


def test_search_chats_keywords():
    ti = _index_without_embeddings()
    tools = ti.get_tools_for_query("did we discuss the deadline")
    assert "search_chats" in tools


def test_cookbook_ambient_tools_always_available():
    assert "list_downloads" in ALWAYS_AVAILABLE
    assert "list_cached_models" in ALWAYS_AVAILABLE
    assert "list_served_models" in ALWAYS_AVAILABLE
    assert "app_api" in ALWAYS_AVAILABLE


def test_search_vault_not_advertised():
    assert "search_vault" not in TOOL_TAGS
    names = {s["function"]["name"] for s in FUNCTION_TOOL_SCHEMAS}
    assert "search_vault" not in names
