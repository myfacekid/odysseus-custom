"""Sync todos from Nobody to Obsidian vault markdown."""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Dict, List

from src.one_thing import (
    CHECKBOX_RE,
    DEFAULT_BOARD_PATH,
    HORIZONS,
    OneThingTask,
    TASK_ID_RE,
    add_task,
    archive_stale_completed_tasks,
    extract_horizon_section,
    format_horizon_section,
    get_or_create_board,
    get_task,
    list_tasks,
    merge_section,
    parse_task_line,
    tasks_from_section,
    update_task,
)
from src.obsidian_vault import VaultConfig, resolve_vault_config
from src.vault_write import (
    daily_vault_note_path,
)

logger = logging.getLogger(__name__)

DEFAULT_TODOS_TWO_WAY = True
VAULT_PUSH_DEBOUNCE_SEC = 0.45
_push_debounce_lock = threading.Lock()
_push_debounce_timers: Dict[str, threading.Timer] = {}


def is_todos_two_way_sync_enabled(owner: str) -> bool:
    """Whether Obsidian checkbox edits flow back into Nobody on board refresh."""
    from routes.prefs_routes import _load_for_user

    cfg = (_load_for_user(owner) or {}).get("obsidian_vault") or {}
    value = cfg.get("todos_two_way", DEFAULT_TODOS_TWO_WAY)
    if isinstance(value, str):
        return value.strip().lower() not in ("0", "false", "no", "off")
    return bool(value)


def _board_path(config: VaultConfig, owner: str) -> str:
    from routes.prefs_routes import _load_for_user

    cfg = (_load_for_user(owner) or {}).get("obsidian_vault") or {}
    return (cfg.get("one_thing_board_path") or DEFAULT_BOARD_PATH).strip()


def _write_note(config: VaultConfig, rel_path: str, content: str, owner: str = "") -> None:
    from src.vault_write import _resolve_write_path

    target, resolved, err = _resolve_write_path(config, rel_path)
    if err or not target or not resolved:
        raise RuntimeError(err or "invalid path")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    from src.vault_write import _after_write

    _after_write(config, resolved, owner=owner)


def _read_note_body(config: VaultConfig, rel_path: str) -> str:
    from src.obsidian_vault import _resolve_within_vault

    target, err = _resolve_within_vault(config, rel_path)
    if err or not target or not target.is_file():
        return ""
    try:
        return target.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def sync_focus_to_daily_note(
    config: VaultConfig,
    owner: str,
    tasks: List[OneThingTask],
) -> str:
    """Mirror immediate tasks into today's daily note."""
    daily_path = daily_vault_note_path(config, None)
    focus_tasks = [t for t in tasks if t.horizon == "focus"]
    section = format_horizon_section("focus", focus_tasks)

    existing = _read_note_body(config, daily_path)
    if not existing.strip():
        stem = Path(daily_path).stem
        merged = f"# {stem}\n\n{section}\n"
        _write_note(config, daily_path, merged, owner=owner)
        return daily_path

    merged = merge_section(existing, "focus", section)
    if not merged.startswith("#"):
        stem = Path(daily_path).stem
        merged = f"# {stem}\n\n{merged}"
    _write_note(config, daily_path, merged, owner=owner)
    return daily_path


def sync_board_file(
    config: VaultConfig,
    owner: str,
    tasks: List[OneThingTask],
) -> str:
    """Write the todos board (immediate + miscellaneous) to a vault note."""
    rel = _board_path(config, owner)
    if is_todos_two_way_sync_enabled(owner):
        hint = (
            "_Two-way sync: checkbox edits in Obsidian import when Todos opens. "
            "Lines with `nobody:` ids match existing tasks._"
        )
    else:
        hint = "_Synced from Nobody — edit tasks in the Todos panel for consistency._"
    parts = [
        "# Todos Board",
        "",
        hint,
        "",
    ]
    body = "\n\n".join(parts)
    for h in HORIZONS:
        section = format_horizon_section(h, tasks)
        body = merge_section(body, h, section)

    _write_note(config, rel, body.strip() + "\n", owner=owner)
    return rel


