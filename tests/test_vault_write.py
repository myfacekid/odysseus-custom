"""Tests for vault write and wikilink operations."""

from src.obsidian_vault import VaultConfig
from src.vault_write import (
    append_vault_note,
    create_vault_note,
    follow_vault_links,
    link_vault_notes,
    patch_vault_note,
)


def test_create_append_patch_link_follow(tmp_path):
    cfg = VaultConfig(vault_path=str(tmp_path), daily_notes_folder="Daily Notes")
    a = create_vault_note(cfg, folder="Notes", title="Topic A", content="# A\n\nSeed.")
    assert a["exit_code"] == 0

    b = create_vault_note(cfg, path="Notes/Topic B.md", content="# B\n\nBody.")
    assert b["exit_code"] == 0

    link = link_vault_notes(cfg, from_path="Notes/Topic A.md", to="Topic B")
    assert link["exit_code"] == 0

    app = append_vault_note(cfg, "Notes/Topic A.md", "- bullet")
    assert app["exit_code"] == 0

    patch = patch_vault_note(cfg, "Notes/Topic A.md", find="Seed.", replace="Seed updated.")
    assert patch["exit_code"] == 0

    follow = follow_vault_links(cfg, "Notes/Topic A.md", depth=1, max_notes=3)
    assert follow["exit_code"] == 0
    assert "Topic B" in follow["output"]
