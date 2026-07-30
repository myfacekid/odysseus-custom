"""Agent manage_notes add_one_thing must pass parent_ids for Todos hierarchy."""
import asyncio
import json
import sys
import types
from types import SimpleNamespace
from unittest.mock import MagicMock

from src import tool_implementations
from src.one_thing import OneThingTask, format_agent_list


def _install_db(monkeypatch):
    fake_sa_attrs = types.ModuleType("sqlalchemy.orm.attributes")
    fake_sa_attrs.flag_modified = lambda *a, **k: None
    monkeypatch.setitem(sys.modules, "sqlalchemy.orm.attributes", fake_sa_attrs)

    class FakeDB:
        def query(self, *a, **k):
            return MagicMock()

        def add(self, *a, **k):
            pass

        def commit(self):
            pass

        def close(self):
            pass

    fake_core_db = types.ModuleType("core.database")
    fake_core_db.SessionLocal = lambda: FakeDB()
    fake_core_db.Note = MagicMock()
    monkeypatch.setitem(sys.modules, "core.database", fake_core_db)


def _run(args, owner="user"):
    return asyncio.run(tool_implementations.do_manage_notes(json.dumps(args), owner=owner))


def test_add_one_thing_passes_parent_ids(monkeypatch):
    _install_db(monkeypatch)
    captured = {}

    def fake_add(db, owner, text, **kw):
        captured.update(kw)
        captured["text"] = text
        return SimpleNamespace(
            id="aaaaaaaa-0000-4000-8000-000000000001",
            horizon=kw.get("horizon") or "focus",
            priority=kw.get("priority") or "steady",
            text=text,
            parent_ids=list(kw.get("parent_ids") or []),
        )

    monkeypatch.setattr("src.one_thing.add_task", fake_add)
    monkeypatch.setattr("src.knowledge_sync.after_task_change", lambda *a, **k: None)

    out = _run({
        "action": "add_one_thing",
        "text": "Draft methods",
        "horizon": "focus",
        "parent_ids": ["bbbbbbbb"],
    })
    assert out.get("exit_code") == 0
    assert captured.get("parent_ids") == ["bbbbbbbb"]
    assert "parents=" in out.get("response", "")


def test_add_one_thing_missing_parents_lists_candidates(monkeypatch):
    _install_db(monkeypatch)

    def fake_add(db, owner, text, **kw):
        raise ValueError("Immediate Tasks must link to at least one Intermediate Goals goal")

    def fake_list(db, owner, horizon=None, include_done=False):
        return [
            OneThingTask(id="build000-0000-4000-8000-000000000001", text="Ship thesis", horizon="build"),
        ]

    monkeypatch.setattr("src.one_thing.add_task", fake_add)
    monkeypatch.setattr("src.one_thing.list_tasks", fake_list)

    out = _run({
        "action": "add_one_thing",
        "text": "Today task",
        "horizon": "focus",
    })
    assert out.get("exit_code") == 1
    err = out.get("error") or ""
    assert "must link" in err
    assert "Ship thesis" in err
    assert "parent_ids" in err


def test_format_agent_list_shows_parents():
    parent = OneThingTask(
        id="parent00-0000-4000-8000-000000000001",
        text="Quarterly outcome",
        horizon="build",
    )
    child = OneThingTask(
        id="child000-0000-4000-8000-000000000002",
        text="Today task",
        horizon="focus",
        parent_ids=[parent.id],
    )
    text = format_agent_list([parent, child])
    assert "parents:" in text
    assert "Quarterly outcome" in text
    assert "Hierarchy:" in text


def test_manage_notes_schema_has_parent_ids():
    from src.tool_schemas import FUNCTION_TOOL_SCHEMAS

    schema = next(s for s in FUNCTION_TOOL_SCHEMAS if s["function"]["name"] == "manage_notes")
    assert "parent_ids" in schema["function"]["parameters"]["properties"]
