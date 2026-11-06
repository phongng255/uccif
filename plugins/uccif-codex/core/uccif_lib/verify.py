"""`uccif verify-tests`: check once, cheaply, that the project's test runner works.

List mode first (it collects tests without running them): a real run only for runners without
one. One attempt, hard timeout, nothing installed (`npx --no-install`). Any failure, timeout or
sign that the tests need a database / server / network leaves the command unverified; the
result is stored in .local/verify.json and `uccif claude-md write` marks the block from it.
"""

import os
import re
import signal
import subprocess
import time

from uccif_lib import stack
from uccif_lib.paths import ensure_local, now_iso, read_json, write_json

TIMEOUT = 60
LIST_MODES = {
    "vitest": "npx --no-install vitest list",
    "jest": "npx --no-install jest --listTests",
    "playwright": "npx --no-install playwright test --list",
    "pytest": "python -m pytest --collect-only -q",
    "go test": "go test -list . ./...",
    "cargo test": "cargo test -- --list",
    "rspec": "bundle exec rspec --dry-run",
    "phpunit": "vendor/bin/phpunit --list-tests",
}
NEEDS_SERVICE = re.compile(r"ECONNREFUSED|connection refused|could not connect|ENOTFOUND|getaddrinfo|"
                           r"EAI_AGAIN|network is unreachable|database .*does not exist|no such host", re.I)


def choose(root):
    """(command, mode) for this project: the root package's runner first, list mode when the
    runner has one, else its run-all command, else the manifests' `test` command."""
    runners = sorted(stack.test_runners(root), key=lambda r: (r["dir"] != ".", r["dir"]))
    for r in runners:
        if r["name"] in LIST_MODES:
            return stack._cd(r["dir"], LIST_MODES[r["name"]]), "list"
    for r in runners:
        if r["run_all"]:
            return r["run_all"], "run"
    test = dict(stack.commands(root)).get("test")
    return (test, "run") if test else (None, None)


MISSING_DEPS = re.compile(r"No module named|ModuleNotFoundError|could not determine executable|"
                          r"command not found|not found: (vitest|jest|playwright)|Cannot find module|"
                          r"npx canceled due to missing packages|cannot find package", re.I)


def deps_missing(root, cmd, reason):
    """True when the check failed because dependencies were never installed."""
    from pathlib import Path
    root = Path(root)
    m = re.match(r"cd (\S+) && ", cmd or "")
    pkg = root / m.group(1) if m else root
    if (pkg / "package.json").exists() and not (pkg / "node_modules").is_dir() \
            and not (root / "node_modules").is_dir():
        return True
    return bool(MISSING_DEPS.search(reason or ""))


def run(cmd, cwd, timeout=TIMEOUT):
    """(ok, reason). Never raises; the whole process group dies at the timeout."""
    kw = {"cwd": str(cwd), "shell": True, "stdin": subprocess.DEVNULL, "stdout": subprocess.PIPE,
          "stderr": subprocess.STDOUT, "env": dict(os.environ, CI="1")}
    if os.name != "nt":
        kw["start_new_session"] = True
    try:
        p = subprocess.Popen(cmd, **kw)
    except OSError as e:
        return False, "cannot start: %s" % e
    try:
        out, _ = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            if os.name != "nt":
                os.killpg(p.pid, signal.SIGKILL)
            else:
                p.kill()
        except OSError:
            pass
        p.communicate()
        return False, "timeout after %ds" % timeout
    text = (out or b"").decode("utf-8", "replace")
    if NEEDS_SERVICE.search(text):
        return False, "needs a database/server/network"
    if p.returncode != 0:
        hit = MISSING_DEPS.search(text)
        last = [l for l in text.strip().splitlines() if l.strip()][-1:] or [""]
        return False, "exit %d: %s" % (p.returncode, (hit.group(0) if hit else last[0])[:160])
    return True, "ok"


def verify(project, timeout=TIMEOUT):
    cmd, mode = choose(project.root)
    if not cmd:
        res = {"ok": False, "reason": "no test command found", "cmd": None, "mode": None}
    else:
        t0 = time.time()
        ok, reason = run(cmd, project.root, timeout)
        res = {"ok": ok, "reason": reason, "cmd": cmd, "mode": mode, "s": round(time.time() - t0, 1),
               "deps_missing": (not ok) and deps_missing(project.root, cmd, reason)}
    res["at"] = now_iso()
    ensure_local(project)
    write_json(project.local_dir / "verify.json", {"test": res})
    return res


def test_label(project, verified_flag=False):
    """Suffix for the test command in the CLAUDE.md block: "" when verified."""
    res = (read_json(project.local_dir / "verify.json", {}) or {}).get("test") or {}
    if verified_flag or res.get("ok"):
        return ""
    return " (deps not installed)" if res.get("deps_missing") else " (unverified)"


def verified(project):
    """Purposes (e.g. {"test"}) the last `uccif verify-tests` confirmed."""
    data = read_json(project.local_dir / "verify.json", {}) or {}
    return {k for k, v in data.items() if isinstance(v, dict) and v.get("ok")}
