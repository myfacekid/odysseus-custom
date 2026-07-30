"""LDR Phase L0 spike — construct LangGraph stack when LDR is installed."""

import pytest

from src.research.ldr_availability import ldr_stack_available


@pytest.mark.skipif(not ldr_stack_available(), reason="LDR stack not installed")
def test_ldr_settings_snapshot_programmatic_mode():
    from local_deep_research.api.settings_utils import create_settings_snapshot

    snap = create_settings_snapshot(
        {
            "search.tool": "searxng",
            "search.search_strategy": "langgraph-agent",
            "langgraph_agent.max_iterations": 12,
        }
    )
    assert snap
    tool = snap.get("search.tool")
    value = tool.get("value") if isinstance(tool, dict) else tool
    assert value == "searxng"


@pytest.mark.skipif(not ldr_stack_available(), reason="LDR stack not installed")
def test_ldr_langgraph_strategy_builds_tools():
    """Smoke: LangGraphAgentStrategy exposes academic search tools without running the agent."""
    from unittest.mock import MagicMock

    from local_deep_research.advanced_search_system.strategies.langgraph_agent_strategy import (
        SearchResultsCollector,
        LangGraphAgentStrategy,
    )
    from local_deep_research.api.settings_utils import create_settings_snapshot

    snap = create_settings_snapshot({"search.tool": "duckduckgo"})
    collector = SearchResultsCollector([])
    strategy = LangGraphAgentStrategy(
        model=MagicMock(),
        search=MagicMock(),
        all_links_of_system=collector._all_links,
        settings_snapshot=snap,
        programmatic_mode=True,
        max_iterations=12,
        include_sub_research=False,
    )
    tools = strategy._build_tools(overall_query="protein folding benchmarks")
    names = {getattr(t, "name", "") for t in tools}
    assert "web_search" in names
    # At least one specialized academic engine when config loads.
    assert any(n.startswith("search_") for n in names)


@pytest.mark.skipif(not ldr_stack_available(), reason="LDR stack not installed")
def test_ldr_advanced_search_system_instantiates():
    from unittest.mock import MagicMock

    from local_deep_research.api.settings_utils import create_settings_snapshot
    from local_deep_research.config.search_config import get_search
    from local_deep_research.search_system import AdvancedSearchSystem

    model = MagicMock()
    snap = create_settings_snapshot(
        {"search.tool": "duckduckgo", "search.search_strategy": "langgraph-agent"}
    )
    search = get_search("duckduckgo", llm_instance=model, settings_snapshot=snap, programmatic_mode=True)
    system = AdvancedSearchSystem(
        llm=model,
        search=search,
        strategy_name="langgraph-agent",
        settings_snapshot=snap,
        programmatic_mode=True,
        max_iterations=12,
    )
    assert system.strategy is not None
    try:
        system.close()
    except Exception:
        pass
