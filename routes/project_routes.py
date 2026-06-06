"""Project workspace routes — records and scoped file CRUD (Phase 0)."""

import asyncio
import logging
import re
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from src.auth_helpers import get_current_user
from src.project_files import (
    delete_path,
    list_directory,
    map_project_exception,
    mkdir,
    read_text_file,
    write_text_file,
)
from src.project_runner import map_run_exception, run_python_script
from src.project_sessions import (
    create_project_session,
    list_project_sessions,
    map_session_exception,
)
from src.project_workspace import (
    ProjectAccessError,
    ProjectNotFoundError,
    assert_project_owner,
    create_project,
    get_project,
    list_projects,
    refresh_working_dir_status,
    save_project,
)

logger = logging.getLogger(__name__)

_PROJECT_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,128}$")


class ProjectCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    working_dir: str = Field(..., min_length=1, max_length=4096)
    description: str = Field(default="", max_length=2000)
    project_id: Optional[str] = Field(default=None, max_length=128)


class ProjectUpdateRequest(BaseModel):
    title: Optional[str] = Field(default=None, max_length=200)
    working_dir: Optional[str] = Field(default=None, max_length=4096)
    description: Optional[str] = Field(default=None, max_length=2000)


class ProjectFileWriteRequest(BaseModel):
    path: str = Field(..., min_length=1, max_length=4096)
    content: str = ""
    create_dirs: bool = True


class ProjectMkdirRequest(BaseModel):
    path: str = Field(..., min_length=1, max_length=4096)


class ProjectRunRequest(BaseModel):
    path: str = Field(..., min_length=1, max_length=4096)
    args: Optional[list[str]] = Field(default=None, max_length=16)
    timeout: Optional[int] = Field(default=None, ge=1, le=300)


class ProjectSessionCreateRequest(BaseModel):
    name: str = Field(default="Project chat", max_length=200)
    endpoint_url: str = Field(default="", max_length=4096)
    model: str = Field(default="", max_length=512)
    rag: bool = False


