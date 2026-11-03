# Changelog

## 1.1.0 — Antigravity CLI (Gemini)

- The plugin folder is also an **Antigravity CLI** (`agy`, Gemini CLI's successor) plugin:
  `.antigravity-plugin/plugin.json`, `mcp_config.json` (CodeGraph MCP server) and `hooks.json`
  (SessionStart, PostToolUse on file writes, Stop). Install with
  `agy plugin install <clone>/plugins/uccif`.
- `uccif hook --agent antigravity <event>` maps Antigravity's hook JSON (camelCase stdin,
  `toolCall`, `workspacePaths`) onto the existing handlers and answers in its format
  (`injectSteps` at SessionStart). Every hook still exits 0 and never blocks.
- Project skills are also written to `.agents/skills/` (or the legacy `.agent/skills/`): automatically
  in `agy` sessions or when the project already has that folder, or with
  `uccif skills generate --target agents|all`.

## 1.0.0 — first release

A Claude Code plugin marketplace with one plugin, `uccif`. Install it once; in any repository it
works without commands from the user.

**Workflow and rules**
- CORE RULES (do the work yourself, evidence before claims, ask first only for installs / deploy /
  push / external calls / deleting data, reply in the configured language) are injected by hooks at
  session start, after `/clear` and after compaction. Hooks cover SessionStart, UserPromptSubmit,
  PreToolUse (Bash), PostToolUse (Edit/Write), PostToolUseFailure, SubagentStart/Stop, Stop,
  PreCompact/PostCompact, SessionEnd and InstructionsLoaded. Every handler exits 0: the plugin never
  blocks a tool call or a stop.
- Your own rules: plain Markdown in `<project>/.claude/uccif/rules.md` and `~/.claude/uccif/rules.md`
  is loaded after the CORE RULES (15 lines each at most). `uccif doctor` lists what is loaded.
- Options (`/config`): `reply_language` (default `vi`), `token_report` (default on), `auto_setup`
  (default on).

**Task memory**
- `uccif task start | show | checkpoint | close`: the current task (goal, decisions, issues, tests,
  files) survives `/clear`, compaction and new sessions; `/uccif:resume` continues earlier work.
  State lives in `<project>/.claude/uccif/.local/` (git-ignored, writable from Claude's sandboxed
  Bash).

**Project docs and drift**
- `/uccif:init` surveys the repository once and writes `.claude/uccif/summary.md`, `architecture.md`
  and a UCCIF block in `CLAUDE.md`. Drift detection (`uccif drift check | show | ack`) notices new or
  removed source directories and dependency / build-config changes and hands Claude the doc section
  to update.

**Code search with CodeGraph**
- CodeGraph is the code index. The plugin declares its MCP server (`.mcp.json`:
  `codegraph serve --mcp`), so nothing is written to your Claude config; the `uccif:codegraph` skill
  installs the CLI (once you agree) and indexes the project, and `uccif codegraph` reports the state.
  With `auto_setup` on, opening a project indexes it in the background when the CLI is installed
  (`.codegraph/` is kept out of git through `.git/info/exclude`).
- Project skills generated from the graph, for any language: `.claude/skills/<project>-map`,
  `<project>-bugfix` and one `<project>-mod-*` per sizeable module (key files and symbols with
  `file:line`, routes, neighbours, tests), with the project's own test commands per package of a
  monorepo. Files you edit are never overwritten; the `<!-- uccif:notes -->` block survives every
  rewrite (`uccif skills generate | list`).
- LSP for TypeScript/JavaScript and Python (`.lsp.json`); `uccif doctor` reports a missing server
  instead of installing it.

**Skills and agents**
- Skills: `init`, `task-context`, `smart-code-search`, `code-impact-analysis`, `code-review`,
  `resume`, `codegraph`. Read-only agents: `project-analyst`, `code-impact-analyzer`,
  `change-reviewer`.

**Observability**
- A real token line after each reply, read from the transcript (never estimated), and
  `uccif usage turn | session`.
- Logs of every hook run and session (`uccif log hooks | sessions | prune`); `uccif doctor` checks
  the install; `uccif detect` surveys the project as JSON.

**Platforms**
- Python 3.8+ and git; no other dependency. macOS, Linux and Windows (Git Bash) are tested in CI on
  Python 3.9 and 3.12. Windows has not yet been tried in a real Claude Code session.
