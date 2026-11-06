"""Project skills generated from a CodeGraph index, stack detection, background bootstrap.

A real CodeGraph is never run: tests build a minimal `.codegraph/codegraph.db` with the
tables and columns skillgen reads (files, nodes, edges)."""

import json
import os
import sqlite3
import stat
import sys

import pytest

from conftest import git, run_hook
from uccif_lib import codegraph, skillgen, stack

FILES = {
    "src/api/routes.py": "python", "src/api/deps.py": "python", "src/api/auth.py": "python",
    "src/core/db.py": "python", "src/core/config.py": "python", "src/core/security.py": "python",
    "src/utils/fmt.py": "python", "src/main.py": "python", "tests/test_routes.py": "python",
    "web/src/App.tsx": "tsx", "web/src/api.ts": "typescript", "web/src/Button.tsx": "tsx",
    ".github/scripts/release.py": "python", "docker-compose.yml": "yaml",
}


def make_db(root, extra_edges=()):
    d = root / ".codegraph"
    d.mkdir(exist_ok=True)
    if (d / "codegraph.db").exists():
        (d / "codegraph.db").unlink()
    con = sqlite3.connect(str(d / "codegraph.db"))
    con.executescript("""
        CREATE TABLE files (path TEXT PRIMARY KEY, content_hash TEXT, language TEXT, size INTEGER,
                            modified_at INTEGER, indexed_at INTEGER, node_count INTEGER);
        CREATE TABLE nodes (id TEXT PRIMARY KEY, kind TEXT, name TEXT, qualified_name TEXT, file_path TEXT,
                            language TEXT, start_line INTEGER, end_line INTEGER);
        CREATE TABLE edges (id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT, target TEXT, kind TEXT,
                            metadata TEXT, line INTEGER);
    """)
    for p, lang in FILES.items():
        con.execute("INSERT INTO files VALUES (?,?,?,?,?,?,?)", (p, "h", lang, 10, 0, 0, 2))
        con.execute("INSERT INTO nodes VALUES (?,?,?,?,?,?,?,?)", ("file:" + p, "file", p, p, p, lang, 1, 1))
    syms = [("get_db", "function", "src/core/db.py", 10), ("Settings", "class", "src/core/config.py", 3),
            ("current_user", "function", "src/api/deps.py", 7), ("fmt", "function", "src/utils/fmt.py", 1),
            ("Button", "function", "web/src/Button.tsx", 4)]
    for name, kind, path, line in syms:
        con.execute("INSERT INTO nodes VALUES (?,?,?,?,?,?,?,?)",
                    ("%s:%s" % (kind, name), kind, name, name, path, "python", line, line + 5))
    con.execute("INSERT INTO nodes VALUES ('route:1','route','GET /items','GET /items','src/api/routes.py',"
                "'python',12,12)")
    uses = [("src/api/routes.py", "function:get_db"), ("src/api/deps.py", "function:get_db"),
            ("src/api/auth.py", "function:get_db"), ("src/api/routes.py", "function:current_user"),
            ("src/api/auth.py", "class:Settings"), ("src/core/db.py", "class:Settings"),
            ("tests/test_routes.py", "function:current_user"), ("web/src/App.tsx", "function:Button"),
            ("src/main.py", "function:fmt")] + list(extra_edges)
    for src, dst in uses:
        con.execute("INSERT INTO edges (source, target, kind, line) VALUES (?,?,?,1)", ("file:" + src, dst, "calls"))
    con.commit()
    con.close()


@pytest.fixture
def app(repo):
    for p in FILES:
        (repo / p).parent.mkdir(parents=True, exist_ok=True)
        (repo / p).write_text("x = 1\n")
    (repo / "pyproject.toml").write_text('[project]\ndependencies = ["fastapi"]\n[tool.x]\ndev = ["pytest>=7"]\n')
    (repo / "web" / "package.json").write_text(json.dumps({"scripts": {"dev": "vite", "test": "vitest"},
                                                           "devDependencies": {"vitest": "1"}}))
    make_db(repo)
    git(repo, "add", "-A")
    return repo


def test_choose_modules_opens_containers_and_big_dirs():
    paths = ["src/a/%d.py" % i for i in range(5)] + ["src/b/x.py", "src/b/y.py", "lib.py"]
    dirs = {m["dir"] for m in skillgen.choose_modules(paths)}
    assert dirs == {"src/a", "src/b", "."}