def setup_project_routes(session_manager=None) -> APIRouter:
    router = APIRouter(prefix="/api/projects", tags=["projects"])

    def _owner(request: Request) -> str:
        user = get_current_user(request)
        if not user:
            raise HTTPException(401, "Not authenticated")
        return user

    def _validate_project_id(project_id: str) -> None:
        if not _PROJECT_ID_RE.fullmatch(project_id or ""):
            raise HTTPException(400, "Invalid project ID format")

    def _handle(exc: Exception) -> None:
        status, detail = map_project_exception(exc)
        if status >= 500:
            logger.error("Project route error: %s", exc, exc_info=True)
        raise HTTPException(status, detail)

    @router.get("")
    async def list_user_projects(request: Request):
        owner = _owner(request)
        projects = [refresh_working_dir_status(p) for p in list_projects(owner)]
        return {"projects": projects, "count": len(projects)}

    @router.post("")
    async def create_user_project(body: ProjectCreateRequest, request: Request):
        owner = _owner(request)
        if body.project_id:
            _validate_project_id(body.project_id)
            if get_project(owner, body.project_id):
                raise HTTPException(409, "Project already exists")
        try:
            project = create_project(
                owner,
                title=body.title,
                working_dir=body.working_dir,
                project_id=body.project_id,
                description=body.description,
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return {"ok": True, "project": project}

    @router.get("/{project_id}")
    async def get_user_project(project_id: str, request: Request):
        owner = _owner(request)
        _validate_project_id(project_id)
        try:
            project = assert_project_owner(owner, project_id)
        except ProjectNotFoundError:
            raise HTTPException(404, "Project not found")
        except ProjectAccessError:
            raise HTTPException(404, "Project not found")
        return {"project": project}

    @router.patch("/{project_id}")
    async def update_user_project(
        project_id: str,
        body: ProjectUpdateRequest,
        request: Request,
    ):
        owner = _owner(request)
        _validate_project_id(project_id)
        project = get_project(owner, project_id)
        if not project:
            raise HTTPException(404, "Project not found")
        if body.title is not None:
            project["title"] = body.title.strip()[:200] or project.get("title") or "Untitled project"
        if body.description is not None:
            project["description"] = body.description.strip()[:2000]
        if body.working_dir is not None:
            wd = refresh_working_dir_status({"working_dir": body.working_dir})
            project["working_dir"] = wd["working_dir"]
            project["working_dir_status"] = wd["working_dir_status"]
        save_project(owner, project_id, project)
        return {"ok": True, "project": refresh_working_dir_status(project)}

    @router.get("/{project_id}/files")
    async def list_project_files(
        project_id: str,
        request: Request,
        path: str = Query("."),
    ):
        owner = _owner(request)
        _validate_project_id(project_id)
        try:
            entries = list_directory(owner, project_id, path)
        except (ProjectNotFoundError, ProjectAccessError) as exc:
            _handle(exc)
        except Exception as exc:
            _handle(exc)
        return {"path": path or ".", "entries": entries}

    @router.get("/{project_id}/file")
    async def read_project_file(
        project_id: str,
        request: Request,
        path: str = Query(..., min_length=1),
    ):
        owner = _owner(request)
        _validate_project_id(project_id)
        try:
            payload = read_text_file(owner, project_id, path)
        except (ProjectNotFoundError, ProjectAccessError) as exc:
            _handle(exc)
        except Exception as exc:
            _handle(exc)
        return payload

    @router.put("/{project_id}/file")
    async def write_project_file(
        project_id: str,
        body: ProjectFileWriteRequest,
        request: Request,
    ):
        owner = _owner(request)
        _validate_project_id(project_id)
        try:
            payload = write_text_file(
                owner,
                project_id,
                body.path,
                body.content,
                create_dirs=body.create_dirs,
            )
        except (ProjectNotFoundError, ProjectAccessError) as exc:
            _handle(exc)
        except Exception as exc:
            _handle(exc)
        return {"ok": True, **payload}

    @router.delete("/{project_id}/file")
    async def delete_project_file(
        project_id: str,
        request: Request,
        path: str = Query(..., min_length=1),
    ):
        owner = _owner(request)
        _validate_project_id(project_id)
        try:
            payload = delete_path(owner, project_id, path)
        except (ProjectNotFoundError, ProjectAccessError) as exc:
            _handle(exc)
        except Exception as exc:
            _handle(exc)
        return {"ok": True, **payload}

    @router.post("/{project_id}/mkdir")
    async def mkdir_project_path(
        project_id: str,
        body: ProjectMkdirRequest,
        request: Request,
    ):
        owner = _owner(request)
        _validate_project_id(project_id)
        try:
            payload = mkdir(owner, project_id, body.path)
        except (ProjectNotFoundError, ProjectAccessError) as exc:
            _handle(exc)
        except Exception as exc:
            _handle(exc)
        return {"ok": True, **payload}

    @router.post("/{project_id}/run")
    async def run_project_script_route(
        project_id: str,
        body: ProjectRunRequest,
        request: Request,
    ):
        owner = _owner(request)
        _validate_project_id(project_id)
        try:
            result = await asyncio.to_thread(
                run_python_script,
                owner,
                project_id,
                body.path,
                args=body.args,
                timeout=body.timeout,
            )
        except Exception as exc:
            status, detail = map_run_exception(exc)
            if status >= 500:
                logger.error("Project run error: %s", exc, exc_info=True)
            raise HTTPException(status, detail)
        return result

    @router.get("/{project_id}/sessions")
    async def list_project_chat_sessions(project_id: str, request: Request):
        owner = _owner(request)
        _validate_project_id(project_id)
        if session_manager is None:
            raise HTTPException(503, "Session manager unavailable")
        try:
            sessions = list_project_sessions(session_manager, owner, project_id)
        except Exception as exc:
            status, detail = map_session_exception(exc)
            raise HTTPException(status, detail)
        return {"project_id": project_id, "sessions": sessions, "count": len(sessions)}

    @router.post("/{project_id}/sessions")
    async def create_project_chat_session(
        project_id: str,
        body: ProjectSessionCreateRequest,
        request: Request,
    ):
        owner = _owner(request)
        _validate_project_id(project_id)
        if session_manager is None:
            raise HTTPException(503, "Session manager unavailable")
        try:
            session = create_project_session(
                session_manager,
                owner,
                project_id,
                name=body.name,
                endpoint_url=body.endpoint_url,
                model=body.model,
                rag=body.rag,
            )
        except Exception as exc:
            status, detail = map_session_exception(exc)
            raise HTTPException(status, detail)
        return {"ok": True, "session": session}

    return router
