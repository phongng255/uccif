# Changelog

## 1.1.0 — understands the project by itself, smaller overhead

**Understanding the source without commands**
- No CodeGraph CLI: SessionStart makes Claude ask one yes/no question in its first reply; on yes it
  installs, indexes (`codegraph init --yes`) and writes the project skills in the same session.
  `uccif codegraph decline` stops the question for that project.
- No more "project not surveyed, run init" message: the generated `<project>-map` skill is the code
  map. `/uccif:init` is optional and small: measured with `claude -p` on zod, 7 tool calls,
  ~$0.14 (≤ 4 files read, one test-runner check). It writes through `uccif summary write` / `uccif claude-md write`
  (Bash, stdin) because Claude Code asks before every Write under `.claude/`.

**One source of truth**
- `architecture.md` is gone. `summary.md` (≤ 20 lines, written only by init) holds only what the
  graph cannot know: purpose, conventions, external services.
- `uccif claude-md write` composes the CLAUDE.md block itself from 1–3 description lines: commands
  from the manifests and one pointer to the map skill, ≤ 15 lines, appended at the end; text outside
  the block is never touched. A longer block is refused. A symlinked CLAUDE.md (e.g. -> AGENTS.md)
  stays a symlink: the target is edited.
- Commands use the package manager declared in `package.json` `packageManager`, then the lockfile
  (pnpm / yarn / bun / npm), then npm.
- `uccif verify-tests` checks the test runner once: list mode first (`vitest list`,
  `jest --listTests`, `pytest --collect-only`, `go test -list`, `cargo test -- --list`, …), a real run
  only for runners without one, 60 s hard timeout, nothing installed (`npx --no-install`). Error,
  timeout or a sign the tests need a DB/server/network → the test command is marked `(unverified)`
  in the CLAUDE.md block, or `(deps not installed)` when node_modules / the venv is missing; no
  retry, init never tries another way. Only the test command is labelled; one line says
  "Commands from <packageManager>/manifest; only test is verified."
- `uccif summary write`: ≤ 20 lines from stdin, refuses to overwrite without `--replace`, stores the
  drift baseline. Init never copies what CLAUDE.md / AGENTS.md already say.
- Drift no longer reports new/removed source dirs (the map skill refreshes itself); dependency and
  build-config changes point to `summary.md` / the CLAUDE.md block. `project-analyst` now describes
  only a module's purpose, conventions and external services.

**CodeGraph routing** (defined once, in CORE RULE 2)
- Flows and "where/how" → MCP `codegraph_explore`; one symbol → Bash `codegraph node|callers|impact`;
  tests → `codegraph affected`. Hook lines, generated skills and agents point to it instead of
  repeating it. `.mcp.json` pins `CODEGRAPH_MCP_TOOLS=explore` (listing node/callers/impact costs
  ~1.3K tokens of schema per session).
- CodeGraph 1.6.2 has no switch to shorten its MCP `initialize` instructions (~1.7K tokens). Its
  `codegraph install` writes a `<!-- CODEGRAPH_START -->` block into CLAUDE.md (global or project),
  a second MCP server and a prompt hook; `uccif doctor` now warns when it finds any of them
  (read-only, user files are never edited).

**Fewer tokens and tool calls**
- CORE RULES: 8 → 5 rules.
- Tasks are automatic: the first edit of a prompt opens one (title and type from the prompt) and
  PostToolUse records files. A task lives across turns and `/clear` (SessionStart shows
  `Open task: <title> (<n> files)`). It closes when Claude records a decision/issue with
  `uccif task close`, when the first edit of a prompt is clearly other work (the old task closes
  without findings, a new one opens), or after 24 h without an edit (SessionStart). Matching is
  accent-free ("sửa lỗi" = "sua loi") with Vietnamese/English stopwords; continuation words
  ("luôn", "tiếp", "nữa", "đó", "vậy", "also") keep the task, and doubt keeps it too. No
  `uccif task start`, no "edit without task" nudge; `#quick` still skips the task.
- UserPromptSubmit injects nothing unless project notes are stale.
- PreToolUse runs only for Bash/Grep/Glob; the search reminder is one short line.
- Generated skills: at most 5 `-mod-*` skills (largest by symbols); other modules are rows of the
  map table with their key symbols. Every description ≤ 200 characters.
- Plugin skills `smart-code-search`, `code-review`, `code-impact-analysis` and `task-context` are
  removed (their roles live in CORE RULE 2 and the `change-reviewer` / `code-impact-analyzer` agents);
  remaining descriptions shortened.

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
