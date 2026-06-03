"""Todos board — immediate tasks, miscellaneous items, and Obsidian vault sync.

Horizons:
  focus — Immediate Tasks (mirrored to today's daily note)
  build — Intermediate Goals (~3 months)
  aim   — Long Horizon (~1 year)
  misc  — Miscellaneous tasks

Nobody holds the source of truth (one pinned ``one_thing`` note per user).
Vault markdown mirrors tasks for Obsidian ``- [ ]`` checkbox compatibility.
"""
from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

HORIZONS = ("focus", "build", "aim", "misc")
PRIORITIES = ("critical", "elevated", "steady")

HORIZON_LABELS = {
    "focus": "Immediate Tasks",
    "build": "Intermediate Goals",
    "aim": "Long Horizon",
    "misc": "Miscellaneous",
}

HORIZON_TAGLINES = {
    "focus": "Concrete commitments — synced to today's Obsidian daily note.",
    "build": "Shorter-term outcomes you are building toward.",
    "aim": "Directional goals for the year ahead.",
    "misc": "Tasks that do not fit the other categories.",
}

LEGACY_HORIZON_HEADERS = {
    "focus": ("One Thing — This Week",),
    "build": ("Intermediate Goals — Next 3 Months",),
    "aim": ("Long Horizon — This Year",),
    "misc": (),
}

PRIORITY_LABELS = {
    "critical": "Critical",
    "elevated": "Elevated",
    "steady": "Steady",
}

# Obsidian Tasks emoji mapping
PRIORITY_MARKERS = {
    "critical": "⏫",
    "elevated": "🔼",
    "steady": "",
}

HORIZON_MARKER = "<!-- nobody-horizon:{horizon} -->"
TASK_ID_RE = re.compile(r"`nobody:([a-f0-9-]{8,36})`", re.I)
CHECKBOX_RE = re.compile(r"^\s*-\s*\[([ xX])\]\s*(.+)$")

DEFAULT_BOARD_PATH = "Nobody/Todos Board.md"
BOARD_NOTE_TITLE = "Todos Board"
BOARD_NOTE_LABEL = "one-thing"


@dataclass
class OneThingTask:
    id: str
    text: str
    done: bool = False
    horizon: str = "focus"
    priority: str = "steady"
    due_date: Optional[str] = None  # YYYY-MM-DD
    completed_at: Optional[str] = None  # YYYY-MM-DD — set when marked done
    archived: bool = False

    def to_item(self) -> dict:
        out = {
            "id": self.id,
            "text": self.text,
            "done": self.done,
            "horizon": self.horizon,
            "priority": self.priority,
            "archived": self.archived,
        }
        if self.due_date:
            out["due_date"] = self.due_date
        if self.completed_at:
            out["completed_at"] = self.completed_at
        return out

    @classmethod
    def from_item(cls, raw: dict) -> Optional["OneThingTask"]:
        if not isinstance(raw, dict):
            return None
        text = (raw.get("text") or "").strip()
        if not text:
            return None
        tid = (raw.get("id") or str(uuid.uuid4())).strip()
        horizon = normalize_horizon(raw.get("horizon") or "focus")
        priority = (raw.get("priority") or "steady").lower()
        if priority not in PRIORITIES:
            priority = "steady"
        due = _normalize_date(raw.get("due_date"))
        completed = _normalize_date(raw.get("completed_at"))
        return cls(
            id=tid,
            text=text,
            done=bool(raw.get("done") or raw.get("checked")),
            horizon=horizon,
            priority=priority,
            due_date=due,
            completed_at=completed,
            archived=bool(raw.get("archived")),
        )


def _normalize_date(value: Any) -> Optional[str]:
    if not value:
        return None
    s = str(value).strip()[:10]
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return s
    except ValueError:
        return None


def normalize_horizon(value: Any) -> str:
    if not value:
        return "focus"
    key = str(value).strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "one_thing": "focus",
        "one": "focus",
        "week": "focus",
        "this_week": "focus",
        "immediate": "focus",
        "immediate_tasks": "focus",
        "intermediate": "build",
        "three_months": "build",
        "3_months": "build",
        "quarter": "build",
        "long": "aim",
        "year": "aim",
        "long_horizon": "aim",
        "this_year": "aim",
        "build": "build",
        "aim": "aim",
        "miscellaneous": "misc",
        "misc": "misc",
    }
    key = aliases.get(key, key)
    return key if key in HORIZONS else "focus"


def week_start(d: date) -> date:
    """Monday-start week containing ``d``."""
    return d - timedelta(days=d.weekday())


