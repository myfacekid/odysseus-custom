"""Promote a project cwd file into Library (Documents / Notes / ingest).

Explicit bridge only — never mirrors trees. Paths stay jail-checked under the
project working directory via ``read_text_file``.
"""
from __future__ import annotations

import os
import uuid
from typing import Any, Dict, Optional

from src.project_files import ProjectFileError, read_text_file
from src.project_graph import project_node_id
from src.project_paths import ProjectPathError
from src.project_workspace import (
    ProjectAccessError,
    ProjectNotFoundError,
    assert_project_owner,
)

PROMOTE_TYPES = frozenset({"document", "note", "ingest"})


class ProjectPromoteError(ValueError):
    """Invalid promote request."""


def _basename_title(rel_path: str, override: Optional[str]) -> str:
    if override and str(override).strip():
        return str(override).strip()[:200]
    name = os.path.basename((rel_path or "").replace("\\", "/").rstrip("/")) or "Promoted file"
    return name[:200]


def _sniff_language(path: str, content: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    mapping = {
        ".py": "python",
        ".js": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".jsx": "javascript",
        ".json": "json",
        ".md": "markdown",
        ".markdown": "markdown",
        ".html": "html",
        ".css": "css",
        ".yml": "yaml",
        ".yaml": "yaml",
        ".sh": "shell",
        ".rs": "rust",
        ".go": "go",
        ".sql": "sql",
        ".toml": "toml",
        ".r": "r",
        ".R": "r",
    }
    if ext in mapping:
        return mapping[ext]
    # prose default
    if content.lstrip().startswith("#") or "\n# " in content[:500]:
        return "markdown"
    return "markdown" if len(content) > 40 and "\n" in content else "text"


def _create_library_document(
    *,
    owner: Optional[str],
    title: str,
    content: str,
    language: str,
    source_summary: str,
) -> Dict[str, Any]:
    from core.database import Document, DocumentVersion, SessionLocal

    doc_id = str(uuid.uuid4())
    ver_id = str(uuid.uuid4())
    db = SessionLocal()
    try:
        doc = Document(
            id=doc_id,
            session_id=None,
            title=title,
            language=language,
            current_content=content,
            version_count=1,
            is_active=True,
            owner=owner,
        )
        ver = DocumentVersion(
            id=ver_id,
            document_id=doc_id,
            version_number=1,
            content=content,
            summary=source_summary,
            source="project_promote",
        )
        db.add(doc)
        db.add(ver)
        db.commit()
        db.refresh(doc)
        if owner:
            try:
                from src.knowledge_sync import after_document_change
                after_document_change(owner)
            except Exception:
                pass
        try:
            from src.event_bus import fire_event
            fire_event("document_created", owner)
        except Exception:
            pass
        return {
            "library_type": "document",
            "id": doc.id,
            "title": doc.title,
            "node_id": f"document:{doc.id}",
            "language": doc.language,
        }
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _create_library_note(
    *,
    owner: Optional[str],
    title: str,
    content: str,
) -> Dict[str, Any]:
    from core.database import Note, SessionLocal

    note_id = str(uuid.uuid4())
    db = SessionLocal()
    try:
        note = Note(
            id=note_id,
            title=title,
            content=content,
            note_type="note",
            owner=owner,
            source="project_promote",
        )
        db.add(note)
        db.commit()
        db.refresh(note)
        try:
            from src.event_bus import fire_event
            fire_event("note_created", owner)
        except Exception:
            pass
        return {
            "library_type": "note",
            "id": note.id,
            "title": note.title or title,
            "node_id": f"note:{note.id}",
        }
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _maybe_link(owner: Optional[str], project_id: str, to_id: str, link: bool) -> Optional[Dict[str, Any]]:
    if not link or not to_id:
        return None
    from src.knowledge_graph import add_graph_link

    from_id = project_node_id(project_id)
    edge = add_graph_link(owner, from_id, to_id, kind="relates", source="project_promote")
    return {"from_id": from_id, "to_id": to_id, "kind": "relates", "edge": edge}


def promote_project_file(
    owner: Optional[str],
    project_id: str,
    rel_path: str,
    *,
    library_type: str = "document",
    title: Optional[str] = None,
    link: bool = True,
) -> Dict[str, Any]:
    """Copy a cwd text file into Library as document, note, or ingest corpus entry."""
    kind = (library_type or "document").strip().lower()
    if kind not in PROMOTE_TYPES:
        raise ProjectPromoteError(
            f"library_type must be one of: {', '.join(sorted(PROMOTE_TYPES))}"
        )
    assert_project_owner(owner, project_id)
    try:
        payload = read_text_file(owner, project_id, rel_path)
    except (ProjectPathError, ProjectFileError) as exc:
        raise ProjectPromoteError(str(exc)) from exc
    except (ProjectNotFoundError, ProjectAccessError):
        raise

    content = payload.get("content") or ""
    path = payload.get("path") or rel_path
    final_title = _basename_title(path, title)
    language = _sniff_language(path, content)
    summary = f"Promoted from project cwd: {path}"

    if kind == "note":
        artifact = _create_library_note(owner=owner, title=final_title, content=content)
    else:
        # document and ingest both land as library documents; ingest keeps
        # wording so UI can call it a corpus ingest while still searchable.
        if kind == "ingest" and not (title and str(title).strip()):
            final_title = f"Ingest · {final_title}"
        artifact = _create_library_document(
            owner=owner,
            title=final_title,
            content=content,
            language=language if kind != "ingest" else language or "markdown",
            source_summary=summary if kind != "ingest" else f"Corpus ingest from project cwd: {path}",
        )
        artifact["library_type"] = kind

    link_info = None
    try:
        link_info = _maybe_link(owner, project_id, artifact.get("node_id"), link)
    except Exception as exc:
        link_info = {"error": str(exc)}

    return {
        "ok": True,
        "project_id": project_id,
        "path": path,
        "artifact": artifact,
        "link": link_info,
    }


def map_promote_exception(exc: Exception) -> tuple[int, str]:
    if isinstance(exc, ProjectNotFoundError):
        return 404, "Project not found"
    if isinstance(exc, ProjectAccessError):
        return 404, "Project not found"
    if isinstance(exc, ProjectPromoteError):
        return 400, str(exc)
    if isinstance(exc, ProjectPathError):
        return 400, str(exc)
    if isinstance(exc, ProjectFileError):
        return 400, str(exc)
    return 500, "Promote failed"
