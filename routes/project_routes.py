"""Project workspace routes — records and scoped file CRUD (Phase 0)."""

import asyncio
import logging
import os
import re
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from src.auth_helpers import _auth_disabled, get_current_user
from src.project_files import (
    delete_path,
    list_directory,
    map_project_exception,
    mkdir,
    read_text_file,
    rename_path,
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
    archive_project,
    assert_project_owner,
    create_project,
    get_project,
    list_projects,
    refresh_working_dir_status,
    save_project,
)
from src.project_paths import find_dirs_named_under_root, is_path_under_root
from src.project_graph import get_project_graph_links, project_node_id
from src.knowledge_graph import add_graph_link, remove_graph_link

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


class ProjectRenameRequest(BaseModel):
    src: str = Field(..., min_length=1, max_length=4096)
    dest: str = Field(..., min_length=1, max_length=4096)


class ProjectRunRequest(BaseModel):
    path: str = Field(..., min_length=1, max_length=4096)
    args: Optional[list[str]] = Field(default=None, max_length=16)
    timeout: Optional[int] = Field(default=None, ge=1, le=300)


class ProjectSessionCreateRequest(BaseModel):
    name: str = Field(default="Project chat", max_length=200)
    endpoint_url: str = Field(default="", max_length=4096)
    model: str = Field(default="", max_length=512)
    rag: bool = False


class ProjectLinkCreateRequest(BaseModel):
    to_id: str = Field(..., min_length=1)
    kind: str = Field(default="related", max_length=32)


class ProjectValidateDirRequest(BaseModel):
    working_dir: str = Field(..., min_length=1, max_length=4096)


class ProjectResolveDirRequest(BaseModel):
    folder_name: str = Field(..., min_length=1, max_length=256)
    relative_hint: str = Field(default="", max_length=4096)


