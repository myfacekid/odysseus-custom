"""Tests for project cwd → Library promote (context layer L4)."""
from __future__ import annotations

from pathlib import Path

import pytest

from src.project_promote import ProjectPromoteError, promote_project_file
from src.project_workspace import create_project
import src.project_workspace as pw


@pytest.fixture()
def owner_project(tmp_path, monkeypatch):
    monkeypatch.setattr(pw, "PROJECTS_ROOT", tmp_path / "projects")
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    (cwd / "analysis.py").write_text("print('hi')\n", encoding="utf-8")
    (cwd / "notes").mkdir()
    (cwd / "notes" / "readme.md").write_text("# Hello\n\nWorld\n", encoding="utf-8")
    project = create_project(
        owner="testuser",
        title="Promote Lab",
        working_dir=str(cwd),
    )
    return "testuser", project["id"], cwd


def test_promote_to_document(owner_project):
    owner, pid, _cwd = owner_project
    result = promote_project_file(
        owner, pid, "analysis.py", library_type="document", link=False,
    )
    assert result["ok"] is True
    art = result["artifact"]
    assert art["library_type"] == "document"
    assert art["title"] == "analysis.py"
    assert art["id"]
    from core.database import Document, SessionLocal

    db = SessionLocal()
    try:
        doc = db.query(Document).filter(Document.id == art["id"]).one()
        assert "print('hi')" in (doc.current_content or "")
        assert doc.owner == owner
    finally:
        db.close()


def test_promote_to_note(owner_project):
    owner, pid, _cwd = owner_project
    result = promote_project_file(
        owner, pid, "notes/readme.md", library_type="note", title="Lab readme", link=False,
    )
    art = result["artifact"]
    assert art["library_type"] == "note"
    assert art["title"] == "Lab readme"
    from core.database import Note, SessionLocal

    db = SessionLocal()
    try:
        note = db.query(Note).filter(Note.id == art["id"]).one()
        assert "Hello" in (note.content or "")
    finally:
        db.close()


def test_promote_ingest_prefix(owner_project):
    owner, pid, _cwd = owner_project
    result = promote_project_file(
        owner, pid, "notes/readme.md", library_type="ingest", link=False,
    )
    assert result["artifact"]["library_type"] == "ingest"
    assert result["artifact"]["title"].startswith("Ingest ·")


def test_promote_rejects_bad_type(owner_project):
    owner, pid, _cwd = owner_project
    with pytest.raises(ProjectPromoteError):
        promote_project_file(owner, pid, "analysis.py", library_type="vault")


def test_promote_rejects_missing_file(owner_project):
    owner, pid, _cwd = owner_project
    with pytest.raises(ProjectPromoteError):
        promote_project_file(owner, pid, "nope.txt", library_type="document", link=False)


def test_promote_in_tool_policy():
    from src.project_tool_policy import (
        PROJECT_DEPTH_ALLOWED_TOOLS,
        is_project_depth_allowed_tool,
    )

    assert "promote_project_file" in PROJECT_DEPTH_ALLOWED_TOOLS
    assert is_project_depth_allowed_tool("promote_project_file")


def test_promote_tool_schema_present():
    # Avoid circular import flake: assert against source + warm agent_tools first.
    from pathlib import Path

    text = Path("src/tool_schemas.py").read_text(encoding="utf-8")
    assert '"name": "promote_project_file"' in text
    import src.agent_tools  # noqa: F401
    from src.tool_schemas import FUNCTION_TOOL_SCHEMAS

    names = [t["function"]["name"] for t in FUNCTION_TOOL_SCHEMAS if t.get("type") == "function"]
    assert "promote_project_file" in names
