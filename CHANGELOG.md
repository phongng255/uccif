# Changelog

## 3.0.0-dev.9

- **Call graph** (step 2 of the code-graph roadmap). With tree-sitter installed, the index
  also records who calls what in a new `calls` table (`SCHEMA` 2; an old index is rebuilt
  automatically). Each call keeps its enclosing function (`Class.method`), line, and, when it
  can be worked out, the repo file defining the callee: through the file's own imports (named,
  aliased, namespace, Python `from . import`), same-file definitions, and `this.x()` /
  `self.x()`. Everything else is stored unresolved, never guessed.
- `uccif index query --symbol X` now shows `Called by (n)` (resolved) and
  `Possibly called by (receiver unresolved) (n)` with `file:line in caller`, still within the
  30-line limit (callers are capped, references shrink to fit). `index status` shows the
  number of call edges.
- Without tree-sitter nothing changes: no call edges, `git grep` references as before.
- Known limits: calls on variables (`store.add()`) and dynamic calls stay unresolved; a call
  resolved before its target file existed is refreshed only when the caller file is re-parsed.

## 3.0.0-dev.8

- **Optional tree-sitter parsing** for the code index (step 1 of the code-graph roadmap).
  When `tree-sitter`, `tree-sitter-javascript`/`-typescript` and `tree-sitter-python` are
  importable, JS/TS/TSX/Vue/Svelte/Python files get exact symbols (functions, classes, methods
  with their class, arrow-function consts, Pinia `defineStore`, types/interfaces/enums) and
  exact imports (`import`, `export … from`, `require`, dynamic `import()`, `import a, b`),
  stored with precision `ast`. Vue/Svelte parse only `<script>` and keep real line numbers.
- Fallback order is tree-sitter → universal-ctags → regex; without the packages behaviour is
  unchanged. Nothing is installed automatically; `uccif doctor` and `index status` say which
  tool is active. `UCCIF_NO_TREE_SITTER=1` turns it off.
- CI runs the suite a second time with the tree-sitter packages installed.

## 3.0.0-dev.7

- Windows: the Stop hook crashed printing the token line (its emoji cannot be encoded in the
  console's legacy code page), so Windows users never saw it. The CLI now switches
  stdin/stdout/stderr to UTF-8, and hook JSON is written ASCII-escaped. Prompts in
  Vietnamese reach the hooks intact too.

## 3.0.0-dev.6

Found by the Windows CI job:
- Files edited by Claude are recorded with `/` separators on Windows too (they were stored as
  `src\a.ts`, so task file lists and index keys did not match).
- Git output is decoded as UTF-8 everywhere; Windows' locale code page garbled non-ASCII paths.
- Tests: run the launcher with Git Bash (a bare `bash` on Windows can be WSL's launcher), read
  UTF-8 explicitly, and leave a directory before renaming it.

## 3.0.0-dev.5

- `uccif detect` reports LSP status only for languages the plugin configures (TS/JS, Python);
  others (e.g. Vue) go to `no_lsp`, covered by the code index. `/uccif:init` no longer asks
  about installing a server the plugin would not use.
- `/uccif:init` states that `.claude/uccif/` docs and `.gitignore` are meant to be committed
  instead of asking, and leaves unrelated untracked files alone.

## 3.0.0-dev.4

- Works inside Claude Code's Bash sandbox, which denies writes under `~/.claude`:
  - `uccif index query` / `status` open the index read-only (rollback journal instead of
    WAL); the refresh before a query is skipped there, since hooks keep the index current.
  - Task memory and drift state moved to `<project>/.claude/uccif/.local/` (writable in the
    sandbox, git-ignored through `.claude/uccif/.gitignore`). Existing task state is migrated
    automatically at the next session start.
  - `uccif doctor` reports a read-only data dir as INFO, not a failure.
- `doctor` no longer warns about languages the plugin has no LSP config for (e.g. Vue); it
  notes that the code index covers them. Missing bundled servers show the install command.

## 3.0.0-dev.3

- **Code index** (`uccif index query --symbol | --file | --tests-for`, `index status|build`):
  SQLite map of files, symbols, imports and tests, kept outside the repo. Symbols from
  universal-ctags when installed, otherwise per-language regexes; references counted live
  with `git grep`. Every query refreshes changed files first.
- **Automatic upkeep:** SessionStart builds/refreshes the index and checks drift in the
  background; each Edit/Write re-indexes that file; Stop refreshes everything touched outside
  Claude (Bash, the user, git pull). No manual step.
- **Drift detection** (`uccif drift check|show|ack`): new/removed source dirs, dependency and
  build-config changes are handed to Claude on the next prompt with the doc section to update.
- **LSP:** the plugin ships `.lsp.json` for TypeScript/JavaScript and Python. When a project's
  main language has no server installed, Claude offers the install command once per machine.
- Every prompt reminds Claude to search with the index first; skills and agents use it.
- `uccif doctor` reports index status.

## 3.0.0-dev.2

- Windows: the launcher no longer sets `PYTHONPATH` (its `:` separator and `/c/...` paths
  break native Windows Python); it runs `scripts/uccif_main.py`, which sets `sys.path` itself.
- Hooks use the quoted shell form (`"${CLAUDE_PLUGIN_ROOT}/bin/uccif" hook <event>`) instead
  of exec form, because exec-form `args` are unreliable on Windows.
- CI runs on Windows too (experimental, does not fail the run). New manual `smoke` workflow.
- Data-dir fallback picks the core plugin's dir (`uccif-uccif`, or a dir holding the core
  marker), never a sibling plugin such as `uccif-strict-*`.
- The repo's root commit is cached in `meta.json` instead of walking history on every hook.
- PreToolUse calls that skip (every main-agent Bash call) are no longer logged.
- Task state is guarded by a cross-process lock: two sessions on one project can no longer
  overwrite each other or reuse a task id. A stale lock (crashed process) is taken over.
- CORE RULES no longer mention an index that arrives only in 3.2.
- Token line shows billions as `B`.
- `uccif detect` / `doctor` no longer name unconfirmed LSP plugins (Go, Vue).

## 3.0.0-dev.1

- First plugin skeleton: hooks, task memory, token line, logs, `/uccif:init`, 3 agents, tests, CI.
