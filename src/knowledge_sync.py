"""Replace vault sync hooks with knowledge graph rebuild scheduling."""

from src.knowledge_graph import rebuild_owner_graph, schedule_rebuild


def after_task_change(owner: str) -> None:
    schedule_rebuild(owner)


def after_document_change(owner: str) -> None:
    schedule_rebuild(owner)


def after_memory_change(owner: str) -> None:
    schedule_rebuild(owner)


def after_skill_change(owner: str) -> None:
    schedule_rebuild(owner)


def after_zotero_sync(owner: str) -> None:
    schedule_rebuild(owner)


def force_rebuild(owner: str) -> dict:
    return rebuild_owner_graph(owner)
