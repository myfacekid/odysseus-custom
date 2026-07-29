"""Danger Zone wipe kind=links clears manual/pending/rejected edges."""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi import Request

from core.database import Base
from routes.admin_wipe_routes import setup_admin_wipe_routes


def test_wipe_links_clears_manual_pending_rejected(tmp_path, monkeypatch):
    users = tmp_path / "knowledge" / "users" / "tester"
    users.mkdir(parents=True)
    (users / "manual_edges.jsonl").write_text(
        '{"from":"a","to":"b","kind":"relates"}\n'
        '{"from":"c","to":"d","kind":"supports"}\n',
        encoding="utf-8",
    )
    (users / "pending_edges.jsonl").write_text(
        '{"id":"p1","from":"e","to":"f","kind":"relates","status":"pending"}\n',
        encoding="utf-8",
    )
    (users / "rejected_edge_keys.jsonl").write_text(
        '{"from":"g","to":"h","kind":"relates"}\n',
        encoding="utf-8",
    )
    (users / "edges.jsonl").write_text(
        '{"from":"task:1","to":"task:2","kind":"parent"}\n'
        '{"from":"a","to":"b","kind":"relates"}\n',
        encoding="utf-8",
    )
    (users / "nodes.jsonl").write_text(
        '{"id":"a","type":"document","title":"A"}\n',
        encoding="utf-8",
    )

    import src.knowledge_graph as kg
    import routes.admin_wipe_routes as wipe_mod

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    TestSessionLocal = sessionmaker(bind=engine)

    monkeypatch.setattr(kg, "KNOWLEDGE_ROOT", tmp_path / "knowledge")
    monkeypatch.setattr(wipe_mod, "SessionLocal", TestSessionLocal)
    monkeypatch.setattr(wipe_mod, "require_admin", lambda r: None)

    router = setup_admin_wipe_routes(session_manager=None)
    wipe_route = next(r for r in router.routes if r.path == "/api/admin/wipe/{kind}")
    result = wipe_route.endpoint(kind="links", request=Request(scope={"type": "http"}))

    assert result["status"] == "deleted"
    assert result["kind"] == "links"
    assert result["count"] == 4  # 2 manual + 1 pending + 1 rejected

    assert kg.load_manual_edges("tester") == []
    assert not (users / "pending_edges.jsonl").exists()
    assert not (users / "rejected_edge_keys.jsonl").exists()
    # Inferred parent edge kept; manual relates dropped from edges.jsonl
    edges = kg.load_edges("tester")
    assert edges == [{"from": "task:1", "to": "task:2", "kind": "parent"}]
    # Nodes untouched
    assert (users / "nodes.jsonl").is_file()
    assert "document" in (users / "nodes.jsonl").read_text(encoding="utf-8")
