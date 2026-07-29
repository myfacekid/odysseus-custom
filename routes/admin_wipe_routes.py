"""Admin Danger Zone — per-category wipes.

Each endpoint is admin-only and truncates exactly one domain so the
user can selectively reset memory / skills / notes / etc. without
nuking everything. The catch-all `chats` endpoint mirrors the
existing /api/sessions/all so the Danger Zone speaks one URL pattern.

URL shape: DELETE /api/admin/wipe/{kind}
Kinds: chats, memory, skills, notes, todos, tasks, documents, gallery, calendar, links.
"""

import json
import logging
import os
import shutil
from pathlib import Path
from fastapi import APIRouter, HTTPException, Request

from core.middleware import require_admin
from core.database import (
    SessionLocal,
    Session as DbSession,
    ChatMessage as DbChatMessage,
    Memory,
    Note,
    ScheduledTask,
    TaskRun,
    Document,
    DocumentVersion,
    GalleryImage,
    GalleryAlbum,
    CalendarEvent,
    CalendarCal,
)
from src.constants import DATA_DIR

logger = logging.getLogger(__name__)


def _wipe_memory_files():
    """Blank memory.json + drop the per-owner tidy-state sidecar so the
    next audit doesn't try to diff against gone memories."""
    for name in ("memory.json", "memory_tidy_state.json"):
        p = os.path.join(DATA_DIR, name)
        if not os.path.exists(p):
            continue
        try:
            if name == "memory.json":
                with open(p, "w", encoding="utf-8") as f:
                    json.dump([], f)
            else:
                os.remove(p)
        except OSError as e:
            logger.warning(f"Could not reset {name}: {e}")


def _rmtree_quiet(path: str):
    """rmtree that doesn't crash if the path doesn't exist."""
    if os.path.isdir(path):
        try:
            shutil.rmtree(path)
        except OSError as e:
            logger.warning(f"Could not remove {path}: {e}")


def _count_jsonl_rows(path: Path) -> int:
    if not path.is_file():
        return 0
    try:
        return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
    except OSError:
        return 0


def _count_one_thing_tasks(items_json) -> int:
    """Count task rows stored on a Todos (one_thing) board note."""
    if not items_json:
        return 0
    try:
        raw = json.loads(items_json)
    except (json.JSONDecodeError, TypeError):
        return 0
    return len(raw) if isinstance(raw, list) else 0


def _wipe_all_links() -> int:
    """Clear confirmed + pending + rejected graph links for every owner.

    Nodes stay on disk. Confirmed edges live in ``manual_edges.jsonl``;
    ``edges.jsonl`` is rewritten to inferred-only via ``_sync_edges_from_manual``.
    """
    from src.knowledge_graph import KNOWLEDGE_ROOT, _sync_edges_from_manual, save_manual_edges

    users_root = Path(KNOWLEDGE_ROOT) / "users"
    if not users_root.is_dir():
        return 0

    count = 0
    link_files = ("manual_edges.jsonl", "pending_edges.jsonl", "rejected_edge_keys.jsonl")
    for owner_dir in users_root.iterdir():
        if not owner_dir.is_dir():
            continue
        owner = owner_dir.name
        for name in link_files:
            count += _count_jsonl_rows(owner_dir / name)
        try:
            save_manual_edges(owner, [])
        except Exception as e:
            logger.warning(f"Could not clear manual edges for {owner}: {e}")
            # Fall back to deleting the file so a partial wipe still lands.
            try:
                (owner_dir / "manual_edges.jsonl").unlink(missing_ok=True)
            except OSError:
                pass
        for name in ("pending_edges.jsonl", "rejected_edge_keys.jsonl"):
            p = owner_dir / name
            try:
                if p.is_file():
                    p.unlink()
            except OSError as e:
                logger.warning(f"Could not remove {p}: {e}")
        try:
            _sync_edges_from_manual(owner)
        except Exception as e:
            logger.warning(f"Could not sync edges after link wipe for {owner}: {e}")
    return count