def task_archive_reference(task: OneThingTask) -> Optional[date]:
    """Date used to decide when a completed task leaves the active board."""
    if not task.done:
        return None
    if task.completed_at:
        try:
            return date.fromisoformat(task.completed_at)
        except ValueError:
            pass
    if task.due_date:
        try:
            return date.fromisoformat(task.due_date)
        except ValueError:
            pass
    return None


def should_auto_archive(task: OneThingTask, today: Optional[date] = None) -> bool:
    """Archive completed tasks from weeks before the current one."""
    if not task.done or task.archived:
        return False
    ref = task_archive_reference(task)
    if ref is None:
        return False
    today = today or date.today()
    return week_start(ref) < week_start(today)


def _apply_done_transition(task: OneThingTask, done: bool, today: Optional[date] = None) -> None:
    today = today or date.today()
    task.done = bool(done)
    if task.done:
        if not task.completed_at:
            task.completed_at = today.isoformat()
    else:
        task.completed_at = None
        task.archived = False


def _backfill_missing_completion_dates(tasks: List[OneThingTask], today: Optional[date] = None) -> bool:
    """Legacy done tasks with no anchor date — stamp today so they age out next week."""
    today = today or date.today()
    changed = False
    for task in tasks:
        if task.done and not task.archived and not task.completed_at and not task.due_date:
            task.completed_at = today.isoformat()
            changed = True
    return changed


def archive_stale_completed_tasks(
    db,
    owner: str,
    *,
    today: Optional[date] = None,
) -> int:
    """Move completed tasks from prior weeks off the active board."""
    today = today or date.today()
    note = get_or_create_board(db, owner)
    tasks = _load_tasks(note)
    changed = _backfill_missing_completion_dates(tasks, today)
    archived = 0
    for task in tasks:
        if should_auto_archive(task, today):
            task.archived = True
            archived += 1
            changed = True
    if changed:
        _save_tasks(db, note, tasks)
    return archived


def normalize_priority(value: Any) -> str:
    if not value:
        return "steady"
    key = str(value).strip().lower()
    aliases = {
        "high": "critical",
        "urgent": "critical",
        "medium": "elevated",
        "normal": "elevated",
        "low": "steady",
    }
    key = aliases.get(key, key)
    return key if key in PRIORITIES else "steady"


def get_or_create_board(db, owner: str):
    """Return the pinned One Thing board note, creating it if needed."""
    from core.database import Note

    q = db.query(Note).filter(
        Note.owner == owner,
        Note.note_type == "one_thing",
        Note.archived == False,  # noqa: E712
    )
    note = q.order_by(Note.updated_at.desc()).first()
    if note:
        return note

    note = Note(
        id=str(uuid.uuid4()),
        owner=owner,
        title=BOARD_NOTE_TITLE,
        content=(
            "Todos board — checkbox tasks synced with Obsidian.\n\n"
            "• **Immediate Tasks** — synced to today's daily note\n"
            "• **Intermediate Goals** — ~3 month outcomes\n"
            "• **Long Horizon** — yearly direction\n"
            "• **Miscellaneous** — everything else\n"
        ),
        items=json.dumps([]),
        note_type="one_thing",
        label=BOARD_NOTE_LABEL,
        pinned=True,
        source="system",
    )
    db.add(note)
    db.commit()
    db.refresh(note)
    return note


def _load_tasks(note) -> List[OneThingTask]:
    if not note or not note.items:
        return []
    try:
        raw = json.loads(note.items)
    except (json.JSONDecodeError, TypeError):
        return []
    tasks = []
    for item in raw or []:
        t = OneThingTask.from_item(item)
        if t:
            tasks.append(t)
    return tasks


def _save_tasks(db, note, tasks: List[OneThingTask]) -> None:
    from sqlalchemy.orm.attributes import flag_modified

    note.items = json.dumps([t.to_item() for t in tasks])
    flag_modified(note, "items")
    db.commit()
    db.refresh(note)


def list_tasks(
    db,
    owner: str,
    *,
    horizon: Optional[str] = None,
    include_done: bool = False,
    include_archived: bool = False,
) -> List[OneThingTask]:
    note = get_or_create_board(db, owner)
    tasks = _load_tasks(note)
    hz = normalize_horizon(horizon) if horizon else None
    out = []
    for t in tasks:
        if hz and t.horizon != hz:
            continue
        if t.archived and not include_archived:
            continue
        if not include_done and t.done:
            continue
        out.append(t)
    return out


