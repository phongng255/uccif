"""CodeGraph integration (https://github.com/colbymchenry/codegraph).

UCCIF no longer builds its own code index: CodeGraph parses the project with
tree-sitter into `<project>/.codegraph/` (SQLite) and serves it to Claude through
its MCP tool `codegraph_explore` (CLI: `codegraph explore`). This module
detects its state, tells Claude what to do and, when the CLI is already installed,
indexes the project in the background (`codegraph init --yes`, project-local). It
never installs anything. The MCP server itself is declared by the plugin (`.mcp.json`:
`codegraph serve --mcp`), so nothing has to be written into the user's Claude config.

The npm package is `@colbymchenry/codegraph`. The unscoped `codegraph` package on
npm is an unrelated project with no CLI, so `npx codegraph` must never be used.
"""

import json
import os
import shutil
from pathlib import Path

PACKAGE = "@colbymchenry/codegraph"
NPX = "npx -y %s" % PACKAGE
INDEX_DIR = ".codegraph"
DOCS = "https://github.com/colbymchenry/codegraph"
MCP_TOOL = "mcp__codegraph__codegraph_explore"
PLUGIN_ROOT = Path(__file__).resolve().parents[1]


def cli():
    """Path of the installed `codegraph` CLI, or None."""
    return shutil.which("codegraph")


def indexed(project):
    return (Path(project.root) / INDEX_DIR).is_dir()


def _mcp_in(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(data, dict):
        return False
    servers = dict(data.get("mcpServers") or {})
    for proj in (data.get("projects") or {}).values():  # ~/.claude.json keeps per-project servers too
        if isinstance(proj, dict):
            servers.update(proj.get("mcpServers") or {})
    return any("codegraph" in str(k).lower() or "codegraph" in json.dumps(v).lower() for k, v in servers.items())


def plugin_mcp():
    """True when this plugin declares the CodeGraph MCP server itself (plugins/uccif/.mcp.json)."""
    return _mcp_in(PLUGIN_ROOT / ".mcp.json")


def mcp_via(project):
    """Where the CodeGraph MCP server comes from: "plugin", "config" (the user's ~/.claude.json or the
    project's .mcp.json, e.g. from `codegraph install`) or None."""
    if plugin_mcp():
        return "plugin"
    home = Path(os.path.expanduser("~"))
    if any(_mcp_in(p) for p in (home / ".claude.json", Path(project.root) / ".mcp.json")):
        return "config"
    return None


def mcp_wired(project):
    return mcp_via(project) is not None


def state(project):
    via = mcp_via(project)
    return {"cli": cli(), "indexed": indexed(project), "mcp": via is not None, "mcp_via": via}


def gitignored(project):
    if (Path(project.root) / INDEX_DIR / ".gitignore").exists():  # newer CodeGraph ignores itself
        return True
    try:
        text = (Path(project.root) / ".gitignore").read_text(encoding="utf-8")
    except OSError:
        return False
    return any(l.strip().strip("/") == INDEX_DIR for l in text.splitlines())


def context_line(project):
    """One SessionStart line for Claude: how to look code up, or how to get CodeGraph."""
    st = state(project)
    if st["indexed"] and not st["cli"]:
        return ("CodeGraph index exists (.codegraph/) but the `codegraph` CLI is not installed, so its MCP server "
                "cannot start. Use bounded Grep/Glob, and offer the user once to run the uccif:codegraph skill "
                "(installs the CLI; needs a Claude Code restart).")
    if st["indexed"] and st["mcp"]:
        return ("CodeGraph is active for this project (.codegraph/). To find or understand code, call the "
                "`codegraph_explore` MCP tool FIRST (subagents / shell: `codegraph explore \"<question>\"`); "
                "trust its source output instead of re-reading files, and use Grep/Glob only for what it cannot "
                "answer (string literals, config, non-code files).")
    if st["indexed"]:
        return ("CodeGraph index exists (.codegraph/) but its MCP server is not wired into Claude Code. Use "
                "`codegraph explore \"<question>\"` in Bash before Grep/Read, and offer the user once to run the "
                "uccif:codegraph skill (wires the MCP tool; needs a Claude Code restart).")
    if st["cli"]:
        return ("CodeGraph CLI is installed and this project is being indexed in the background "
                "(`codegraph init --yes`); until `.codegraph/` exists use `codegraph explore` once it finishes, "
                "or bounded Grep/Glob. If it never appears, run the uccif:codegraph skill.")
    return ("CodeGraph is not installed. It replaces grep/find exploration with a pre-built code graph and saves "
            "tokens. Ask the user once, in your next reply, whether to set it up; if they agree, run the "
            "uccif:codegraph skill (never `npx codegraph`: that npm name is an unrelated package).")


# ---- background bootstrap (run by `uccif maintain`, never by Claude's Bash) -------------

INIT_TIMEOUT = 1800
RETRY_AFTER = 24 * 3600


def _git_exclude(project):
    """Keep .codegraph/ out of git without touching the user's .gitignore: .git/info/exclude."""
    import subprocess
    if gitignored(project):
        return False
    try:
        out = subprocess.run(["git", "rev-parse", "--git-path", "info/exclude"], cwd=str(project.root),
                             capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return False
    if out.returncode != 0 or not out.stdout.strip():
        return False
    path = Path(out.stdout.strip())
    if not path.is_absolute():
        path = Path(project.root) / path
    try:
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        if any(l.strip().strip("/") == INDEX_DIR for l in text.splitlines()):
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(str(path), "a", encoding="utf-8") as f:
            f.write(("" if not text or text.endswith("\n") else "\n") + INDEX_DIR + "/\n")
        return True
    except OSError:
        return False


def auto_init(project):
    """Index the project when the CLI exists and no index does yet. Project-local only (the
    global MCP wiring stays a user decision, through the uccif:codegraph skill). One run at a
    time (lock); a failure is retried after a day, not on every turn."""
    import subprocess
    import time
    from uccif_lib.paths import LockTimeout, ensure_local, file_lock, now_iso, read_json, write_json
    root = Path(project.root)
    if indexed(project):
        _git_exclude(project)
        return None
    exe = cli()
    if not exe or root == Path(os.path.expanduser("~")) or not (root / ".git").exists():
        return None
    ensure_local(project)
    state_path = project.local_dir / "codegraph.json"
    state = read_json(state_path, {}) or {}
    if state.get("failed_at") and time.time() - state["failed_at"] < RETRY_AFTER:
        return None
    try:
        with file_lock(project.local_dir / "codegraph-init.lock", timeout=0, stale=INIT_TIMEOUT):
            env = dict(os.environ, CODEGRAPH_TELEMETRY=os.environ.get("CODEGRAPH_TELEMETRY", "0"))
            try:
                out = subprocess.run([exe, "init", "--yes"], cwd=str(root), capture_output=True, text=True,
                                     encoding="utf-8", errors="replace", timeout=INIT_TIMEOUT, env=env)
                ok, err = out.returncode == 0 and indexed(project), (out.stderr or out.stdout)[-300:]
            except (OSError, subprocess.SubprocessError) as e:
                ok, err = False, str(e)[:300]
            write_json(state_path, {"initialized_at": now_iso()} if ok else
                       {"failed_at": time.time(), "error": err})
            if ok:
                _git_exclude(project)
            return ok
    except LockTimeout:
        return None
