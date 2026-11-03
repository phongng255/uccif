"""CodeGraph integration (https://github.com/colbymchenry/codegraph).

UCCIF no longer builds its own code index: CodeGraph parses the project with
tree-sitter into `<project>/.codegraph/` (SQLite) and serves it to Claude through
its MCP tool `codegraph_explore` (CLI: `codegraph explore`). This module only
detects its state and tells Claude what to do; it never installs anything.

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


def mcp_wired(project):
    """True when a Claude Code MCP config (user or project) mentions the codegraph server."""
    home = Path(os.path.expanduser("~"))
    return any(_mcp_in(p) for p in (home / ".claude.json", Path(project.root) / ".mcp.json"))


def state(project):
    return {"cli": cli(), "indexed": indexed(project), "mcp": mcp_wired(project)}


def gitignored(project):
    try:
        text = (Path(project.root) / ".gitignore").read_text(encoding="utf-8")
    except OSError:
        return False
    return any(l.strip().strip("/") == INDEX_DIR for l in text.splitlines())


def context_line(project):
    """One SessionStart line for Claude: how to look code up, or how to get CodeGraph."""
    st = state(project)
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
        return ("CodeGraph CLI is installed but this project has no index yet. Before the first code search, run "
                "the uccif:codegraph skill (it runs `codegraph init --yes`, project-local, no question needed).")
    return ("CodeGraph is not installed. It replaces grep/find exploration with a pre-built code graph and saves "
            "tokens. Ask the user once, in your next reply, whether to set it up; if they agree, run the "
            "uccif:codegraph skill (never `npx codegraph`: that npm name is an unrelated package).")
