"""Tests for One Thing / Todos task board."""

from pathlib import Path

from src.one_thing import (
    OneThingTask,
    extract_horizon_section,
    format_task_line,
    merge_section,
    normalize_horizon,
    normalize_priority,
    parse_task_line,
    tasks_from_section,
)
from src.vault_one_thing_sync import import_from_vault, _import_section_tasks


def test_normalize_horizon_aliases():
    assert normalize_horizon("this week") == "focus"
    assert normalize_horizon("immediate tasks") == "focus"
    assert normalize_horizon("intermediate") == "build"
    assert normalize_horizon("year") == "aim"
    assert normalize_horizon("miscellaneous") == "misc"


def test_normalize_priority_aliases():
    assert normalize_priority("high") == "critical"
    assert normalize_priority("medium") == "elevated"
    assert normalize_priority("low") == "steady"


def test_format_and_parse_task_line_roundtrip():
    task = OneThingTask(
        id="abc12345-0000-4000-8000-000000000001",
        text="Finish figure 3",
        horizon="focus",
        priority="critical",
        due_date="2026-06-05",
    )
    line = format_task_line(task)
    assert "`nobody:abc12345" in line
    assert "📅 2026-06-05" in line
    assert "⏫" in line
    parsed = parse_task_line(line, default_horizon="focus")
    assert parsed is not None
    assert parsed.id == "abc12345-0000-4000-8000-000000000001"
    assert parsed.text == "Finish figure 3"
    assert parsed.due_date == "2026-06-05"
    assert parsed.priority == "critical"


def test_parse_task_line_without_nobody_id():
    parsed = parse_task_line("- [ ] Plain vault task", default_horizon="focus")
    assert parsed is not None
    assert parsed.text == "Plain vault task"
    assert not parsed.done


def test_extract_horizon_section_current_and_legacy():
    body = (
        "## Immediate Tasks\n"
        "<!-- nobody-horizon:focus -->\n\n"
        "- [ ] Finish figure 3\n\n"
        "## Other\n"
    )
    section = extract_horizon_section(body, "focus")
    assert "- [ ] Finish figure 3" in section

    legacy = (
        "## One Thing — This Week\n\n"
        "- [ ] Legacy weekly task\n"
    )
    section = extract_horizon_section(legacy, "focus")
    assert "- [ ] Legacy weekly task" in section


def test_merge_section_replaces_horizon_block():
    body = "## Immediate Tasks\n<!-- nobody-horizon:focus -->\n\n- [ ] old task\n"
    new_section = "## Immediate Tasks\n<!-- nobody-horizon:focus -->\n\n- [ ] new task · `nobody:x`\n"
    merged = merge_section(body, "focus", new_section)
    assert "new task" in merged
    assert "old task" not in merged


def test_should_auto_archive_completed_tasks_from_prior_weeks():
    from datetime import date

    from src.one_thing import archive_stale_completed_tasks, should_auto_archive, week_start

    today = date(2026, 6, 1)  # Monday
    last_week = date(2026, 5, 25)
    this_week = date(2026, 6, 2)

    old_done = OneThingTask(
        id="a",
        text="Old done",
        done=True,
        completed_at=last_week.isoformat(),
    )
    fresh_done = OneThingTask(
        id="b",
        text="Fresh done",
        done=True,
        completed_at=this_week.isoformat(),
    )
    open_task = OneThingTask(id="c", text="Open")

    assert week_start(today) == today
    assert should_auto_archive(old_done, today)
    assert not should_auto_archive(fresh_done, today)
    assert not should_auto_archive(open_task, today)


def test_archive_stale_completed_tasks_marks_old_done():
    from datetime import date
    from unittest.mock import patch

    from src.one_thing import OneThingTask, archive_stale_completed_tasks

    tasks = [
        OneThingTask(
            id="old",
            text="Ship it",
            done=True,
            completed_at="2026-05-20",
        ),
        OneThingTask(
            id="fresh",
            text="Still visible",
            done=True,
            completed_at="2026-06-01",
        ),
        OneThingTask(id="open", text="Active"),
    ]

    class FakeNote:
        items = "[]"

    def fake_load(_note):
        return tasks

    saved = {}

    def fake_save(db, note, next_tasks):
        saved["tasks"] = list(next_tasks)

    with patch("src.one_thing.get_or_create_board", return_value=FakeNote()), patch(
        "src.one_thing._load_tasks", fake_load
    ), patch("src.one_thing._save_tasks", fake_save):
        count = archive_stale_completed_tasks(object(), "tester", today=date(2026, 6, 1))

    assert count == 1
    by_id = {t.id: t for t in saved["tasks"]}
    assert by_id["old"].archived
    assert not by_id["fresh"].archived
    assert not by_id["open"].archived