def test_generate_writes_map_bugfix_and_module_skills(project, app):
    res = skillgen.generate(project)
    slug = skillgen.slugify(app.name, 30)
    names = set(res["written"])
    assert {"%s-map" % slug, "%s-bugfix" % slug, "%s-mod-api" % slug, "%s-mod-core" % slug} <= names
    assert not any("github" in n for n in names)  # dot-dirs are not code modules
    text = (app / (".claude/skills/%s-map/SKILL.md" % slug)).read_text(encoding="utf-8")
    assert text.startswith("---\nname: %s-map\ndescription: \"" % slug)
    assert "| `src/api` | 3 | HTTP/API layer | %s-mod-api |" % slug in text
    assert "`GET /items` — src/api/routes.py:12" in text
    assert "`get_db` function — src/core/db.py:10 (3 uses)" in text
    assert "- `src/main.py`" in text  # entry point: nothing imports it
    assert "yaml" not in text.split("\n## Modules")[0]
    bug = (app / (".claude/skills/%s-bugfix/SKILL.md" % slug)).read_text(encoding="utf-8")
    assert "core rule 2" in bug and "uccif task start" not in bug
    assert "python -m pytest -q {file}" in bug and "cd web && npx vitest run {file}" in bug
    api = (app / (".claude/skills/%s-mod-api/SKILL.md" % slug)).read_text(encoding="utf-8")
    assert "- `tests/test_routes.py`" in api and "run one: `python -m pytest -q tests/test_routes.py`" in api
    assert "depends on: `src/core`" in api
    assert skillgen.generate(project)["written"] == []  # second run: nothing changes


def test_codex_project_skills_use_shared_agents_directory(project, app):
    from uccif_lib import codex_setup
    codex_setup.run(project)
    result = skillgen.generate(project, hosts_=["codex"])
    assert result["dirs"] == [".agents/skills"]
    name = "%s-map" % skillgen.slugify(app.name, 30)
    assert (app / ".agents/skills" / name / "SKILL.md").is_file()
    codex_setup.run(project, remove_=True)
    # Generated code maps are shared data, not owned setup workflow files.
    assert (app / ".agents/skills" / name / "SKILL.md").is_file()


def test_regeneration_keeps_notes_and_respects_user_files(project, app):
    slug = skillgen.slugify(app.name, 30)
    skillgen.generate(project)
    core = app / (".claude/skills/%s-mod-core/SKILL.md" % slug)
    core.write_text(core.read_text(encoding="utf-8").replace("<!-- uccif:notes -->\n", "<!-- uccif:notes -->\nDB is Postgres.\n"), encoding="utf-8")
    mine = app / (".claude/skills/%s-bugfix/SKILL.md" % slug)
    mine.write_text(mine.read_text(encoding="utf-8").replace("shortest path", "my way"), encoding="utf-8")
    own = app / (".claude/skills/%s-map/SKILL.md" % slug)
    own.write_text("---\nname: x\ndescription: mine\n---\nhand written\n", encoding="utf-8")
    make_db(app, extra_edges=[("src/utils/fmt.py", "class:Settings")])  # graph changed
    res = skillgen.generate(project)
    assert "DB is Postgres." in core.read_text(encoding="utf-8")
    assert own.read_text(encoding="utf-8").endswith("hand written\n")
    skipped = dict(res["skipped"])
    assert "no UCCIF marker" in skipped["%s-map" % slug] and "--force" in skipped["%s-bugfix" % slug]
    assert "my way" in mine.read_text(encoding="utf-8")
    skillgen.generate(project, force=True)
    assert "my way" not in mine.read_text(encoding="utf-8") and own.read_text(encoding="utf-8").endswith("hand written\n")


def test_module_skill_removed_when_module_disappears(project, app):
    slug = skillgen.slugify(app.name, 30)
    skillgen.generate(project)
    con = sqlite3.connect(str(app / ".codegraph/codegraph.db"))
    con.execute("DELETE FROM files WHERE path LIKE 'src/core/%'")
    con.commit()
    con.close()
    res = skillgen.generate(project)
    assert "%s-mod-core" % slug in res["removed"]
    assert not (app / (".claude/skills/%s-mod-core" % slug)).exists()


def test_generate_without_index_raises(project):
    with pytest.raises(skillgen.NoIndex):
        skillgen.generate(project)


def test_stack_runners_in_sub_packages(tmp_path):
    (tmp_path / "backend").mkdir()
    (tmp_path / "backend" / "pyproject.toml").write_text('dev = ["pytest"]\n')
    (tmp_path / "go.mod").write_text("module x\n")
    (tmp_path / "Makefile").write_text("test:\n\tgo test ./...\nlint:\n\tgolangci-lint run\n")
    runners = stack.test_runners(tmp_path)
    assert [(r["name"], r["dir"]) for r in runners] == [("go test", "."), ("pytest", "backend")]
    assert stack.run_one(runners, "backend/tests/test_a.py") == "cd backend && python -m pytest -q tests/test_a.py"
    assert stack.run_one(runners, "pkg/store/store_test.go") == "go test ./pkg/store/..."
    cmds = dict((c, p) for p, c in stack.commands(tmp_path))
    assert "make test" in cmds and "make lint" in cmds and "go build ./..." in cmds
    assert "cd backend && python -m pytest -q" in cmds