def get_task(db, owner: str, task_id: str) -> Optional[OneThingTask]:
    prefix = (task_id or "").strip().lower()
    if not prefix:
        return None
    for t in _load_tasks(get_or_create_board(db, owner)):
        if t.id.lower().startswith(prefix):
            return t
    return None


def add_task(
    db,
    owner: str,
    text: str,
    *,
    horizon: str = "focus",
    priority: str = "steady",
    due_date: Optional[str] = None,
) -> OneThingTask:
    note = get_or_create_board(db, owner)
    tasks = _load_tasks(note)
    task = OneThingTask(
        id=str(uuid.uuid4()),
        text=(text or "").strip(),
        horizon=normalize_horizon(horizon),
        priority=normalize_priority(priority),
        due_date=_normalize_date(due_date),
    )
    if not task.text:
        raise ValueError("Task text is required")
    tasks.append(task)
    _save_tasks(db, note, tasks)
    return task


def update_task(
    db,
    owner: str,
    task_id: str,
    *,
    text: Optional[str] = None,
    horizon: Optional[str] = None,
    priority: Optional[str] = None,
    due_date: Optional[str] = None,
    done: Optional[bool] = None,
) -> Optional[OneThingTask]:
    note = get_or_create_board(db, owner)
    tasks = _load_tasks(note)
    updated = None
    for i, t in enumerate(tasks):
        if not t.id.lower().startswith((task_id or "").strip().lower()):
            continue
        if text is not None:
            t.text = text.strip() or t.text
        if horizon is not None:
            t.horizon = normalize_horizon(horizon)
        if priority is not None:
            t.priority = normalize_priority(priority)
        if due_date is not None:
            t.due_date = _normalize_date(due_date)
        if done is not None:
            _apply_done_transition(t, done)
        tasks[i] = t
        updated = t
        break
    if not updated:
        return None
    _save_tasks(db, note, tasks)
    return updated


def toggle_task(db, owner: str, task_id: str) -> Optional[OneThingTask]:
    task = get_task(db, owner, task_id)
    if not task:
        return None
    return update_task(db, owner, task.id, done=not task.done)


def delete_task(db, owner: str, task_id: str) -> bool:
    note = get_or_create_board(db, owner)
    tasks = _load_tasks(note)
    prefix = (task_id or "").strip().lower()
    new_tasks = [t for t in tasks if not t.id.lower().startswith(prefix)]
    if len(new_tasks) == len(tasks):
        return False
    _save_tasks(db, note, new_tasks)
    return True


def board_to_dict(
    db,
    owner: str,
    *,
    include_done: bool = True,
    include_archived: bool = False,
) -> dict:
    note = get_or_create_board(db, owner)
    tasks = _load_tasks(note)
    grouped = {h: [] for h in HORIZONS}
    for t in tasks:
        if t.archived and not include_archived:
            continue
        if not include_done and t.done:
            continue
        grouped.setdefault(t.horizon, []).append(t.to_item())
    return {
        "note_id": note.id,
        "title": note.title,
        "horizons": {
            h: {
                "key": h,
                "label": HORIZON_LABELS[h],
                "tagline": HORIZON_TAGLINES[h],
                "tasks": grouped.get(h, []),
            }
            for h in HORIZONS
        },
    }


def get_daily_summary(db, owner: str) -> dict:
    from src.vault_write import daily_vault_note_path
    from src.obsidian_vault import resolve_vault_config

    config = resolve_vault_config(owner)
    daily_path = daily_vault_note_path(config, None) if config else None
    focus = list_tasks(db, owner, horizon="focus", include_done=False)
    return {
        "daily_note_path": daily_path,
        "date": date.today().isoformat(),
        "focus_tasks": [t.to_item() for t in focus],
        "open_count": len(focus),
    }


def format_task_line(task: OneThingTask) -> str:
    """Markdown checkbox line for Obsidian (Tasks-plugin friendly)."""
    mark = "x" if task.done else " "
    parts = [task.text.strip()]
    if task.due_date:
        parts.append(f"📅 {task.due_date}")
    emoji = PRIORITY_MARKERS.get(task.priority, "")
    if emoji:
        parts.append(emoji)
    body = " ".join(parts)
    return f"- [{mark}] {body} · `nobody:{task.id}`"