def test_import_does_not_run_during_push_after_local_toggle():
    """Vault import must not run immediately after a local toggle — it would
    re-read stale `- [x]` lines and undo an uncheck before export."""
    from unittest.mock import patch

    calls = []

    def fake_import(*args, **kwargs):
        calls.append("import")
        return {}

    def fake_export(config, owner, tasks):
        calls.append("export")
        return {"synced": True, "task_count": len(tasks)}

    with patch("core.database.SessionLocal") as session_local, patch(
        "src.vault_one_thing_sync.resolve_vault_config", return_value=object()
    ), patch("src.vault_one_thing_sync.get_or_create_board", return_value=object()), patch(
        "src.vault_one_thing_sync.list_tasks", return_value=[]
    ), patch("src.vault_one_thing_sync.import_from_vault", fake_import), patch(
        "src.vault_one_thing_sync._export_tasks_to_vault", fake_export
    ):
        session_local.return_value = type("DB", (), {"close": lambda self: None})()
        from src.vault_one_thing_sync import push_one_thing_to_vault

        push_one_thing_to_vault("tester")

    assert calls == ["export"]


def test_import_merges_vault_edits_by_nobody_id():
    from dataclasses import dataclass
    from unittest.mock import patch

    task_id = "abc12345-0000-4000-8000-000000000001"
    stored = [
        OneThingTask(
            id=task_id,
            text="Old title",
            horizon="focus",
            priority="steady",
            due_date="2026-06-01",
        )
    ]

    class FakeNote:
        items = "[]"

    def fake_load(_note):
        return list(stored)

    def fake_save(db, note, tasks):
        stored.clear()
        stored.extend(tasks)

    line = format_task_line(
        OneThingTask(
            id=task_id,
            text="Updated in Obsidian",
            done=True,
            horizon="focus",
            priority="critical",
            due_date="2026-06-10",
        )
    )
    section = f"## Immediate Tasks\n<!-- nobody-horizon:focus -->\n\n{line}\n"

    with patch("src.one_thing.get_or_create_board", return_value=FakeNote()), patch(
        "src.one_thing._load_tasks", fake_load
    ), patch("src.one_thing._save_tasks", fake_save):
        changed = _import_section_tasks(object(), "tester", section, "focus")

    assert changed == 1
    assert len(stored) == 1
    task = stored[0]
    assert task.text == "Updated in Obsidian"
    assert task.done
    assert task.priority == "critical"
    assert task.due_date == "2026-06-10"


def test_refresh_board_skipped_when_two_way_disabled():
    from unittest.mock import patch

    with patch(
        "src.vault_one_thing_sync.is_todos_two_way_sync_enabled", return_value=False
    ), patch("src.vault_one_thing_sync.sync_one_thing_to_vault") as full_sync:
        from src.vault_one_thing_sync import refresh_board_from_vault

        out = refresh_board_from_vault("tester")
        full_sync.assert_not_called()
        assert out.get("skipped") is True


