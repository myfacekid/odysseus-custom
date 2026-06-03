"""One Thing task board API — horizons, priorities, Obsidian sync."""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from core.database import SessionLocal
from src.auth_helpers import get_current_user
from src.one_thing import (
    HORIZONS,
    PRIORITIES,
    add_task,
    archive_stale_completed_tasks,
    board_to_dict,
    delete_task,
    get_daily_summary,
    get_task,
    list_tasks,
    toggle_task,
    update_task,
)
from src.vault_one_thing_sync import sync_one_thing_to_vault, sync_after_task_change

logger = logging.getLogger(__name__)


class TaskCreate(BaseModel):
    text: str = Field(..., min_length=1, max_length=500)
    horizon: str = "focus"
    priority: str = "steady"
    due_date: Optional[str] = None


class TaskUpdate(BaseModel):
    text: Optional[str] = None
    horizon: Optional[str] = None
    priority: Optional[str] = None
    due_date: Optional[str] = None
    done: Optional[bool] = None


def setup_one_thing_routes() -> APIRouter:
    router = APIRouter(prefix="/api/one-thing", tags=["one-thing"])

    def _owner(request: Request) -> str:
        user = get_current_user(request)
        if not user:
            raise HTTPException(401, "Not authenticated")
        return user

    @router.get("")
    def get_board(request: Request, include_done: bool = True):
        owner = _owner(request)
        db = SessionLocal()
        try:
            archived = archive_stale_completed_tasks(db, owner)
            board = board_to_dict(db, owner, include_done=include_done)
            if archived:
                board["archived_stale"] = archived
            return board
        finally:
            db.close()

    @router.get("/daily")
    def get_daily(request: Request):
        owner = _owner(request)
        db = SessionLocal()
        try:
            summary = get_daily_summary(db, owner)
            sync = sync_one_thing_to_vault(owner)
            summary["vault_sync"] = sync
            return summary
        finally:
            db.close()

    @router.get("/meta")
    def get_meta():
        from src.one_thing import HORIZON_LABELS, HORIZON_TAGLINES, PRIORITY_LABELS

        return {
            "horizons": [
                {
                    "key": h,
                    "label": HORIZON_LABELS[h],
                    "tagline": HORIZON_TAGLINES[h],
                }
                for h in HORIZONS
            ],
            "priorities": [
                {"key": p, "label": PRIORITY_LABELS[p]} for p in PRIORITIES
            ],
        }

    @router.post("/tasks")
    def create_task(body: TaskCreate, request: Request):
        owner = _owner(request)
        db = SessionLocal()
        try:
            task = add_task(
                db,
                owner,
                body.text,
                horizon=body.horizon,
                priority=body.priority,
                due_date=body.due_date,
            )
            sync_after_task_change(owner)
            return {"ok": True, "task": task.to_item()}
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        finally:
            db.close()

    @router.put("/tasks/{task_id}")
    def patch_task(task_id: str, body: TaskUpdate, request: Request):
        owner = _owner(request)
        db = SessionLocal()
        try:
            task = update_task(
                db,
                owner,
                task_id,
                text=body.text,
                horizon=body.horizon,
                priority=body.priority,
                due_date=body.due_date,
                done=body.done,
            )
            if not task:
                raise HTTPException(404, "Task not found")
            sync_after_task_change(owner)
            return {"ok": True, "task": task.to_item()}
        finally:
            db.close()

    @router.post("/tasks/{task_id}/toggle")
    def toggle_task_route(task_id: str, request: Request):
        owner = _owner(request)
        db = SessionLocal()
        try:
            task = toggle_task(db, owner, task_id)
            if not task:
                raise HTTPException(404, "Task not found")
            archive_stale_completed_tasks(db, owner)
            task = get_task(db, owner, task_id) or task
        finally:
            db.close()
        sync_after_task_change(owner)
        return {"ok": True, "task": task.to_item()}

    @router.delete("/tasks/{task_id}")
    def remove_task(task_id: str, request: Request):
        owner = _owner(request)
        db = SessionLocal()
        try:
            if not delete_task(db, owner, task_id):
                raise HTTPException(404, "Task not found")
            sync_after_task_change(owner)
            return {"ok": True}
        finally:
            db.close()

    @router.post("/sync")
    def force_sync(request: Request):
        owner = _owner(request)
        result = sync_one_thing_to_vault(owner)
        if not result.get("synced"):
            raise HTTPException(400, result.get("error") or "Sync failed")
        return result

    return router