def _apply_vault_task_to_local(
    db,
    owner: str,
    current: OneThingTask,
    parsed: OneThingTask,
    *,
    full_merge: bool,
) -> bool:
    """Merge vault checkbox line into an existing Nobody task."""
    if full_merge:
        updates = {}
        if parsed.text.strip() and parsed.text.strip().lower() != current.text.strip().lower():
            updates["text"] = parsed.text.strip()
        if parsed.priority != current.priority:
            updates["priority"] = parsed.priority
        if (parsed.due_date or None) != (current.due_date or None):
            updates["due_date"] = parsed.due_date or ""
        if (parsed.parent_ids or []) != (current.parent_ids or []):
            updates["parent_ids"] = parsed.parent_ids or []
        if current.done != parsed.done:
            updates["done"] = parsed.done
        if not updates:
            return False
        update_task(db, owner, current.id, **updates)
        return True

    if current.done == parsed.done:
        return False
    update_task(db, owner, current.id, done=parsed.done)
    return True


def _import_section_tasks(
    db,
    owner: str,
    section_text: str,
    horizon: str,
) -> int:
    """Import `- [ ]` lines from a markdown section into the todos board."""
    if not section_text.strip():
        return 0

    existing = list_tasks(db, owner, horizon=horizon, include_done=True, include_archived=True)
    all_tasks = list_tasks(db, owner, include_done=True, include_archived=True)
    by_id = {t.id.lower(): t for t in existing}
    by_text = {t.text.strip().lower(): t for t in existing}
    changed = 0

    for line in section_text.splitlines():
        if not CHECKBOX_RE.match(line or ""):
            continue
        parsed = parse_task_line(
            line, default_horizon=horizon, all_tasks=all_tasks
        )
        if not parsed or not parsed.text.strip():
            continue

        line_has_id = bool(TASK_ID_RE.search(line or ""))
        tid_key = parsed.id.lower()
        text_key = parsed.text.strip().lower()

        if tid_key in by_id:
            current = by_id[tid_key]
            if _apply_vault_task_to_local(
                db, owner, current, parsed, full_merge=line_has_id
            ):
                changed += 1
                refreshed = get_task(db, owner, current.id)
                if refreshed:
                    by_text[refreshed.text.strip().lower()] = refreshed
                    all_tasks = list_tasks(
                        db, owner, include_done=True, include_archived=True
                    )
            continue

        if text_key in by_text:
            current = by_text[text_key]
            if _apply_vault_task_to_local(
                db, owner, current, parsed, full_merge=line_has_id
            ):
                changed += 1
                all_tasks = list_tasks(
                    db, owner, include_done=True, include_archived=True
                )
            continue

        new_task = add_task(
            db,
            owner,
            parsed.text,
            horizon=horizon,
            priority=parsed.priority,
            due_date=parsed.due_date,
            parent_ids=parsed.parent_ids,
            require_links=False,
        )
        if parsed.done:
            update_task(db, owner, new_task.id, done=True)
        changed += 1
        by_text[text_key] = new_task
        by_id[new_task.id.lower()] = new_task
        all_tasks = list_tasks(db, owner, include_done=True, include_archived=True)

    return changed


