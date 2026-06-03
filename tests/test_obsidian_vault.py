"""Tests for native vault read/search and filesystem mode."""

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from src.obsidian_vault import (
    VaultConfig,
    append_vault_sources_marker,
    execute_search_vault_tool,
    extract_vault_search_query,
    list_vault,
    read_vault_note,
    resolve_vault_config,
    resolve_vault_mode,
    search_vault_notes,
    vault_plugins_enabled,
    vault_ui_sources_from_output,
    _resolve_within_vault,
)


@pytest.fixture
def sample_vault(tmp_path):
    meetings = tmp_path / "Meetings"
    daily = tmp_path / "Daily Notes"
    meetings.mkdir()
    daily.mkdir()
    (meetings / "standup.md").write_text("# Standup\nDiscuss epistasis project.", encoding="utf-8")
    (tmp_path / "Epistasis and Influenza.md").write_text(
        "# Epistasis and Influenza\nCross-scale epistasis in HA evolution.",
        encoding="utf-8",
    )
    (daily / "2026-06-01.md").write_text("- [ ] Finish lab notes\n- [x] Email committee", encoding="utf-8")
    return VaultConfig(vault_path=str(tmp_path), daily_notes_folder="Daily Notes")


def test_resolve_within_vault_blocks_escape(sample_vault):
    ok, err = _resolve_within_vault(sample_vault, "Meetings/standup.md")
    assert err is None
    assert ok.name == "standup.md"

    bad, err = _resolve_within_vault(sample_vault, "../etc/passwd")
    assert bad is None
    assert "escapes" in err


def test_list_and_read(sample_vault):
    listed = list_vault(sample_vault, folder="Meetings")
    assert listed["exit_code"] == 0
    assert "Meetings/standup.md" in listed["output"]

    read = read_vault_note(sample_vault, "Meetings/standup.md")
    assert read["exit_code"] == 0
    assert "epistasis" in read["output"]


def test_search(sample_vault):
    found = search_vault_notes(sample_vault, query="epistasis")
    assert found["exit_code"] == 0
    assert "Epistasis and Influenza.md" in found["output"]

    todos = search_vault_notes(sample_vault, query="lab notes", folder="Daily Notes")
    assert todos["exit_code"] == 0
    assert "2026-06-01.md" in todos["output"]


def test_extract_vault_search_query():
    assert extract_vault_search_query("Search my vault for epistasis") == "epistasis"
    assert extract_vault_search_query("What do my notes say about epistasis?") == "epistasis"


def test_search_natural_language_query(sample_vault):
    found = search_vault_notes(sample_vault, query="Search my vault for epistasis")
    assert found["exit_code"] == 0
    assert "Epistasis and Influenza.md" in found["output"]
    assert found["output"].index("Epistasis and Influenza.md") < found["output"].find("Meetings/standup.md")


def test_execute_tool_not_configured(monkeypatch):
    monkeypatch.setattr(
        "src.obsidian_vault.resolve_vault_config",
        lambda owner="": None,
    )
    out = execute_search_vault_tool({"action": "list"}, owner="user")
    assert out["exit_code"] == 1
    assert "not configured" in out["output"].lower()


def test_vault_ui_sources_from_output():
    output = "Vault search — scope: entire vault\n\n- `Epistasis and Influenza.md` (keyword)"
    sources = vault_ui_sources_from_output(output)
    assert len(sources) == 1
    assert sources[0]["source"] == "vault"
    assert sources[0]["path"] == "Epistasis and Influenza.md"
    marked = append_vault_sources_marker(output)
    assert "<!-- SOURCES:" in marked


def test_default_vault_path_exists():
    default = os.path.expanduser("~/Documents/Vault_1/Vault_1")
    if Path(default).is_dir():
        cfg = resolve_vault_config("")
        assert cfg is not None
        assert cfg.root.is_dir()


def test_filesystem_mode_skips_plugins(sample_vault):
    with patch("src.vault_plugins.search_plugin_sources") as mock_plugins:
        with patch("src.obsidian_vault.vault_plugins_enabled", return_value=False):
            found = search_vault_notes(sample_vault, query="epistasis", owner="user")
        mock_plugins.assert_not_called()
    assert found["exit_code"] == 0
    assert "Epistasis and Influenza.md" in found["output"]


def test_resolve_vault_mode_defaults_filesystem():
    with patch("src.obsidian_vault._load_vault_user_cfg", return_value={}):
        assert resolve_vault_mode("user") == "filesystem"
        assert vault_plugins_enabled("user") is False


def test_resolve_vault_mode_hybrid():
    with patch("src.obsidian_vault._load_vault_user_cfg", return_value={"vault_mode": "hybrid"}):
        assert resolve_vault_mode("user") == "hybrid"
        assert vault_plugins_enabled("user") is True
