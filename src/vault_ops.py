"""Filesystem-first vault operations — shared entry for AI, Todos, and routes.

All reads/writes go to markdown on disk. Wikilinks, backlinks, and graph traversal
are handled natively (VaultGraph + vault_write) — no Obsidian app or Smart Connections.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from src.obsidian_vault import (
    DEFAULT_VAULT_MODE,
    VALID_VAULT_MODES,
    VaultConfig,
    execute_search_vault_tool,
    list_vault,
    read_vault_note,
    resolve_vault_config,
    resolve_vault_mode,
    search_vault_backlinks,
    search_vault_for_chat,
    search_vault_notes,
    test_vault_connection,
    vault_plugins_enabled,
)

__all__ = [
    "DEFAULT_VAULT_MODE",
    "VALID_VAULT_MODES",
    "VaultConfig",
    "execute_search_vault_tool",
    "list_vault",
    "read_vault_note",
    "resolve_vault_config",
    "resolve_vault_mode",
    "search",
    "search_vault_backlinks",
    "search_vault_for_chat",
    "search_vault_notes",
    "test_vault_connection",
    "vault_plugins_enabled",
]


def search(
    owner: str,
    query: str = "",
    *,
    folder: str = "",
    limit: int = 15,
    use_semantic: bool = True,
    use_plugins: Optional[bool] = None,
    expand_links: bool = True,
) -> Dict[str, Any]:
    """Search the user's vault using native filesystem backends."""
    config = resolve_vault_config(owner)
    if not config:
        return {
            "error": "Vault folder is not configured or does not exist.",
            "exit_code": 1,
        }
    return search_vault_notes(
        config,
        query=query,
        folder=folder,
        limit=limit,
        owner=owner,
        use_semantic=use_semantic,
        use_plugins=use_plugins,
        expand_links=expand_links,
    )