def import_from_vault(db, owner: str, config: VaultConfig) -> dict:
    """Pull checkbox tasks from the daily note and todos board."""
    daily_path = daily_vault_note_path(config, None)
    daily_body = _read_note_body(config, daily_path)
    focus_section = extract_horizon_section(daily_body, "focus")

    board_rel = _board_path(config, owner)
    board_body = _read_note_body(config, board_rel)

    focus_imported = _import_section_tasks(db, owner, focus_section, "focus")
    focus_board_section = extract_horizon_section(board_body, "focus")
    focus_imported += _import_section_tasks(db, owner, focus_board_section, "focus")

    board_imported = 0
    board_counts = {}
    for horizon in ("build", "aim", "misc"):
        section = extract_horizon_section(board_body, horizon)
        board_counts[horizon] = len(tasks_from_section(section, horizon))
        board_imported += _import_section_tasks(db, owner, section, horizon)

    return {
        "daily_note_path": daily_path,
        "board_path": board_rel,
        "focus_imported": focus_imported,
        "board_imported": board_imported,
        "imported_from_vault": focus_imported + board_imported,
        "focus_tasks_in_vault": len(tasks_from_section(focus_section, "focus")),
        "board_tasks_in_vault": sum(board_counts.values()),
    }


def _export_tasks_to_vault(
    config: VaultConfig,
    owner: str,
    tasks: List[OneThingTask],
) -> dict:
    board_path = sync_board_file(config, owner, tasks)
    daily_path = sync_focus_to_daily_note(config, owner, tasks)
    return {
        "synced": True,
        "board_path": board_path,
        "daily_note_path": daily_path,
        "task_count": len(tasks),
    }


def push_one_thing_to_vault(owner: str) -> dict:
    """Push local todos to Obsidian without importing vault state first.

    Use after local edits (toggle, add, update) so vault checkbox lines cannot
    clobber in-flight changes before they are written out.
    """
    from core.database import SessionLocal

    config = resolve_vault_config(owner)
    if not config:
        return {
            "synced": False,
            "error": "Obsidian vault not configured",
        }

    db = SessionLocal()
    try:
        get_or_create_board(db, owner)
        tasks = list_tasks(db, owner, include_done=True)
    finally:
        db.close()

    try:
        return _export_tasks_to_vault(config, owner, tasks)
    except Exception as e:
        logger.warning(f"Todos vault push failed: {e}")
        return {"synced": False, "error": str(e)}


def refresh_board_from_vault(owner: str) -> dict:
    """Import Obsidian checkbox edits, then push merged state back to the vault.

    Called when the Todos panel opens (two-way mode). Local mutations still
    use push-only via sync_after_task_change to avoid clobbering in-flight toggles.
    """
    if not is_todos_two_way_sync_enabled(owner):
        return {"two_way": False, "skipped": True}

    return sync_one_thing_to_vault(owner)


def sync_one_thing_to_vault(owner: str) -> dict:
    """Pull vault checkboxes, then push all todos to Obsidian."""
    from core.database import SessionLocal

    config = resolve_vault_config(owner)
    if not config:
        return {
            "synced": False,
            "error": "Obsidian vault not configured",
        }

    db = SessionLocal()
    try:
        get_or_create_board(db, owner)
        import_stats = import_from_vault(db, owner, config)
        archive_stale_completed_tasks(db, owner)
        tasks = list_tasks(db, owner, include_done=True)
    finally:
        db.close()

    try:
        out = _export_tasks_to_vault(config, owner, tasks)
        out.update(import_stats)
        out["two_way"] = is_todos_two_way_sync_enabled(owner)
        return out
    except Exception as e:
        logger.warning(f"Todos vault sync failed: {e}")
        return {"synced": False, "error": str(e)}


def sync_after_task_change(owner: str) -> None:
    """Debounced background vault push after local mutations; returns immediately."""
    if not owner:
        return

    def _do_push() -> None:
        try:
            push_one_thing_to_vault(owner)
        except Exception as e:
            logger.debug(f"Todos push skipped: {e}")
        finally:
            with _push_debounce_lock:
                _push_debounce_timers.pop(owner, None)

    with _push_debounce_lock:
        existing = _push_debounce_timers.get(owner)
        if existing:
            existing.cancel()
        timer = threading.Timer(VAULT_PUSH_DEBOUNCE_SEC, _do_push)
        timer.daemon = True
        _push_debounce_timers[owner] = timer
        timer.start()
