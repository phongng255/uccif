# UCCIF — Universal Claude Code Intelligence Framework

A Claude Code plugin marketplace. Install the core plugin `uccif` once; from then on, in
**any** repository, with nothing to run by hand:

- a **code index** (SQLite, outside the repo) that Claude queries before grepping:
  definitions, dependents, imports, related tests — built in the background at session start
  and kept current after every edit, every turn and every `git pull`;
- **LSP** for TypeScript/JavaScript and Python (Claude offers to install a missing server once);
- **CORE RULES** and a token-saving workflow injected by hooks at every session and prompt;
- **task memory** (`uccif task …`) that survives `/clear`, compaction and new sessions;
- **project docs** (`.claude/uccif/`) written once by `/uccif:init`, with **drift detection**
  that tells Claude which section to update when the project's structure changes;
- a **real token line** after each reply, read from the transcript — never estimated;
- read-only **agents** for module analysis, impact analysis and change review;
- **logs** of every hook run and session (`uccif log hooks|sessions`).

Full context — decisions, incidents, how it works — for people and AIs picking this up:
[docs/HANDOFF.md](docs/HANDOFF.md).

The core plugin **never blocks** a tool call or a stop. Blocking gates will live in an
optional `uccif-strict` plugin.

## Install

```
/plugin marketplace add phongng255/uccif
/plugin install uccif@uccif
```

Then open a project and ask for anything; the first session suggests `/uccif:init`.
Options (`/config`): `reply_language` (default `vi`), `token_report` (default on).

Requirements: Python 3.8+ (`python3`, `python` or `py -3`), git. macOS, Linux and Windows (Git
Bash, which Claude Code uses to run hooks) are all tested in CI; Windows has not yet been
tried in a real Claude Code session. Language servers and MCP servers are never installed automatically;
`uccif doctor` reports what is missing.

## Where data lives

| Data | Location |
|---|---|
| Framework code | `${CLAUDE_PLUGIN_ROOT}` |
| Code index, logs, metrics | `${CLAUDE_PLUGIN_DATA}/projects/<path-hash>/` (outside the repo; written by hooks) |
| Task memory, history, drift baseline | `<project>/.claude/uccif/.local/` (git-ignored; writable from Claude's sandboxed Bash) |
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

The smoke test also runs in GitHub Actions by hand (*Actions → smoke → Run workflow*); it
needs an `ANTHROPIC_API_KEY` repository secret.

**Versions.** `plugin.json` pins `version`, so an installed copy only updates when the version
is bumped (`plugins/uccif/.claude-plugin/plugin.json` and `uccif_lib/__init__.py` must match;
a test checks it). While developing, load the working tree with `claude --plugin-dir` instead
of reinstalling.

## Code graph queries

Claude runs these itself (the session hint and the skills point to them); they refresh changed
files first, read the index read-only and answer in at most 30 lines, each with `file:line`.

| Query | Answers |
|---|---|
| `uccif index query --symbol X` | definitions, callers, subclasses, users (callbacks, types, reads/writes), tests |
| `--file P` | symbols, imports, imported-by, tests, files often changed with it |
| `--impact P` or `--impact X` | what a change to a file or a symbol reaches, level by level, plus tests to run; `--kinds code,types,vars`, `--min-confidence inferred`, `--depth N` |
| `--path A B` | shortest dependency chain between two files or symbols |
| `--cochange P` | files git history changes together with P |
| `uccif index graph [--file P]` | a self-contained HTML view: files, or one file's functions; filter by edge kind |

Edges carry a confidence: `extracted` (found through an explicit import / declaration),
`inferred` (matched by name or pattern, shown with `~inferred` and hidden by default when certain
edges exist) and `unresolved` (a name we could not place: a lead to check, never a fact).

## Roadmap

| Version | Content |
|---|---|
| 3.0 | task/resume, token line, logs, `/uccif:init`, CORE RULES via hooks, 3 agents, code index, LSP config, drift detection, tests + CI |
| 3.1 | `[src:]` doc-claims check |
| 3.0-dev.11+ | code graph: optional tree-sitter parsing (done), call edges (done), multi-level `--impact` and `--path` queries (done), HTML graph view `uccif index graph` (done); phase 2 (nodes/edges model, Vue/Pinia/router edges, deeper resolution) in progress, step 0 fixture + benchmark done, nodes/edges model with confidence done, config-driven aliases + barrels + Python roots done, extends/implements + contains + function-level tests done, Vue template edges (`renders`, template calls) done, Pinia stores + composables + variable origins done, props/emits + vue-router done, callbacks + late resolution + built-in methods done, CSS variables + classes done, type references + variable reads/writes done, git co-change done, new graph queries done, graph view with kind filters / component tree / function level done, Go / Rust / Java (layer E) done; framework layer (Vue templates, Pinia, vue-router, CSS links) removed in dev.31: UCCIF is one framework-neutral core, project-specific knowledge goes in your own rules / skills / agents |
| 3.2 | optional `uccif-codeintel` plugin (Serena, more languages) |
| 3.3 | `uccif-strict` (blocking gates), only if needed |