def setup_admin_wipe_routes(session_manager):
    """The session_manager is passed in so we can also clear its
    in-memory cache when wiping chats — without it the DB is empty
    but the next /api/sessions returns stale entries."""
    router = APIRouter(prefix="/api/admin")

    @router.delete("/wipe/{kind}")
    def wipe(kind: str, request: Request):
        require_admin(request)
        kind = (kind or "").strip().lower()

        db = SessionLocal()
        try:
            if kind == "chats":
                count = db.query(DbSession).count()
                db.query(DbChatMessage).delete()
                db.query(DbSession).delete()
                db.commit()
                try:
                    session_manager.sessions.clear()
                except Exception:
                    pass
                return {"status": "deleted", "kind": kind, "count": count}

            if kind == "memory":
                count = db.query(Memory).count()
                db.query(Memory).delete()
                db.commit()
                _wipe_memory_files()
                # Drop the vector store too so semantic search doesn't
                # return ghosts. Lazy import — chromadb may not be
                # initialised in every deployment.
                try:
                    from src.memory_vector import get_memory_vector_store
                    mv = get_memory_vector_store()
                    if mv and hasattr(mv, "clear"):
                        mv.clear()
                except Exception as e:
                    logger.info(f"Memory vector clear skipped: {e}")
                return {"status": "deleted", "kind": kind, "count": count}

            if kind == "skills":
                # Skills live as SKILL.md files under data/skills/. Drop
                # the entire directory; the SkillsManager re-creates the
                # tree on next write.
                skills_dir = os.path.join(DATA_DIR, "skills")
                count = 0
                if os.path.isdir(skills_dir):
                    # Count SKILL.md files for the response — quick walk.
                    for _, _, files in os.walk(skills_dir):
                        count += sum(1 for f in files if f == "SKILL.md")
                    _rmtree_quiet(skills_dir)
                # Legacy fallback file
                legacy = os.path.join(DATA_DIR, "skills.json")
                if os.path.exists(legacy):
                    try:
                        os.remove(legacy)
                    except OSError:
                        pass
                return {"status": "deleted", "kind": kind, "count": count}

            if kind == "notes":
                # Todos live as note_type=one_thing boards — wiped separately.
                q = db.query(Note).filter(Note.note_type != "one_thing")
                count = q.count()
                q.delete(synchronize_session=False)
                db.commit()
                return {"status": "deleted", "kind": kind, "count": count}

            if kind == "todos":
                boards = db.query(Note).filter(Note.note_type == "one_thing").all()
                count = sum(_count_one_thing_tasks(b.items) for b in boards)
                db.query(Note).filter(Note.note_type == "one_thing").delete(
                    synchronize_session=False
                )
                db.commit()
                return {"status": "deleted", "kind": kind, "count": count}

            if kind == "tasks":
                # TaskRun rows reference tasks via FK — clear them first.
                db.query(TaskRun).delete()
                count = db.query(ScheduledTask).count()
                db.query(ScheduledTask).delete()
                db.commit()
                return {"status": "deleted", "kind": kind, "count": count}

            if kind == "documents":
                # DocumentVersion FKs Document — clear children first.
                db.query(DocumentVersion).delete()
                count = db.query(Document).count()
                db.query(Document).delete()
                db.commit()
                return {"status": "deleted", "kind": kind, "count": count}

            if kind == "gallery":
                count = db.query(GalleryImage).count() + db.query(GalleryAlbum).count()
                db.query(GalleryImage).delete()
                db.query(GalleryAlbum).delete()
                db.commit()
                # Also drop the upload dir so disk doesn't keep orphans.
                _rmtree_quiet(os.path.join(DATA_DIR, "gallery"))
                _rmtree_quiet(os.path.join(DATA_DIR, "gallery_uploads"))
                return {"status": "deleted", "kind": kind, "count": count}

            if kind == "calendar":
                # Events FK calendars — clear children first, then both.
                db.query(CalendarEvent).delete()
                count = db.query(CalendarCal).count()
                db.query(CalendarCal).delete()
                db.commit()
                return {"status": "deleted", "kind": kind, "count": count}

            if kind == "links":
                # Graph links live on disk under data/knowledge/users/*/ —
                # no SQLite tables involved.
                count = _wipe_all_links()
                return {"status": "deleted", "kind": kind, "count": count}

            raise HTTPException(400, f"Unknown wipe kind: {kind!r}")
        except HTTPException:
            raise
        except Exception as e:
            db.rollback()
            logger.exception(f"Wipe {kind} failed")
            raise HTTPException(500, f"Wipe {kind} failed: {e}")
        finally:
            db.close()

    return router