def test_import_from_vault_extracts_immediate_and_misc():
    import tempfile
    from dataclasses import dataclass
    from unittest.mock import patch

    with tempfile.TemporaryDirectory() as tmp:
        vault_root = Path(tmp) / "vault"
        daily_dir = vault_root / "Daily Notes"
        board_dir = vault_root / "Nobody"
        daily_dir.mkdir(parents=True)
        board_dir.mkdir(parents=True)

        daily_path = daily_dir / "2026-06-01.md"
        daily_path.write_text(
            "# 2026-06-01\n\n"
            "## Immediate Tasks\n"
            "<!-- nobody-horizon:focus -->\n\n"
            "- [ ] Ship todos panel\n"
            "- [x] Done already\n",
            encoding="utf-8",
        )
        board_path = board_dir / "Todos Board.md"
        board_path.write_text(
            "# Todos Board\n\n"
            "## Intermediate Goals\n"
            "<!-- nobody-horizon:build -->\n\n"
            "- [ ] Quarterly goal\n\n"
            "## Miscellaneous\n"
            "<!-- nobody-horizon:misc -->\n\n"
            "- [ ] Fix edge case\n",
            encoding="utf-8",
        )

        @dataclass
        class FakeConfig:
            vault_path: str
            daily_notes_folder: str = "Daily Notes"

        config = FakeConfig(vault_path=str(vault_root))

        class FakeNote:
            id = "board-note"
            items = "[]"
            owner = "tester"
            note_type = "one_thing"
            archived = False
            title = "Todos Board"
            content = ""
            label = "one-thing"
            pinned = True
            source = "system"

        stored_tasks = []

        def fake_get_or_create_board(db, owner):
            return FakeNote()

        def fake_load(note):
            return list(stored_tasks)

        def fake_save(db, note, tasks):
            stored_tasks.clear()
            stored_tasks.extend(tasks)

        patches = [
            patch("src.one_thing.get_or_create_board", fake_get_or_create_board),
            patch("src.one_thing._load_tasks", fake_load),
            patch("src.one_thing._save_tasks", fake_save),
            patch("src.vault_one_thing_sync._board_path", lambda _cfg, _owner: "Nobody/Todos Board.md"),
            patch(
                "src.vault_one_thing_sync.daily_vault_note_path",
                lambda _cfg, _date: "Daily Notes/2026-06-01.md",
            ),
            patch(
                "src.vault_one_thing_sync._read_note_body",
                lambda _cfg, rel: (daily_path if "Daily" in rel else board_path).read_text(encoding="utf-8"),
            ),
        ]
        for p in patches:
            p.start()
        try:
            stats = import_from_vault(object(), "tester", config)
        finally:
            for p in patches:
                p.stop()

        assert stats["focus_tasks_in_vault"] == 2
        assert stats["board_tasks_in_vault"] == 2
        assert stats["imported_from_vault"] == 4
        assert len(stored_tasks) == 4
        texts = {t.text for t in stored_tasks}
        assert "Ship todos panel" in texts
        assert "Done already" in texts
        assert "Quarterly goal" in texts
        assert "Fix edge case" in texts


def test_format_and_parse_parent_links_roundtrip():
    parent = OneThingTask(
        id="parent-0000-4000-8000-000000000001",
        text="Ship the thesis",
        horizon="build",
    )
    child = OneThingTask(
        id="child-0000-4000-8000-000000000002",
        text="Draft methods section",
        horizon="focus",
        parent_ids=[parent.id],
    )
    all_tasks = [parent, child]
    line = format_task_line(child, all_tasks=all_tasks)
    assert "[[Ship the thesis]]" in line
    assert "`parents:parent-0000-4000-8000-000000000001`" in line
    parsed = parse_task_line(line, default_horizon="focus", all_tasks=all_tasks)
    assert parsed is not None
    assert parsed.parent_ids == [parent.id]
    assert parsed.text == "Draft methods section"


def test_validate_parent_links_requires_focus_parent():
    from src.one_thing import validate_parent_links

    parent = OneThingTask(id="p1", text="Quarterly outcome", horizon="build")
    child = OneThingTask(id="c1", text="Today task", horizon="focus", parent_ids=[])
    try:
        validate_parent_links(child, [parent, child])
        assert False, "expected ValueError"
    except ValueError:
        pass

    child.parent_ids = [parent.id]
    validate_parent_links(child, [parent, child])
    assert child.parent_ids == [parent.id]


def test_validate_parent_links_build_requires_aim():
    from src.one_thing import validate_parent_links

    aim = OneThingTask(id="a1", text="Year direction", horizon="aim")
    build = OneThingTask(id="b1", text="Quarter goal", horizon="build", parent_ids=[])
    try:
        validate_parent_links(build, [aim, build])
        assert False, "expected ValueError"
    except ValueError:
        pass

    build.parent_ids = [aim.id]
    validate_parent_links(build, [aim, build])
