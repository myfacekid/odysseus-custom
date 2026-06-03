"""One Thing task board API — horizons, priorities, knowledge graph index."""

import logging
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from core.database import SessionLocal
from src.auth_helpers import get_current_user
from src.knowledge_sync import after_task_change, force_rebuild
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

logger = logging.getLogger(__name__)


class TaskCreate(BaseModel):
    text: str = Field(..., min_length=1, max_length=500)
    horizon: str = "focus"
    priority: str = "steady"
    due_date: Optional[str] = None
    parent_ids: List[str] = Field(default_factory=list)


class TaskUpdate(BaseModel):
    text: Optional[str] = None
    horizon: Optional[str] = None
    priority: Optional[str] = None
    due_date: Optional[str] = None
    done: Optional[bool] = None
    parent_ids: Optional[List[str]] = None


def setup_one_thing_routes() -> APIRouter:
    router = APIRouter(prefix="/api/one-thing", tags=["one-thing"])

    def _owner(request: Request) -> str:
        user = get_current_user(request)
        if not user:
            raise HTTPException(401, "Not authenticated")
        return user

    @router.get("")
    def get_board(
        request: Request,
        include_done: bool = True,
        include_archived: bool = False,
        skip_vault_sync: bool = True,
    ):
        owner = _owner(request)
        db = SessionLocal()
        try:
            archived = archive_stale_completed_tasks(db, owner)
            board = board_to_dict(
                db,
                owner,
                include_done=include_done,
                include_archived=include_archived,
            )
            if not include_archived:
                board["archived_count"] = len(
                    list_tasks(db, owner, include_done=True, include_archived=True)
                )
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
            return get_daily_summary(db, owner)
        finally:
            db.close()

    @router.get("/meta")
    def get_meta():
        from src.one_thing import (
            HORIZON_LABELS,
            HORIZON_TAGLINES,
            PARENT_HORIZON,
            PRIORITY_LABELS,
            links_required_for,
        )

        return {
            "horizons": [
                {
                    "key": h,
                    "label": HORIZON_LABELS[h],
                    "tagline": HORIZON_TAGLINES[h],
                    "links_required": links_required_for(h),
                    "parent_horizon": PARENT_HORIZON.get(h),
                    "parent_label": HORIZON_LABELS[PARENT_HORIZON[h]]
                    if PARENT_HORIZON.get(h)
                    else None,
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
                parent_ids=body.parent_ids,
            )
            after_task_change(owner)
            from src.one_thing import enrich_task_item, list_tasks as _list_tasks

            all_tasks = _list_tasks(db, owner, include_done=True, include_archived=True)
            return {"ok": True, "task": enrich_task_item(task, all_tasks)}
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
                parent_ids=body.parent_ids,
            )
            if not task:
                raise HTTPException(404, "Task not found")
            after_task_change(owner)
            from src.one_thing import enrich_task_item, list_tasks as _list_tasks

            all_tasks = _list_tasks(db, owner, include_done=True, include_archived=True)
            return {"ok": True, "task": enrich_task_item(task, all_tasks)}
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
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
        after_task_change(owner)
        return {"ok": True, "task": task.to_item()}

    @router.delete("/tasks/{task_id}")
    def remove_task(task_id: str, request: Request):
        owner = _owner(request)
        db = SessionLocal()
        try:
            if not delete_task(db, owner, task_id):
                raise HTTPException(404, "Task not found")
            after_task_change(owner)
            return {"ok": True}
        finally:
            db.close()

    @router.post("/sync")
    def rebuild_knowledge_index(request: Request):
        """Rebuild the portable knowledge graph (replaces legacy vault sync)."""
        owner = _owner(request)
        result = force_rebuild(owner)
        if not result.get("ok"):
            raise HTTPException(400, result.get("error") or "Rebuild failed")
        return result

    return router
