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
    assert not any("summary.md" in l and l.startswith("WARN") for l in lines)  # init is optional
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
    from uccif_lib import __version__
    assert r.returncode == 0 and r.stdout.startswith("uccif %s " % __version__)


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


def _claude_md(monkeypatch, project, text, *argv):
    import io
    from uccif_lib import cli
    monkeypatch.setattr("sys.stdin", io.StringIO(text))
    return cli.main(["claude-md", "write", *argv])


def test_claude_md_block_is_composed_small_and_appended_last(project, repo, monkeypatch, capsys):
    make_web_app(repo)
    md = repo / "CLAUDE.md"
    md.write_text("# Mine\n" + "my own rule\n" * 400)  # a big existing file: never touched
    before = md.read_text()
    assert _claude_md(monkeypatch, project, "A Vue shop.\nTalks to Stripe.") == 0
    text = md.read_text()
    assert text.startswith(before.rstrip("\n"))
    block = text[text.index("<!-- UCCIF:BEGIN -->"):]
    assert len(block.splitlines()) <= 15 and block.rstrip().endswith("<!-- UCCIF:END -->")
    assert "A Vue shop." in block and "build `npm run build`" in block and "test `npm test`" in block
    assert _claude_md(monkeypatch, project, "x") == 3  # existing block: refuses without --replace
    assert _claude_md(monkeypatch, project, "Changed.", "--replace") == 0
    assert md.read_text().startswith(before.rstrip("\n")) and "Changed." in md.read_text()


def test_claude_md_block_over_15_lines_is_refused(project, repo, monkeypatch):
    block = "<!-- UCCIF:BEGIN -->\n" + "line\n" * 20 + "<!-- UCCIF:END -->"
    assert _claude_md(monkeypatch, project, block) == 1
    assert not (repo / "CLAUDE.md").exists()


def test_doctor_warns_on_codegraph_installer_duplicates(project, repo, tmp_path):
    home = Path(os.environ["HOME"])
    (home / ".claude").mkdir(parents=True, exist_ok=True)
    md = home / ".claude" / "CLAUDE.md"
    md.write_text("mine\n<!-- CODEGRAPH_START -->\nuse codegraph\n<!-- CODEGRAPH_END -->\n")
    before = md.read_text()
    _, lines = detect.doctor(project)
    assert any(l.startswith("WARN") and "CODEGRAPH" not in l and "instructions block" in l for l in lines)
    assert md.read_text() == before  # never edited


def test_summary_write_caps_lines_and_stores_baseline(project, repo, monkeypatch):
    import io
    from uccif_lib import cli, drift
    monkeypatch.setattr("sys.stdin", io.StringIO("x\n" * 21))
    assert cli.main(["summary", "write"]) == 1
    monkeypatch.setattr("sys.stdin", io.StringIO("Shop for bikes [src: README.md]\n"))
    assert cli.main(["summary", "write"]) == 0
    assert (project.docs_dir / "summary.md").read_text().startswith("Shop for bikes")
    assert drift.pending(project) == []
    monkeypatch.setattr("sys.stdin", io.StringIO("again\n"))
    assert cli.main(["summary", "write"]) == 3


def test_claude_md_symlink_is_kept(project, repo, monkeypatch):
    if os.name == "nt":
        return
    (repo / "AGENTS.md").write_text("# agents\n")
    os.symlink("AGENTS.md", str(repo / "CLAUDE.md"))
    assert _claude_md(monkeypatch, project, "A lib.") == 0
    assert (repo / "CLAUDE.md").is_symlink() and "UCCIF:BEGIN" in (repo / "AGENTS.md").read_text()


import pytest as _pytest


@_pytest.mark.parametrize("pkg,lock,pm", [
    ({"packageManager": "yarn@4.1.0"}, "pnpm-lock.yaml", "yarn"),  # the declaration wins over the lockfile
    ({"packageManager": "nub@0.8.3"}, None, "nub"),
    ({}, "pnpm-lock.yaml", "pnpm"),
    ({}, "yarn.lock", "yarn"),
    ({}, "bun.lockb", "bun"),
    ({}, "package-lock.json", "npm"),
    ({}, None, "npm"),
])
def test_package_manager_detection(repo, pkg, lock, pm):
    from uccif_lib import stack
    (repo / "package.json").write_text(json.dumps(dict(pkg, scripts={"test": "vitest", "build": "vite build"})))
    if lock:
        (repo / lock).write_text("")
    cmds = dict(stack.commands(repo))
    assert cmds["test"] == "%s test" % pm and cmds["build"] == "%s run build" % pm


def test_claude_md_verified_flag_and_no_labels_on_other_commands(project, repo, monkeypatch):
    make_web_app(repo)
    assert _claude_md(monkeypatch, project, "A shop.", "--verified", "test") == 0
    text = (repo / "CLAUDE.md").read_text()
    assert "test `npm test`" in text and "test `npm test` (unverified)" not in text
    assert "build `npm run build`" in text and "(unverified)" not in text
