import os
import shutil
import threading

import pytest

from conftest import git
from uccif_lib import paths


def test_project_root_is_git_toplevel(repo, monkeypatch):
    sub = repo / "src" / "deep"
    sub.mkdir(parents=True)
    monkeypatch.chdir(sub)
    assert paths.project_root() == repo


def test_claude_project_dir_wins(repo, tmp_path, monkeypatch):
    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(other))
    assert paths.project_root() == other.resolve()


def test_data_root_precedence(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path / "plugin"))
    assert paths.data_root() == tmp_path / "data"  # UCCIF_DATA_DIR from fixture wins
    monkeypatch.delenv("UCCIF_DATA_DIR")
    assert paths.data_root() == tmp_path / "plugin"


def test_meta_records_path_and_root_commit(project, repo):
    meta = paths.read_json(project.data_dir / "meta.json")
    assert meta["path"] == str(repo)
    assert meta["root_commit"] and len(meta["root_commit"]) == 40
    assert project.docs_dir == repo / ".claude" / "uccif"


def test_renamed_repo_moves_its_data(project, repo, tmp_path, monkeypatch):
    (project.data_dir / "marker").write_text("x")
    moved = tmp_path / "moved"
    monkeypatch.chdir(tmp_path)  # Windows cannot rename the process's current directory
    shutil.move(str(repo), str(moved))
    monkeypatch.chdir(moved)
    p2 = paths.resolve_project()
    assert p2.renamed_from == str(repo)
    assert (p2.data_dir / "marker").exists()
    assert not project.data_dir.exists()


def test_live_clone_gets_its_own_data(project, repo, tmp_path, monkeypatch):
    (project.data_dir / "marker").write_text("x")
    clone = tmp_path / "clone"
    git(tmp_path, "clone", "-q", str(repo), str(clone))
    monkeypatch.chdir(clone)
    p2 = paths.resolve_project()
    assert p2.root_commit == project.root_commit
    assert p2.data_dir != project.data_dir
    assert p2.renamed_from is None
    assert not (p2.data_dir / "marker").exists()


def test_non_git_dir_works(tmp_path, monkeypatch):
    d = tmp_path / "plain"
    d.mkdir()
    monkeypatch.chdir(d)
    p = paths.resolve_project()
    assert p.root == d.resolve() and p.root_commit is None
    assert p.data_dir.is_dir()


def test_fallback_data_dir_ignores_sibling_plugins(tmp_path, monkeypatch):
    monkeypatch.delenv("UCCIF_DATA_DIR")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    base = tmp_path / ".claude" / "plugins" / "data"
    core = base / "uccif-mymarket"
    sibling = base / "uccif-strict-uccif"
    for d in (core, sibling):
        (d / "projects").mkdir(parents=True)
    (core / paths.CORE_MARKER).write_text("{}")
    os.utime(str(core), (1, 1))  # the sibling is the most recently used dir
    assert paths.data_root_source() == (core, "fallback-marker")
    exact = base / paths.CORE_DATA_NAME
    exact.mkdir()
    (exact / paths.CORE_MARKER).write_text("{}")
    assert paths.data_root_source() == (exact, "fallback-exact")


def test_root_commit_is_cached_after_first_resolve(project, repo, monkeypatch):
    calls = []
    real = paths.root_commit
    monkeypatch.setattr(paths, "root_commit", lambda root: calls.append(root) or real(root))
    again = paths.resolve_project()
    assert again.root_commit == project.root_commit
    assert calls == []


def test_write_text_atomic_survives_concurrent_writers(tmp_path):
    # two sessions starting together used to share one temp file and crash SessionStart
    state = tmp_path / "state"
    target = state / "hosts.json"
    errors = []

    def writer(n):
        for _ in range(100):
            try:
                paths.write_text_atomic(target, "writer %d\n" % n)
            except OSError as e:
                errors.append(e)

    threads = [threading.Thread(target=writer, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert target.read_text(encoding="utf-8").startswith("writer ")
    assert [p.name for p in state.iterdir()] == ["hosts.json"]


def test_write_text_atomic_retries_a_denied_replace(tmp_path, monkeypatch):
    target = tmp_path / "hosts.json"
    real, denied = os.replace, [PermissionError(13, "Access is denied")] * 2

    def flaky(src, dst):
        if denied:
            raise denied.pop()
        real(src, dst)

    monkeypatch.setattr(paths.os, "replace", flaky)
    paths.write_text_atomic(target, "ok\n")
    assert not denied
    assert target.read_text(encoding="utf-8") == "ok\n"


def test_write_text_atomic_gives_up_on_a_lasting_denial(tmp_path, monkeypatch):
    def denied(src, dst):
        raise PermissionError(13, "Access is denied")

    monkeypatch.setattr(paths.os, "replace", denied)
    monkeypatch.setattr(paths, "REPLACE_RETRY_SECONDS", 0.02)
    with pytest.raises(PermissionError):
        paths.write_text_atomic(tmp_path / "state" / "hosts.json", "x")
    assert list((tmp_path / "state").iterdir()) == []
