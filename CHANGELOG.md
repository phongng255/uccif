# Changelog

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
