"""Danger Zone wipe kind=todos clears One Thing boards; notes wipe skips them."""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi import Request

from core.database import Base, Note
from routes.admin_wipe_routes import setup_admin_wipe_routes


def _wipe_handler(monkeypatch, SessionLocal):
    import routes.admin_wipe_routes as wipe_mod

    monkeypatch.setattr(wipe_mod, "SessionLocal", SessionLocal)
    monkeypatch.setattr(wipe_mod, "require_admin", lambda r: None)
    router = setup_admin_wipe_routes(session_manager=None)
    wipe_route = next(r for r in router.routes if r.path == "/api/admin/wipe/{kind}")
    return wipe_route.endpoint


def test_wipe_todos_clears_one_thing_boards(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine)

    db = SessionLocal()
    db.add(Note(
        id="board-1",
        owner="tester",
        title="Todos",
        note_type="one_thing",
        items='[{"id":"t1","text":"A"},{"id":"t2","text":"B"},{"id":"t3","text":"C"}]',
    ))
    db.add(Note(id="n1", owner="tester", title="Keep me", note_type="note", content="hi"))
    db.add(Note(id="c1", owner="tester", title="List", note_type="checklist", items="[]"))
    db.commit()
    db.close()

    wipe = _wipe_handler(monkeypatch, SessionLocal)
    result = wipe(kind="todos", request=Request(scope={"type": "http"}))

    assert result == {"status": "deleted", "kind": "todos", "count": 3}

    db = SessionLocal()
    assert db.query(Note).filter(Note.note_type == "one_thing").count() == 0
    assert db.query(Note).filter(Note.id == "n1").count() == 1
    assert db.query(Note).filter(Note.id == "c1").count() == 1
    db.close()


def test_wipe_notes_skips_todos(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine)

    db = SessionLocal()
    db.add(Note(
        id="board-1",
        owner="tester",
        title="Todos",
        note_type="one_thing",
        items='[{"id":"t1","text":"A"}]',
    ))
    db.add(Note(id="n1", owner="tester", title="Gone", note_type="note"))
    db.commit()
    db.close()

    wipe = _wipe_handler(monkeypatch, SessionLocal)
    result = wipe(kind="notes", request=Request(scope={"type": "http"}))

    assert result["kind"] == "notes"
    assert result["count"] == 1

    db = SessionLocal()
    assert db.query(Note).filter(Note.note_type == "one_thing").count() == 1
    assert db.query(Note).filter(Note.id == "n1").count() == 0
    db.close()
