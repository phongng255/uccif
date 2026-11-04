import json
import sys

import pytest

from uccif_lib import verify


def _pkg(repo, deps):
    (repo / "package.json").write_text(json.dumps({"scripts": {"test": "x"}, "devDependencies": deps}))


def test_runner_with_list_mode_is_listed_not_run(repo):
    _pkg(repo, {"vitest": "1"})
    assert verify.choose(repo) == ("npx --no-install vitest list", "list")
    (repo / "package.json").unlink()
    (repo / "requirements.txt").write_text("pytest\n")
    assert verify.choose(repo) == ("python -m pytest --collect-only -q", "list")


def test_runner_without_list_mode_runs_for_real(repo):
    _pkg(repo, {"mocha": "1"})
    cmd, mode = verify.choose(repo)
    assert mode == "run" and cmd == "npm test"
    (repo / "package.json").unlink()
    assert verify.choose(repo) == (None, None)


def test_run_ok_error_timeout_and_service(repo):
    py = '"%s" -c' % sys.executable
    assert verify.run(py + ' "print(1)"', repo) == (True, "ok")
    ok, why = verify.run(py + ' "import sys; print(\'boom\'); sys.exit(3)"', repo)
    assert not ok and why.startswith("exit 3") and "boom" in why
    ok, why = verify.run(py + ' "import time; time.sleep(30)"', repo, timeout=1)
    assert not ok and why == "timeout after 1s"
    ok, why = verify.run(py + ' "print(\'connect ECONNREFUSED 127.0.0.1:5432\')"', repo)
    assert not ok and "database/server/network" in why


@pytest.mark.parametrize("cmd,verified", [("ok", True), ("fail", False), ("slow", False)])
def test_claude_md_block_follows_the_verification(project, repo, monkeypatch, cmd, verified):
    import io
    from uccif_lib import cli
    (repo / "package.json").write_text(json.dumps({"scripts": {"test": "vitest", "build": "vite build"},
                                                   "devDependencies": {"vitest": "1"}}))
    py = '"%s" -c ' % sys.executable
    prog = {"ok": py + '"print(1)"', "fail": py + '"import sys; sys.exit(1)"',
            "slow": py + '"import time; time.sleep(30)"'}[cmd]
    monkeypatch.setattr(verify, "choose", lambda root: (prog, "list"))
    monkeypatch.setattr(verify, "TIMEOUT", 1)
    res = verify.verify(project, timeout=1)
    assert res["ok"] is verified
    monkeypatch.setattr("sys.stdin", io.StringIO("A lib."))
    assert cli.main(["claude-md", "write"]) == 0
    block = (repo / "CLAUDE.md").read_text()
    assert ("test `npm test` (unverified)" in block) is not verified
    assert "build `npm run build` (unverified)" in block  # never run: never verified