def parse_task_line(line: str, default_horizon: str = "focus") -> Optional[OneThingTask]:
    m = CHECKBOX_RE.match(line or "")
    if not m:
        return None
    done = m.group(1).lower() == "x"
    rest = m.group(2).strip()
    tid = None
    id_m = TASK_ID_RE.search(rest)
    if id_m:
        tid = id_m.group(1)
        rest = TASK_ID_RE.sub("", rest).strip().strip("·").strip()

    due = None
    due_m = re.search(r"📅\s*(\d{4}-\d{2}-\d{2})", rest)
    if due_m:
        due = due_m.group(1)
        rest = rest.replace(due_m.group(0), "").strip()

    priority = "steady"
    for p, emoji in PRIORITY_MARKERS.items():
        if emoji and emoji in rest:
            priority = p
            rest = rest.replace(emoji, "").strip()

    text = rest.strip().strip("·").strip()
    if not text:
        return None
    return OneThingTask(
        id=tid or str(uuid.uuid4()),
        text=text,
        done=done,
        horizon=normalize_horizon(default_horizon),
        priority=priority,
        due_date=due,
    )


def format_horizon_section(horizon: str, tasks: List[OneThingTask]) -> str:
    lines = [
        f"## {HORIZON_LABELS[horizon]}",
        HORIZON_MARKER.format(horizon=horizon),
        "",
    ]
    hz_tasks = [t for t in tasks if t.horizon == horizon]
    lines.extend(format_task_line(t) for t in hz_tasks)
    return "\n".join(lines)


def _horizon_header_candidates(horizon: str) -> Tuple[str, ...]:
    return (HORIZON_LABELS[horizon],) + LEGACY_HORIZON_HEADERS.get(horizon, ())


def extract_horizon_section(content: str, horizon: str) -> str:
    """Return markdown body for a horizon section (checkbox lines only)."""
    if horizon not in HORIZONS:
        return ""
    marker = HORIZON_MARKER.format(horizon=horizon)
    for header in _horizon_header_candidates(horizon):
        for with_marker in (True, False):
            if with_marker:
                pattern = re.compile(
                    rf"## {re.escape(header)}\s*\n{re.escape(marker)}\s*\n([\s\S]*?)(?=\n## |\Z)",
                    re.MULTILINE,
                )
            else:
                pattern = re.compile(
                    rf"## {re.escape(header)}\s*\n([\s\S]*?)(?=\n## |\Z)",
                    re.MULTILINE,
                )
            m = pattern.search(content or "")
            if m:
                return m.group(1).strip()
    return ""


def merge_section(content: str, horizon: str, section_body: str) -> str:
    """Replace or append a horizon section in markdown content."""
    header = f"## {HORIZON_LABELS[horizon]}"
    marker = HORIZON_MARKER.format(horizon=horizon)
    block = section_body.strip() + "\n"
    for candidate in _horizon_header_candidates(horizon):
        for with_marker in (True, False):
            if with_marker:
                pattern = re.compile(
                    rf"## {re.escape(candidate)}\s*\n{re.escape(marker)}\s*\n[\s\S]*?(?=\n## |\Z)",
                    re.MULTILINE,
                )
            else:
                pattern = re.compile(
                    rf"## {re.escape(candidate)}\s*\n[\s\S]*?(?=\n## |\Z)",
                    re.MULTILINE,
                )
            if pattern.search(content):
                return pattern.sub(block.rstrip() + "\n", content, count=1)
    sep = "\n\n" if content.strip() else ""
    return content.rstrip() + sep + block


def tasks_from_section(text: str, horizon: str) -> List[OneThingTask]:
    out = []
    for line in (text or "").splitlines():
        t = parse_task_line(line, default_horizon=horizon)
        if t:
            out.append(t)
    return out


def format_tasks_markdown(tasks: List[OneThingTask], *, horizon: Optional[str] = None) -> str:
    lines = []
    horizons = [horizon] if horizon else list(HORIZONS)
    for h in horizons:
        if h not in HORIZONS:
            continue
        lines.append(format_horizon_section(h, tasks))
        lines.append("")
    return "\n".join(lines).strip()


def format_agent_list(tasks: List[OneThingTask]) -> str:
    if not tasks:
        return "No todos found."
    lines = ["TODOS", "=" * 40]
    by_hz: Dict[str, List[OneThingTask]] = {h: [] for h in HORIZONS}
    for t in tasks:
        by_hz.setdefault(t.horizon, []).append(t)
    for h in HORIZONS:
        bucket = by_hz.get(h) or []
        if not bucket:
            continue
        lines.append(f"\n{HORIZON_LABELS[h]}")
        for t in bucket:
            mark = "x" if t.done else " "
            pri = PRIORITY_LABELS[t.priority]
            due = f" due {t.due_date}" if t.due_date else ""
            lines.append(f"  [{mark}] `{t.id[:8]}` {t.text} ({pri}{due})")
    return "\n".join(lines)
