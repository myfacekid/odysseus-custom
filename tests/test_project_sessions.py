"""Phase 0d — sessions.project_id migration and project-scoped chats."""

import sqlite3
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

import core.database as cdb
import core.session_manager as SM
from core.database import Session as DbSession, _migrate_add_project_id_column, _migrate_backfill_project_session_mode
from core.session_manager import SessionManager
from routes import project_routes
from src.project_sessions import create_project_session, list_project_sessions
from src.project_workspace import create_project


@pytest.fixture
def db_env(tmp_path, monkeypatch):
    db_path = tmp_path / "phase0d.db"
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
        poolclass=NullPool,
    )
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    cdb.Base.metadata.create_all(engine)
    monkeypatch.setattr(cdb, "SessionLocal", Session)
    monkeypatch.setattr(SM, "SessionLocal", Session)
    monkeypatch.setattr(cdb, "DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setattr("src.project_workspace.PROJECTS_ROOT", tmp_path / "projects")

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    create_project(
        "alice",
        title="Session project",
        working_dir=str(workspace),
        project_id="proj-sessions",
    )
    manager = SessionManager()
    manager.sessions = {}
    return {"manager": manager, "project_id": "proj-sessions"}


def test_migration_adds_project_id_column(tmp_path, monkeypatch):
    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE sessions (id TEXT PRIMARY KEY, name TEXT, endpoint_url TEXT, "
        "model TEXT, owner TEXT, archived BOOLEAN DEFAULT 0)"
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(cdb, "DATABASE_URL", f"sqlite:///{db_path}")
    _migrate_add_project_id_column()

    conn = sqlite3.connect(db_path)
    columns = [row[1] for row in conn.execute("PRAGMA table_info(sessions)")]
    indexes = [row[1] for row in conn.execute("PRAGMA index_list(sessions)")]
    conn.close()
    assert "project_id" in columns
    assert "ix_sessions_project_id" in indexes


def test_create_and_list_project_sessions(db_env):
    manager = db_env["manager"]
    project_id = db_env["project_id"]

    created = create_project_session(
        manager,
        "alice",
        project_id,
        name="Analysis chat",
        endpoint_url="http://localhost:8000/v1",
        model="test-model",
    )
    assert created["project_id"] == project_id
    assert created["mode"] == "project"

    rows = list_project_sessions(manager, "alice", project_id)
    assert len(rows) == 1
    assert rows[0]["id"] == created["id"]
    assert rows[0]["name"] == "Analysis chat"

    # Unlinked session should not appear in project list.
    other_id = str(uuid.uuid4())
    manager.create_session(
        session_id=other_id,
        name="Main chat",
        endpoint_url="http://localhost:8000/v1",
        model="test-model",
        owner="alice",
    )
    rows = list_project_sessions(manager, "alice", project_id)
    assert len(rows) == 1


def test_project_sessions_api(db_env, monkeypatch):
    monkeypatch.setattr(project_routes, "get_current_user", lambda request: "alice")
    app = FastAPI()
    app.include_router(project_routes.setup_project_routes(db_env["manager"]))
    client = TestClient(app)
    pid = db_env["project_id"]

    res = client.post(
        f"/api/projects/{pid}/sessions",
        json={"name": "Via API", "endpoint_url": "http://x/v1", "model": "m"},
    )
    assert res.status_code == 200
    session_id = res.json()["session"]["id"]

    res = client.get(f"/api/projects/{pid}/sessions")
    assert res.status_code == 200
    body = res.json()
    assert body["count"] == 1
    assert body["sessions"][0]["id"] == session_id
    assert body["sessions"][0]["project_id"] == pid


def test_project_sessions_api_cross_owner(db_env, monkeypatch):
    monkeypatch.setattr(project_routes, "get_current_user", lambda request: "bob")
    app = FastAPI()
    app.include_router(project_routes.setup_project_routes(db_env["manager"]))
    client = TestClient(app)

    res = client.get(f"/api/projects/{db_env['project_id']}/sessions")
    assert res.status_code == 404


def test_backfill_project_session_mode(tmp_path, monkeypatch):
    db_path = tmp_path / "backfill.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE sessions (id TEXT PRIMARY KEY, name TEXT, project_id TEXT, mode TEXT)"
    )
    conn.execute(
        "INSERT INTO sessions (id, name, project_id, mode) VALUES (?, ?, ?, ?)",
        ("s1", "Legacy project chat", "proj-x", None),
    )
    conn.execute(
        "INSERT INTO sessions (id, name, project_id, mode) VALUES (?, ?, ?, ?)",
        ("s2", "Main chat", None, "agent"),
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(cdb, "DATABASE_URL", f"sqlite:///{db_path}")
    _migrate_backfill_project_session_mode()

    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT mode FROM sessions WHERE id = 's1'").fetchone()
    other = conn.execute("SELECT mode FROM sessions WHERE id = 's2'").fetchone()
    conn.close()
    assert row[0] == "project"
    assert other[0] == "agent"


def test_is_project_workspace_session_helper():
    from core.database import is_project_workspace_session

    assert is_project_workspace_session("project", None)
    assert is_project_workspace_session(None, "proj-1")
    assert is_project_workspace_session("agent", None) is False
    assert is_project_workspace_session(None, None) is False


def test_project_sessions_marked_for_main_nav_exclusion(db_env):
    manager = db_env["manager"]
    project_id = db_env["project_id"]

    project_chat = create_project_session(
        manager,
        "alice",
        project_id,
        name="Workspace chat",
        endpoint_url="http://localhost:8000/v1",
        model="test-model",
    )
    main_id = str(uuid.uuid4())
    manager.create_session(
        session_id=main_id,
        name="Main sidebar chat",
        endpoint_url="http://localhost:8000/v1",
        model="test-model",
        owner="alice",
    )

    from core.database import SessionLocal, is_project_workspace_session

    db = SessionLocal()
    try:
        rows = {row.id: row for row in db.query(DbSession).all()}
        assert is_project_workspace_session(
            rows[project_chat["id"]].mode,
            rows[project_chat["id"]].project_id,
        )
        assert not is_project_workspace_session(
            rows[main_id].mode,
            rows[main_id].project_id,
        )
    finally:
        db.close()
