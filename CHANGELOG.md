# Changelog

## Unreleased

### Codex repository workflow preview

- Add safe project-scoped Codex setup, dry-run and removal, preserving user edits and shared task history.
- Add a UCCIF chat router plus init/resume/CodeGraph workflows for repository skill discovery.
- Add opt-in MCP configuration and host-specific diagnostics; configured does not mean connected.
- Generate a portable Codex workflow plugin and separate marketplace. Real Codex 0.167.0 passes local install, namespaced skill discovery, installed-core/task CLI and uninstall checks.
- Add credential-free app-server runtime checks and pinned CI coverage. Model turns, native hook execution and desktop/IDE UI remain unverified; no automatic tracking or token footer.

### Fixes

- Antigravity: edits made with `edit_file` and `write_file` were never tracked, because these tools
  pass the file as `Path`. It is now read, JSON-quoted or plain, and a relative path is resolved
  against the workspace.
- Task titles and new-topic detection no longer read blocks the host adds (`system-reminder`,
  `bash-input`, `bash-stdout`, `bash-stderr`). A prompt holding only those, such as a shell command
  typed by the user, no longer counts as a new request.

## 1.2.0 — Claude Code, Gemini CLI and Antigravity

### Fixes

- Two sessions starting in one project at the same moment could fail SessionStart: they shared one
  temp file when writing state (`FileNotFoundError` on `hosts.json.tmp`). Each writer now has its own.

### Antigravity plugin

Gemini CLI stopped serving unpaid and Google One users on June 18, 2026 in favour of Antigravity CLI
(`agy`), so Antigravity comes first. The Gemini extension stays for paid Gemini CLI users.

- `plugins/uccif-antigravity/`: an Antigravity plugin, built by
  `plugins/uccif/scripts/build_antigravity.py` from the core plugin; only `core`, a symlink to
  `../uccif`, is not generated (`agy plugin install` copies its target, so no code is duplicated).
  Install it with `agy plugin install https://github.com/phongng255/uccif/tree/<branch>/plugins/uccif-antigravity`.
- It has its own directory because `hooks/hooks.json` at a plugin root makes
  `agy plugin validate --strict` fail ("never loaded"), and the repo root needs that file for Gemini.
- `--host antigravity` no longer assumes Claude's format, which was wrong. It now reads
  `conversationId`, `workspacePaths` (hooks run with the plugin root as cwd), `transcriptPath`,
  `toolCall{name, args}`, `error`, `fullyIdle`, and writes `injectSteps` and `decision`.
- Hooks: SessionStart, PreInvocation (first call of a turn only), PostToolUse (edit tools), Stop.
  No PreToolUse: its required `decision` can only allow, deny or ask, and "allow" skips the user's
  permission prompt.
- `uccif setup antigravity [--remove]`: `.agents/rules/uccif.md`, `.agents/skills/`,
  `.agents/mcp_config.json` for the IDE. It records what it writes with a hash, never overwrites a
  file it did not write, and `--remove` deletes only its own unedited files.
- Skill and rule text moved to `uccif_lib/hostfiles.py`, shared by both hosts and by `setup`.

Differences from the other hosts, because Antigravity's hooks offer no way to do them:
no token line (no hook text reaches only the user without a model step, and the transcript format is
not documented); no prompt text in hooks, so `#quick` does nothing and auto tasks are titled "Code
change"; no search nudge (no PreToolUse); no compact or session-end event. Skill and `.claude/uccif/`
behaviour is the same.

`agy plugin import gemini` is not a working path: it copies Gemini's hooks file as is, and the loader
skips the whole file ("cannot unmarshal", or "command hook must specify 'command'" without the
`description` key). Skills and MCP arrive, hooks do not. Install the plugin instead.

### Gemini CLI extension

- The repo root is also a Gemini CLI extension: `gemini-extension.json`, `hooks/hooks.json` and
  `skills/`. `gemini extensions install <github url>` reads the manifest only at the repo root
  (tested with Gemini CLI 0.66.0: "Configuration file not found at
  /tmp/gemini-extension…/gemini-extension.json" when it sits in a subdirectory), so it cannot live
  under `plugins/`.
  - The manifest declares the same CodeGraph MCP server as the Claude plugin
    (`codegraph serve --mcp`, `CODEGRAPH_MCP_TOOLS=explore`), a 4-line context file and three
    settings (`UCCIF_REPLY_LANGUAGE`, `UCCIF_TOKEN_REPORT`, `UCCIF_AUTO_SETUP`).
  - Hooks call `"${extensionPath}${/}plugins${/}uccif${/}bin${/}uccif" hook --host gemini <Event>`
    for SessionStart, BeforeAgent, BeforeTool, AfterTool, AfterAgent, PreCompress and SessionEnd.
  - `skills/` is generated from `plugins/uccif/skills/` by `plugins/uccif/scripts/build_gemini.py`.
    It is one source, and CI fails when the copies are stale.
- Under Gemini, SessionStart also gives the full path of `uccif`, because it is not on PATH there,
  and the UCCIF block of AGENTS.md. Gemini reads only GEMINI.md by default, and the rest of a
  user's AGENTS.md is never injected.
- The token line reads Gemini CLI transcripts: JSONL records with `tokens`, where an updated
  message is appended again under the same id; older whole-JSON sessions are read too.
- CI: `gemini extensions validate .` and a skills sync check.

### One core for all hosts

- Host adapter (`uccif_lib/hosts.py`): `uccif hook --host claude|gemini|antigravity <event>`.
  It translates event names (Gemini SessionStart, BeforeAgent, BeforeTool, AfterTool, AfterAgent,
  PreCompress, SessionEnd), tool names (run_shell_command → Bash, read_file → Read,
  replace / write_file → Edit / Write, grep_search → Grep, glob → Glob, mcp_<server>_<tool> →
  mcp__<server>__<tool>) and the output: Gemini takes additionalContext only on SessionStart,
  BeforeAgent and AfterTool. A failed Gemini tool (AfterTool with an error) runs the failure handler.
  The hook logic stays in hooks.py. Without `--host`, everything works as in 1.1.
- The UCCIF block now lives in AGENTS.md; CLAUDE.md imports it with one `@AGENTS.md` line.
  `uccif agents-md write` (`claude-md write` is still an alias): it creates AGENTS.md or appends
  the block to it, creates CLAUDE.md as `@AGENTS.md` or appends that line once, moves a 1.1 block
  out of CLAUDE.md, and leaves a CLAUDE.md symlink in place. The user's own text is never changed.
  Exception: when the user already has an AGENTS.md that CLAUDE.md does not import, no import is
  added, because it would load the whole file into every Claude session. The same block, built
  from one source with the same markers, goes into both files instead, and `--replace` updates both.
- Generated project skills go to the skill dir of each host the project uses: `.claude/skills/`
  (Claude Code), `.agents/skills/` (Gemini CLI workspace alias, Antigravity). A project counts as
  using a host after that host ran a session there (`.claude/uccif/.local/hosts.json`), or for
  Antigravity once `.agents/rules/uccif.md` exists. A project with nothing recorded counts as
  Claude Code only, as in 1.1.
- Project data (task memory, summary, drift, logs) is where 1.1 kept it, so no migration is needed.
- `tests/measure_context.py`: the context UCCIF injects into Claude, in exact characters.

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
