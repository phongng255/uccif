# UCCIF — Universal Claude Code Intelligence Framework

A Claude Code plugin marketplace. The core plugin `uccif` gives Claude, in any repository:

- **CORE RULES** injected by hooks at session start, after `/clear` and after compaction
  (nothing to paste, nothing to keep in sync);
- **task memory** (`uccif task …`) that survives `/clear`, compaction and new sessions;
- **a real token line** after each reply, read from the transcript — never estimated;
- **project docs** (`.claude/uccif/summary.md`, `architecture.md`) written once by `/uccif:init`;
- read-only **agents** for module analysis, impact analysis and change review;
- **logs** of every hook run and session (`uccif log hooks|sessions`).

The core plugin **never blocks** a tool call or a stop. Blocking gates will live in an
optional `uccif-strict` plugin.

## Install

```
/plugin marketplace add phongng255/uccif
/plugin install uccif@uccif
```

Then open a project and ask for anything; the first session suggests `/uccif:init`.
Options (`/config`): `reply_language` (default `vi`), `token_report` (default on).

Requirements: Python 3.8+ (`python3`, `python` or `py -3`), git. macOS, Linux, or Windows
with Git Bash. Language servers and MCP servers are never installed automatically;
`uccif doctor` reports what is missing.

## Where data lives

| Data | Location |
|---|---|
| Framework code | `${CLAUDE_PLUGIN_ROOT}` |
| Task state, history, logs, metrics | `${CLAUDE_PLUGIN_DATA}/projects/<path-hash>/` (outside the repo) |
| Project docs, decisions, known issues | `<project>/.claude/uccif/` (commit these) |

The per-project key is the repo path; the root commit is stored with it, so a renamed or
moved repo keeps its data while two live clones stay separate.

## Develop

```
python3 -m venv .venv && .venv/bin/pip install pytest
.venv/bin/python -m pytest -q
claude plugin validate plugins/uccif --strict
claude --plugin-dir plugins/uccif          # try it in a session
tests/smoke.sh                             # headless end-to-end check (uses the API)
```

## Roadmap

| Version | Content |
|---|---|
| 3.0 | task/resume, token line, logs, `/uccif:init`, CORE RULES via hooks, 3 agents, tests + CI |
| 3.1 | drift detection + `[src:]` doc-claims |
| 3.2 | `codeintel` layer (LSP / Serena / tree-sitter index / ctags), `uccif-codeintel` plugin |
| 3.3 | `uccif-strict` (blocking gates), only if needed |