def fake_cli(tmp_path, ok=True):
    """A `codegraph` executable that builds the fake index (or fails)."""
    script = tmp_path / "fakecg.py"
    # Execute make_db without importing test_skillgen so child subprocess doesn't import pytest
    code = f'''import sys, os, sqlite3, json
from pathlib import Path
if not {ok}:
    sys.exit(3)
FILES = {repr(FILES)}
root = Path.cwd()
d = root / ".codegraph"
d.mkdir(exist_ok=True)
if (d / "codegraph.db").exists():
    (d / "codegraph.db").unlink()
con = sqlite3.connect(str(d / "codegraph.db"))
con.executescript("""
    CREATE TABLE files (path TEXT PRIMARY KEY, content_hash TEXT, language TEXT, size INTEGER,
                        modified_at INTEGER, indexed_at INTEGER, node_count INTEGER);
    CREATE TABLE nodes (id TEXT PRIMARY KEY, kind TEXT, name TEXT, qualified_name TEXT, file_path TEXT,
                        language TEXT, start_line INTEGER, end_line INTEGER);
    CREATE TABLE edges (id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT, target TEXT, kind TEXT,
                        metadata TEXT, line INTEGER);
""")
for p, lang in FILES.items():
    con.execute("INSERT INTO files VALUES (?,?,?,?,?,?,?)", (p, "h", lang, 10, 0, 0, 2))
    con.execute("INSERT INTO nodes VALUES (?,?,?,?,?,?,?,?)", ("file:" + p, "file", p, p, p, lang, 1, 1))
syms = [("get_db", "function", "src/core/db.py", 10), ("Settings", "class", "src/core/config.py", 3),
        ("current_user", "function", "src/api/deps.py", 7), ("fmt", "function", "src/utils/fmt.py", 1),
        ("Button", "function", "web/src/Button.tsx", 4)]
for name, kind, path, line in syms:
    con.execute("INSERT INTO nodes VALUES (?,?,?,?,?,?,?,?)",
                ("%s:%s" % (kind, name), kind, name, name, path, "python", line, line + 5))
con.execute("INSERT INTO nodes VALUES ('route:1','route','GET /items','GET /items','src/api/routes.py',"
            "'python',12,12)")
uses = [("src/api/routes.py", "function:get_db"), ("src/api/deps.py", "function:get_db"),
        ("src/api/auth.py", "function:get_db"), ("src/api/routes.py", "function:current_user"),
        ("src/api/auth.py", "class:Settings"), ("src/core/db.py", "class:Settings"),
        ("tests/test_routes.py", "function:current_user"), ("web/src/App.tsx", "function:Button"),
        ("src/main.py", "function:fmt")]
for src, dst in uses:
    con.execute("INSERT INTO edges (source, target, kind, line) VALUES (?,?,?,1)", ("file:" + src, dst, "calls"))
con.commit()
con.close()
'''
    script.write_text(code, encoding="utf-8")
    if os.name == "nt":
        exe = tmp_path / "codegraph.bat"
        exe.write_text('@"%s" "%s" %%*\n' % (sys.executable, script))
    else:
        exe = tmp_path / "codegraph"
        exe.write_text('#!/bin/sh\nexec "%s" "%s" "$@"\n' % (sys.executable, script))
        exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    return str(exe)


def test_auto_init_indexes_excludes_and_backs_off(project, repo, tmp_path, monkeypatch):
    monkeypatch.setattr(codegraph, "cli", lambda: fake_cli(tmp_path))
    assert codegraph.auto_init(project) is True
    assert (repo / ".codegraph" / "codegraph.db").exists()
    assert ".codegraph/" in (repo / ".git" / "info" / "exclude").read_text(encoding="utf-8")
    assert codegraph.auto_init(project) is None  # already indexed
    import shutil
    shutil.rmtree(str(repo / ".codegraph"))
    monkeypatch.setattr(codegraph, "cli", lambda: fake_cli(tmp_path, ok=False))
    assert codegraph.auto_init(project) is False
    assert codegraph.auto_init(project) is None  # failure is not retried every turn


def test_session_start_bootstraps_and_lists_project_skills(project, app, tmp_path, monkeypatch):
    import shutil
    shutil.rmtree(str(app / ".codegraph"))
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_AUTO_SETUP", "true")
    monkeypatch.setattr(codegraph, "cli", lambda: fake_cli(tmp_path))
    base = {"session_id": "S1", "cwd": str(app)}
    run_hook("session-start", dict(base, source="startup"))  # UCCIF_SYNC=1: maintain runs inline
    slug = skillgen.slugify(app.name, 30)
    assert (app / (".claude/skills/%s-map/SKILL.md" % slug)).exists()
    _, out = run_hook("session-start", dict(base, source="startup"))
    text = out["hookSpecificOutput"]["additionalContext"]
    assert "Code map: skill `%s-map`" % slug in text and "%s-bugfix" % slug in text and "surveyed" not in text


def test_auto_setup_off_writes_nothing(project, app, tmp_path, monkeypatch):
    monkeypatch.setattr(codegraph, "cli", lambda: fake_cli(tmp_path))
    run_hook("session-start", {"session_id": "S1", "cwd": str(app), "source": "startup"})
    assert not (app / ".claude" / "skills").exists()
