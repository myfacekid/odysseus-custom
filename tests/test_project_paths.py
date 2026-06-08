"""Phase 0 — project path containment and workspace records."""

import os
from pathlib import Path

import pytest

from src.project_paths import (
    WORKING_DIR_INVALID,
    WORKING_DIR_MISSING,
    WORKING_DIR_OK,
    ProjectPathError,
    find_dirs_named_under_root,
    is_path_under_root,
    resolve_path_under_root,
    resolve_project_path,
    validate_working_dir,
)
from src.project_workspace import (
    ProjectAccessError,
    ProjectNotFoundError,
    assert_project_owner,
    create_project,
    get_project,
    resolve_owned_project_path,
)


def test_validate_working_dir_ok(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    canonical, status = validate_working_dir(str(root))
    assert status == WORKING_DIR_OK
    assert canonical == str(root.resolve())


def test_validate_working_dir_missing(tmp_path):
    missing = tmp_path / "gone"
    _, status = validate_working_dir(str(missing))
    assert status == WORKING_DIR_MISSING


def test_validate_working_dir_invalid_file(tmp_path):
    file_path = tmp_path / "not-a-dir.txt"
    file_path.write_text("x", encoding="utf-8")
    _, status = validate_working_dir(str(file_path))
    assert status == WORKING_DIR_INVALID


def test_validate_working_dir_empty():
    _, status = validate_working_dir("")
    assert status == WORKING_DIR_INVALID


def test_resolve_relative_path_under_root(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    script = root / "analysis.py"
    script.write_text("print('ok')\n", encoding="utf-8")

    resolved = resolve_path_under_root(str(root), "analysis.py", must_exist=True)
    assert resolved == script.resolve()


def test_resolve_nested_relative_path(tmp_path):
    root = tmp_path / "root"
    nested = root / "src"
    nested.mkdir(parents=True)
    target = nested / "run.py"
    target.write_text("pass\n", encoding="utf-8")

    resolved = resolve_path_under_root(str(root), "src/run.py", must_exist=True)
    assert resolved == target.resolve()


def test_reject_parent_traversal(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    with pytest.raises(ProjectPathError, match="outside project"):
        resolve_path_under_root(str(root), "../outside.txt")


def test_reject_absolute_path_outside_root(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("secret", encoding="utf-8")

    with pytest.raises(ProjectPathError, match="outside project"):
        resolve_path_under_root(str(root), str(outside))


def test_reject_symlink_escape(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("secret", encoding="utf-8")
    link = root / "escape"
    link.symlink_to(outside)

    with pytest.raises(ProjectPathError, match="outside project"):
        resolve_path_under_root(str(root), "escape", must_exist=True)


def test_allow_symlink_inside_root(tmp_path):
    root = tmp_path / "root"
    inner = root / "inner"
    inner.mkdir(parents=True)
    real = inner / "data.csv"
    real.write_text("a,b\n", encoding="utf-8")
    link = root / "link.csv"
    link.symlink_to(real)

    resolved = resolve_path_under_root(str(root), "link.csv", must_exist=True)
    assert resolved == real.resolve()


def test_must_exist_requires_present_file(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    with pytest.raises(ProjectPathError, match="not found"):
        resolve_path_under_root(str(root), "missing.py", must_exist=True)


def test_resolve_project_path_wrapper(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    script = root / "main.py"
    script.write_text("pass\n", encoding="utf-8")
    resolved = resolve_project_path(str(root), "main.py", must_exist=True)
    assert resolved == script.resolve()


def test_is_path_under_root():
    assert is_path_under_root("/tmp/a/b", "/tmp/a")
    assert not is_path_under_root("/tmp/b", "/tmp/a")


def test_create_project_and_resolve_owned_path(tmp_path, monkeypatch):
    monkeypatch.setattr("src.project_workspace.PROJECTS_ROOT", tmp_path / "projects")
    root = tmp_path / "workspace"
    root.mkdir()
    script = root / "pipeline.py"
    script.write_text("print('run')\n", encoding="utf-8")

    project = create_project(
        "alice",
        title="Test project",
        working_dir=str(root),
        project_id="proj-test-1",
    )
    assert project["working_dir_status"] == WORKING_DIR_OK
    assert get_project("alice", "proj-test-1")["title"] == "Test project"

    resolved = resolve_owned_project_path("alice", "proj-test-1", "pipeline.py", must_exist=True)
    assert resolved == script.resolve()


def test_resolve_owned_project_path_rejects_traversal(tmp_path, monkeypatch):
    monkeypatch.setattr("src.project_workspace.PROJECTS_ROOT", tmp_path / "projects")
    root = tmp_path / "workspace"
    root.mkdir()
    create_project("alice", title="Safe", working_dir=str(root), project_id="proj-safe")

    with pytest.raises(ProjectPathError):
        resolve_owned_project_path("alice", "proj-safe", "../../etc/passwd")


def test_assert_project_owner_cross_owner(tmp_path, monkeypatch):
    monkeypatch.setattr("src.project_workspace.PROJECTS_ROOT", tmp_path / "projects")
    root = tmp_path / "workspace"
    root.mkdir()
    create_project("bob", title="Bob project", working_dir=str(root), project_id="shared-id")

    with pytest.raises(ProjectAccessError):
        assert_project_owner("alice", "shared-id")


def test_assert_project_owner_missing(tmp_path, monkeypatch):
    monkeypatch.setattr("src.project_workspace.PROJECTS_ROOT", tmp_path / "projects")
    with pytest.raises(ProjectNotFoundError):
        assert_project_owner("alice", "missing-id")


def test_resolve_owned_project_path_missing_root(tmp_path, monkeypatch):
    monkeypatch.setattr("src.project_workspace.PROJECTS_ROOT", tmp_path / "projects")
    root = tmp_path / "workspace"
    root.mkdir()
    project = create_project(
        "alice",
        title="Broken later",
        working_dir=str(root),
        project_id="proj-break",
    )
    assert project["working_dir_status"] == WORKING_DIR_OK

    root.rmdir()
    with pytest.raises(ProjectPathError, match="missing"):
        resolve_owned_project_path("alice", "proj-break", "file.py")


def test_find_dirs_named_under_root(tmp_path):
    root = tmp_path / "home"
    nested = root / "Documents" / "experiments" / "alpha"
    nested.mkdir(parents=True)
    (root / "Downloads" / "alpha").mkdir(parents=True)

    matches = find_dirs_named_under_root(str(root), "alpha")
    assert len(matches) == 2
    assert str(nested.resolve()) in matches
