import json
import os
import subprocess

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
    assert set(d["lsp"]) == {"typescript", "vue"}


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


def run_cli(*args, cwd, stdin=None):
    return subprocess.run([str(LAUNCHER)] + list(args), cwd=str(cwd), input=stdin,
                          capture_output=True, text=True, env=dict(os.environ))


def test_launcher_is_executable_and_runs(repo):
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