def setup_project_routes(session_manager=None) -> APIRouter:
    router = APIRouter(prefix="/api/projects", tags=["projects"])

    def _owner(request: Request) -> str:
        user = get_current_user(request)
        if not user:
            if _auth_disabled():
                return ""
            raise HTTPException(401, "Not authenticated")
        return user

    def _browse_home() -> str:
        return os.path.realpath(os.path.expanduser("~"))

    def _assert_browse_path(path: str) -> str:
        try:
            resolved = os.path.realpath(os.path.expanduser((path or "").strip() or "~"))
        except OSError as exc:
            raise HTTPException(400, "Invalid path") from exc
        home = _browse_home()
        if resolved != home and not is_path_under_root(resolved, home):
            raise HTTPException(403, "Path outside allowed browse area")
        if not os.path.isdir(resolved):
            raise HTTPException(404, "Not a directory")
        if not os.access(resolved, os.R_OK | os.X_OK):
            raise HTTPException(403, "Permission denied")
        return resolved

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
        projects = list_projects(owner)
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

    @router.post("/validate-dir")
    async def validate_working_directory(body: ProjectValidateDirRequest, request: Request):
        _owner(request)
        project = refresh_working_dir_status({"working_dir": body.working_dir})
        return {
            "working_dir": project.get("working_dir"),
            "working_dir_status": project.get("working_dir_status"),
            "working_dir_warning": project.get("working_dir_warning"),
        }

    @router.get("/browse-dir")
    async def browse_working_directory(request: Request, path: str = ""):
        _owner(request)
        resolved = _assert_browse_path(path or "~")
        home = _browse_home()
        parent = os.path.dirname(resolved)
        parent_path = None
        if parent and parent != resolved and is_path_under_root(parent, home):
            parent_path = parent
        entries = []
        try:
            for name in sorted(os.listdir(resolved)):
                if name.startswith("."):
                    continue
                full = os.path.join(resolved, name)
                if not os.path.isdir(full):
                    continue
                try:
                    entry_path = os.path.realpath(full)
                except OSError:
                    continue
                if not is_path_under_root(entry_path, home):
                    continue
                if not os.access(entry_path, os.R_OK | os.X_OK):
                    continue
                entries.append({"name": name, "path": entry_path})
                if len(entries) >= 300:
                    break
        except PermissionError as exc:
            raise HTTPException(403, "Permission denied") from exc
        truncated = False
        try:
            total_dirs = sum(
                1 for name in os.listdir(resolved)
                if not name.startswith(".") and os.path.isdir(os.path.join(resolved, name))
            )
            truncated = total_dirs > len(entries)
        except OSError:
            truncated = len(entries) >= 300
        return {
            "path": resolved,
            "parent": parent_path,
            "entries": entries,
            "truncated": truncated,
        }

    @router.post("/resolve-dir")
    async def resolve_native_directory(body: ProjectResolveDirRequest, request: Request):
        _owner(request)
        folder_name = (body.folder_name or "").strip()
        if not folder_name or folder_name in {".", ".."} or "/" in folder_name or "\\" in folder_name:
            raise HTTPException(400, "Invalid folder name")

        home = _browse_home()
        hint = (body.relative_hint or "").strip().replace("\\", "/").strip("/")

        def _valid_dir(path: str) -> str | None:
            try:
                resolved = os.path.realpath(os.path.expanduser(path))
            except OSError:
                return None
            if not is_path_under_root(resolved, home):
                return None
            if not os.path.isdir(resolved):
                return None
            if not os.access(resolved, os.R_OK | os.X_OK):
                return None
            return resolved

        direct_candidates = [
            os.path.join(home, folder_name),
            os.path.expanduser(f"~/{folder_name}"),
        ]
        if hint:
            direct_candidates.extend([
                os.path.join(home, hint),
                os.path.expanduser(f"~/{hint}"),
                os.path.join(home, hint, folder_name),
                os.path.expanduser(f"~/{hint}/{folder_name}"),
            ])
        seen_direct: set[str] = set()
        for candidate in direct_candidates:
            resolved = _valid_dir(candidate)
            if not resolved or resolved in seen_direct:
                continue
            seen_direct.add(resolved)
            if os.path.basename(resolved) == folder_name:
                return {"path": resolved, "matches": 1, "candidates": []}

        matches = find_dirs_named_under_root(home, folder_name, max_depth=12, limit=30)
        if hint and len(matches) > 1:
            hint_parts = [part for part in hint.split("/") if part and part != "."]
            if hint_parts:
                filtered = [
                    match for match in matches
                    if all(part in match.split(os.sep) for part in hint_parts)
                ]
                if filtered:
                    matches = filtered

        if len(matches) == 1:
            return {"path": matches[0], "matches": 1, "candidates": []}

        guess = _valid_dir(os.path.join(home, folder_name)) or _valid_dir(os.path.expanduser(f"~/{folder_name}"))
        guess_path = guess or os.path.realpath(os.path.expanduser(f"~/{folder_name}"))
        if len(matches) > 1:
            return {
                "path": "",
                "matches": len(matches),
                "candidates": matches[:20],
                "guess": guess_path,
            }

        return {
            "path": guess or "",
            "matches": 0,
            "candidates": [],
            "guess": guess_path,
        }

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

    @router.delete("/{project_id}")
    async def archive_user_project(project_id: str, request: Request):
        owner = _owner(request)
        _validate_project_id(project_id)
        try:
            project = archive_project(owner, project_id)
        except ProjectNotFoundError:
            raise HTTPException(404, "Project not found")
        except ProjectAccessError:
            raise HTTPException(404, "Project not found")
        return {"ok": True, "project": project}

    @router.get("/{project_id}/links")
    async def list_project_links(project_id: str, request: Request):
        owner = _owner(request)
        _validate_project_id(project_id)
        try:
            links = get_project_graph_links(owner, project_id)
        except ProjectNotFoundError:
            raise HTTPException(404, "Project not found")
        except ProjectAccessError:
            raise HTTPException(404, "Project not found")
        return links

    @router.post("/{project_id}/links")
    async def add_project_link(
        project_id: str,
        body: ProjectLinkCreateRequest,
        request: Request,
    ):
        owner = _owner(request)
        _validate_project_id(project_id)
        try:
            assert_project_owner(owner, project_id)
        except ProjectNotFoundError:
            raise HTTPException(404, "Project not found")
        except ProjectAccessError:
            raise HTTPException(404, "Project not found")
        from src.project_graph import ensure_graph_node_for_link

        ensure_graph_node_for_link(owner, body.to_id)
        result = add_graph_link(owner, project_node_id(project_id), body.to_id, kind=body.kind)
        if not result.get("ok"):
            raise HTTPException(400, result.get("error") or "Link failed")
        try:
            from src.project_graph import upsert_project_node

            upsert_project_node(owner, assert_project_owner(owner, project_id))
        except Exception:
            pass
        return result

    @router.delete("/{project_id}/links")
    async def remove_project_link(
        project_id: str,
        request: Request,
        to_id: str = Query(..., min_length=1),
        kind: Optional[str] = Query(None),
    ):
        owner = _owner(request)
        _validate_project_id(project_id)
        try:
            assert_project_owner(owner, project_id)
        except ProjectNotFoundError:
            raise HTTPException(404, "Project not found")
        except ProjectAccessError:
            raise HTTPException(404, "Project not found")
        result = remove_graph_link(owner, project_node_id(project_id), to_id, kind=kind)
        if not result.get("ok"):
            raise HTTPException(404, result.get("error") or "Link not found")
        return result

    @router.get("/{project_id}/files")
    async def list_project_files(
        project_id: str,
        request: Request,
        path: str = Query("."),
    ):
        owner = _owner(request)
        _validate_project_id(project_id)
        try:
            payload = list_directory(owner, project_id, path)
        except (ProjectNotFoundError, ProjectAccessError) as exc:
            _handle(exc)
        except Exception as exc:
            _handle(exc)
        return payload

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
        recursive: bool = Query(False),
    ):
        owner = _owner(request)
        _validate_project_id(project_id)
        try:
            payload = delete_path(owner, project_id, path, recursive=recursive)
        except (ProjectNotFoundError, ProjectAccessError) as exc:
            _handle(exc)
        except Exception as exc:
            _handle(exc)
        return {"ok": True, **payload}

    @router.post("/{project_id}/rename")
    async def rename_project_path(
        project_id: str,
        body: ProjectRenameRequest,
        request: Request,
    ):
        owner = _owner(request)
        _validate_project_id(project_id)
        try:
            payload = rename_path(owner, project_id, body.src, body.dest)
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
