"""Tests for plan mode denylist + plan parsing."""

from src.plan_mode import (
    PLAN_WRITE_DENYLIST,
    format_plan_for_execution,
    parse_plan_from_text,
    strip_plan_fence,
)


def test_write_denylist_covers_effectful_tools():
    for name in (
        "bash",
        "python",
        "write_file",
        "create_document",
        "edit_document",
        "manage_notes",
        "trigger_research",
        "ui_control",
        "serve_model",
    ):
        assert name in PLAN_WRITE_DENYLIST
    assert "read_file" not in PLAN_WRITE_DENYLIST
    assert "web_search" not in PLAN_WRITE_DENYLIST
    assert "search_knowledge" not in PLAN_WRITE_DENYLIST


def test_parse_plan_json_fence():
    text = """Here is the approach.

```plan
{
  "title": "Refactor auth",
  "overview": "Tighten session checks",
  "steps": [
    {"title": "Audit routes", "detail": "Find owner checks"},
    {"title": "Add tests", "detail": ""}
  ],
  "risks": ["May break legacy clients"]
}
```
"""
    plan = parse_plan_from_text(text)
    assert plan is not None
    assert plan["title"] == "Refactor auth"
    assert plan["overview"].startswith("Tighten")
    assert len(plan["steps"]) == 2
    assert plan["steps"][0]["title"] == "Audit routes"
    assert plan["risks"] == ["May break legacy clients"]
    assert plan["status"] == "ready"
    stripped = strip_plan_fence(text)
    assert "```plan" not in stripped
    assert "Here is the approach" in stripped


def test_parse_plan_markdown_fallback():
    text = """# Ship dark mode

Flip theme tokens carefully.

1. Inventory CSS variables
2. Add a toggle
3. Persist preference
"""
    plan = parse_plan_from_text(text)
    assert plan is not None
    assert plan["title"] == "Ship dark mode"
    assert len(plan["steps"]) >= 3
    assert "Inventory" in plan["steps"][0]["title"]


def test_format_plan_for_execution():
    plan = {
        "title": "Do the thing",
        "overview": "Overview line",
        "steps": [{"title": "One", "detail": "detail"}],
        "risks": ["careful"],
    }
    out = format_plan_for_execution(plan)
    assert "Approved plan: Do the thing" in out
    assert "Overview line" in out
    assert "1. One — detail" in out
    assert "careful" in out
