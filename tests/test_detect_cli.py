import json
import os
import shutil
import subprocess
from pathlib import Path

from conftest import PLUGIN, git
from uccif_lib import detect

LAUNCHER = PLUGIN / "bin" / "uccif"


def make_web_app(repo):
    (repo / "src").mkdir()
    (repo / "test").mkdir()
    (repo / "node_modules" / "x").mkdir(parents=True)
    (repo / "package.json").write_text(json.dumps({
        "scripts": {"test": "vitest", "build": "vite build"},
        "dependencies": {"vue": "3"}, "devDependencies": {"vitest": "1"}}))
    (repo / "src" / "main.ts").write_text("x")
    (repo / "src" / "App.vue").write_text("x")
    (repo / "test" / "app.spec.ts").write_text("x")
    (repo / "node_modules" / "x" / "index.js").write_text("x")
    (repo / ".gitignore").write_text("node_modules/\n")
    git(repo, "add", "-A")


def test_detect_web_app(project, repo):
    make_web_app(repo)
    d = detect.detect(project)
    assert d["languages"] == {"typescript": 2, "vue": 1}
    assert d["test_dirs"] == ["test"]
    assert "src/main.ts" in d["entry_candidates"] and "src/App.vue" in d["entry_candidates"]
    assert d["node"]["scripts"]["test"] == "vitest"
    assert not d["large_repo"] and d["uccif_v2"] == [] and not d["claude_md_block"]
    assert set(d["lsp"]) == {"typescript"} and d["lsp"]["typescript"]["install"].startswith("npm")
    assert d["no_lsp"] == ["vue"]  # no LSP configured: covered by CodeGraph, nothing to ask


def test_detect_finds_uccif_v2(project, repo):
    (repo / ".claude" / "scripts").mkdir(parents=True)
    (repo / ".claude" / "scripts" / "uccif.py").write_text("x")
    (repo / ".claude" / "settings.json").write_text('{"hooks": "python3 .claude/scripts/uccif.py hook stop"}')
    v2 = detect.detect(project)["uccif_v2"]
    assert ".claude/scripts/uccif.py" in v2 and any("settings.json" in x for x in v2)


def test_doctor_warns_on_fresh_project(project):
    ok, lines = detect.doctor(project)
    assert ok is False
    assert any("session-start never ran" in l for l in lines)
    assert any("no .claude/uccif/summary.md" in l for l in lines)
    assert any("not indexed by CodeGraph" in l for l in lines)


def test_codegraph_state_reports_where_the_mcp_server_comes_from(project, repo, monkeypatch, tmp_path):
    from uccif_lib import codegraph
    home = tmp_path / "h"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setattr(codegraph, "plugin_mcp", lambda: False)
    assert codegraph.state(project)["mcp"] is False and codegraph.state(project)["mcp_via"] is None
    (home / ".claude.json").write_text('{"mcpServers": {"codegraph": {"command": "codegraph"}}}')
    assert codegraph.state(project)["mcp_via"] == "config"
    monkeypatch.setattr(codegraph, "plugin_mcp", lambda: True)
    st = codegraph.state(project)
    assert st["mcp"] is True and st["mcp_via"] == "plugin"
    ok, lines = detect.doctor(project)
    assert any("MCP server provided by the plugin" in l for l in lines)


def test_detect_reports_codegraph_state(project, repo):
    (repo / ".codegraph").mkdir()
    (repo / ".gitignore").write_text(".codegraph/\n")
    cg = detect.detect(project)["codegraph"]
    assert cg["indexed"] is True and cg["gitignored"] is True


def git_bash():
    """Git for Windows' bash, which Claude Code uses for hooks. A bare `bash` on Windows
    can resolve to WSL's launcher (C:\\Windows\\System32\\bash.exe) instead."""
    git = shutil.which("git")
    roots = [Path(git).resolve().parents[1]] if git else []
    roots.append(Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git")
    for root in roots:
        for cand in (root / "bin" / "bash.exe", root.parent / "bin" / "bash.exe"):
            if cand.is_file():
                return str(cand)
    raise RuntimeError("Git Bash not found")


def run_cli(*args, cwd, stdin=None):
    # On Windows the launcher is a sh script run by Git Bash, as Claude Code does.
    cmd = ([git_bash(), LAUNCHER.as_posix()] if os.name == "nt" else [str(LAUNCHER)]) + list(args)
    return subprocess.run(cmd, cwd=str(cwd), input=stdin, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=dict(os.environ))


def test_launcher_is_executable_and_runs(repo):
    if os.name != "nt":
        assert os.access(str(LAUNCHER), os.X_OK)
    r = run_cli("version", cwd=repo)
    assert r.returncode == 0 and r.stdout.startswith("uccif 3.")


def test_cli_task_exit_codes(repo):
    assert run_cli("task", "start", "a", "--type", "ui", cwd=repo).returncode == 0
    assert run_cli("task", "start", "b", "--type", "ui", cwd=repo).returncode == 1
    assert run_cli("task", "close", cwd=repo).returncode == 1
    assert run_cli("task", "close", "--no-findings", cwd=repo).returncode == 0
    assert run_cli("task", "start", "c", "--type", "nope", cwd=repo).returncode == 2


def test_cli_hook_always_exit_0(repo):
    for stdin in ("", "garbage", "{}"):
        assert run_cli("hook", "stop", cwd=repo, stdin=stdin).returncode == 0
    assert run_cli("hook", "no-such-event", cwd=repo, stdin="{}").returncode == 0


def test_hook_output_survives_a_non_utf8_console(repo):
    """Windows consoles default to a legacy code page; the token line has an emoji."""
    env = dict(os.environ, PYTHONIOENCODING="cp1252")
    cmd = ([git_bash(), LAUNCHER.as_posix()] if os.name == "nt" else [str(LAUNCHER)]) + ["hook", "stop"]
    r = subprocess.run(cmd, cwd=str(repo), input=b"{}", capture_output=True, env=env)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout.decode("ascii"))["systemMessage"].startswith("\U0001f522")
