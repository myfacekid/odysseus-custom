"""Tests for vault wikilink graph."""

from src.obsidian_vault import VaultConfig
from src.vault_graph import VaultGraph


def test_wikilink_backlinks(tmp_path):
    (tmp_path / "A.md").write_text("Link to [[B]]", encoding="utf-8")
    (tmp_path / "B.md").write_text("Back to [[A]]", encoding="utf-8")
    cfg = VaultConfig(vault_path=str(tmp_path))
    graph = VaultGraph(cfg)
    assert graph.resolve_link("B", "A.md") == "B.md"
    assert "A.md" in graph.backlinks("B.md")
    assert "B.md" in graph.outgoing("A.md")
