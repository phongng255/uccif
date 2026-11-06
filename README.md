# UCCIF — Universal Claude Code Intelligence Framework

A plugin for AI coding tools: Claude Code, Antigravity (CLI and IDE) and Gemini CLI. Support differs
per tool; see the [comparison table](docs/GUIDE.md#2-what-each-tool-supports). This page describes
Claude Code, the fullest case. Install the core plugin `uccif` once; from then on, in **any**
repository, with nothing to run by hand:

- **CodeGraph** ([@colbymchenry/codegraph](https://github.com/colbymchenry/codegraph)) as the
  code index: the `uccif:codegraph` skill installs the CLI and indexes the project
  (`.codegraph/`, SQLite, tree-sitter), the plugin declares its MCP server, and hooks tell Claude
  to query `codegraph_explore` before any Grep/Read of source code (also `cat`/`sed`/`head` on
  it). When CodeGraph or the project skills become ready mid-session, the next prompt tells Claude,
  so it stops following the earlier "use Grep" note;
- **LSP** for TypeScript/JavaScript and Python (Claude offers to install a missing server once);
- **CORE RULES** and a token-saving workflow injected by hooks at every session and prompt;
- **automatic task memory**: the first edit opens a task (title from your prompt), edited files are
  recorded (also files changed by Bash or a script: at the end of each turn the hook compares
  `git status` with the start of the turn), the task survives turns and `/clear`, and closes on new work, after 24 h idle, or when
  Claude records a decision or issue;
- **project skills** generated from the graph (`<project>-map`, `-bugfix`, up to 5 `-mod-*`): the
  code map, one source of truth. `/uccif:init` is optional: it only adds what the graph cannot
  know (purpose, conventions, external services) to `.claude/uccif/summary.md` and a ≤ 15-line
  block in `AGENTS.md`, which `CLAUDE.md` imports with `@AGENTS.md`;
- a **real token line** after each reply, read from the transcript — never estimated;
- read-only **agents** for impact analysis, change review and module purpose;
- **logs** of every hook run and session (`uccif log hooks|sessions`).

The plugin **never blocks** a tool call or a stop by default: every hook exits 0. The one opt-in
exception is `strict_codegraph` (off by default): with CodeGraph indexed, the first Read/Grep of
source code in a turn without a CodeGraph lookup is refused once, with the lookup to make instead;
a retry goes through. Claude Code only.

> 📖 **User guides:** [Tiếng Việt](docs/HUONG-DAN.md) · [English](docs/GUIDE.md). They cover install,
> daily use, the token line, what to commit, updating, uninstalling and troubleshooting.

## Install

```
/plugin marketplace add phongng255/uccif
/plugin install uccif@uccif
```

Then open a project and ask for anything. Without CodeGraph, Claude asks once whether to install it
and, on yes, installs, indexes and writes the project skills in the same session.
Options (`/config`): `reply_language` (default `vi`), `token_report` (default on), `auto_setup`
(default on), `strict_codegraph` (default off).

Requirements: Python 3.8+ (`python3`, `python` or `py -3`), git. macOS, Linux and Windows (Git
Bash, which Claude Code uses to run hooks) are all tested in CI; Windows has not yet been
tried in a real Claude Code session. Language servers and the CodeGraph CLI are never installed
without your agreement; `uccif doctor` reports what is missing.

## Antigravity

Antigravity CLI (`agy`), from a terminal:

```
agy plugin install https://github.com/phongng255/uccif/tree/main/plugins/uccif-antigravity
```

Use that exact URL form. A bare repo URL, `#branch` or `--ref` installs the Claude plugin from the
default branch instead, whose hooks Antigravity skips. Remove it with `agy plugin uninstall uccif`.

Antigravity IDE, in a project (this writes `.agents/`, which the IDE reads per workspace):

```
<path to>/plugins/uccif/bin/uccif setup antigravity
```

Run `bin/uccif` directly: it is a shell script, not a Python file. `--remove` deletes only the files
it wrote. The rule file holds this machine's path to `uccif`, so do not commit it. There are no hooks
in this mode, so no automatic task memory and no automatic indexing: run `codegraph init --yes` and
`uccif skills generate` yourself to get the project skills.

Antigravity shows no token line and has no `#quick`: its hooks do not allow them.

## Update

```
/plugin marketplace update uccif
/plugin update uccif@uccif
```

The same from a terminal: `claude plugin marketplace update uccif`, then
`claude plugin update uccif@uccif`. **Restart Claude Code afterwards**; an update only applies after a
restart.

- `plugin.json` pins `version`, so an installed copy updates only when the repository has a newer
  version. "Already up to date" means there is none. `claude plugin list` shows the installed
  version; ask Claude to run `uccif version` to see the one that is running.
- Your data stays where it is: project docs and task memory live in your project
  (`.claude/uccif/`, `.claude/uccif/.local/`) and the code index in CodeGraph's `.codegraph/`.
  Nothing has to be rerun after an update.
- If an update does not take effect: `claude plugin uninstall uccif@uccif`, then
  `claude plugin install uccif@uccif`, and restart.

## Where data lives

| Data | Location |
|---|---|
| Framework code | `${CLAUDE_PLUGIN_ROOT}` |
| Logs, metrics | `${CLAUDE_PLUGIN_DATA}/projects/<path-hash>/` (outside the repo; written by hooks) |
| Code graph | `<project>/.codegraph/` (CodeGraph's own; git-ignored) |
| Task memory, history, drift baseline | `<project>/.claude/uccif/.local/` (git-ignored; writable from Claude's sandboxed Bash) |
| Project docs, decisions, known issues | `<project>/.claude/uccif/` (commit these) |

The per-project key is the repo path; the root commit is stored with it, so a renamed or
moved repo keeps its data while two live clones stay separate.

## Extend it yourself

UCCIF is one framework-neutral core. What is special about your project or your stack goes in
your own files, which Claude Code and UCCIF load without any change to the plugin:

| What | Where | Loaded by |
|---|---|---|
| Rules for one project (committable) | `<project>/.claude/uccif/rules.md` | UCCIF, after the CORE RULES |
| Rules for every project | `~/.claude/uccif/rules.md` | UCCIF, after the CORE RULES |
| A skill (e.g. how your framework is wired) | `<project>/.claude/skills/<name>/SKILL.md` | Claude Code |
| An agent | `<project>/.claude/agents/<name>.md` | Claude Code |
| Fixed project instructions | `CLAUDE.md` (outside the UCCIF block) | Claude Code |

The rule files are plain Markdown, one rule per line. They are read at session start, after
`/clear` and after compaction, the same moments as the CORE RULES (every-project file first, then
the project's). Each file contributes at most 15 non-empty lines (`<!-- -->` comments do not count);
a longer file is cut with a pointer to the rest. A missing or unreadable file is skipped.
`uccif doctor` lists which rule files are loaded. UCCIF never writes these files.

## Codex (development preview)

The workflow plugin has been installed, discovered and uninstalled using real Codex CLI /
app-server **0.167.0 on Linux** without an API key. Native status/init/resume and repository resume
also completed in real model turns using Codex Desktop's bundled CLI **0.166.0-alpha.6 on macOS**.
Desktop/VS Code graphical UI behavior and lifecycle hook execution remain unverified. This
development package is not publicly released.

From a checkout containing these changes, add its local marketplace and install:

```bash
codex plugin marketplace add /path/to/uccif
codex plugin add uccif@uccif-codex-local
```

Codex discovers the qualified workflow names `$uccif:init`, `$uccif:resume`, `$uccif:codegraph`
and the menu `$uccif:uccif`. For example, select the init skill in chat to write project notes.
These are skill mentions, not terminal commands or Claude slash commands. The installed package
contains its own generated Python core; it does not depend on paths back into this checkout.

For repository-scoped workflows instead, run this checkout's launcher from the target project:

```bash
/path/to/uccif/plugins/uccif/bin/uccif setup codex --dry-run
/path/to/uccif/plugins/uccif/bin/uccif setup codex
```

Repository setup creates a bounded AGENTS.md block and dedicated `.agents/skills/` workflows.
Its menu is `uccif`; the dedicated names start with `uccif-codex-`. The plugin's qualified names
remain distinct. Remove unchanged setup content with `uccif setup codex --remove`.

Both preview routes install **no hooks** and do not automatically track edits or show token
footers. Task memory remains shared at `.claude/uccif/`; workflow checkpoints save progress.
CodeGraph is optional and is not auto-started by the workflow plugin. Preview project MCP changes
with `uccif setup codex --with-codegraph --dry-run` before applying without `--dry-run`.
Existing servers/uncertain plugin config are preserved. `uccif doctor --host codex` distinguishes
configuration from a verified connection. No dependency installation or trust changes are automatic.
Existing TOML is left alone without `tomllib` or optional `tomli`.

Repository setup files contain this machine's core path; keep them local. The native package is
portable. For verification details and known limits see the [Vietnamese runtime report](docs/CODEX-RUNTIME-VI.md).

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

**Layout.** One core serves three hosts, and each host fixes where it reads its files:

| Path | Host | Edit it? |
| --- | --- | --- |
| `plugins/uccif/` | Claude Code; also the core all hosts run | Yes: the source, skills included |
| `.claude-plugin/marketplace.json` | Claude Code | Yes |
| `gemini-extension.json`, `hooks/hooks.json` | Gemini CLI | Yes |
| `skills/` | Gemini CLI | No: run `build_gemini.py` |
| `plugins/uccif-antigravity/` | Antigravity | No: run `build_antigravity.py` (`core` is a symlink to `../uccif`) |

Gemini CLI needs its manifest and hooks at the repo root, so `skills/` and `hooks/` there belong
to Gemini. The Claude Code plugin cannot move to the root too: Claude Code always loads a plugin's
`hooks/hooks.json`, even when `plugin.json` sets `hooks`, so it would run Gemini's hook commands.

## CodeGraph

UCCIF has no code index of its own: [CodeGraph](https://github.com/colbymchenry/codegraph)
is the index. When the CLI is missing, Claude asks one yes/no question in its first reply (no:
`uccif codegraph decline` stops the question for that project); on yes the `uccif:codegraph`
skill runs, in the same session:

```bash
npm install -g @colbymchenry/codegraph
```

```bash
codegraph init --yes
```

then `uccif skills generate`, keeps `.codegraph/` out of git and checks `codegraph status`. The MCP
server is declared by the plugin itself (`.mcp.json`: `codegraph serve --mcp`, with
`CODEGRAPH_MCP_TOOLS=explore`), so nothing is written to your Claude config.
Lookup routing (one definition, CORE RULE 2): flows and "where/how" → `codegraph_explore`; one
symbol → `codegraph node` / `callers` / `impact` in Bash; tests after a change →
`git diff --name-only | codegraph affected --stdin --quiet`; Grep only for literals, scoped.
Restart Claude Code once afterwards so `codegraph_explore` loads; its first call may ask you to
allow the tool. `uccif codegraph` prints the current state (`mcp_via` says where the server comes
from). Do not also run `codegraph install --target=claude`: that registers a second server with
the same tools (if you did, remove yours with `codegraph uninstall --target=claude`).

**Automatic from then on** (option `auto_setup`, default on): when the `codegraph` CLI is on the
machine, opening any project indexes it in the background (`codegraph init --yes`, project-local;
`.codegraph/` goes into `.git/info/exclude`, your `.gitignore` is not touched) and writes
**project skills** from the graph:

| Skill | Content |
|---|---|
| `.claude/skills/<project>-map` | modules (dir, size, role; key symbols for modules without their own skill), entry points, routes, most-used symbols, commands |
| `.claude/skills/<project>-bugfix` | shortest path from a symptom to a tested fix: explore → callers → impact → smallest fix → affected tests → the project's own test commands |
| `.claude/skills/<project>-mod-*` | the 5 largest modules (by symbols): key files and symbols with `file:line`, routes, the modules it depends on / is used by, tests and how to run one |

They are rewritten only when the project's structure changes, and only files UCCIF wrote and
nobody edited (a sha marker tells); text inside the `<!-- uccif:notes -->` block survives every
rewrite, a file without the marker is never touched. By hand: `uccif skills generate [--force]
[--dry-run]`, `uccif skills list`. Commit them to share with your team. On Antigravity and Gemini CLI
they live in `.agents/skills/` instead.

Do not use `npx codegraph`: the unscoped npm package `codegraph` is an unrelated project with no
CLI. The real one is `@colbymchenry/codegraph` (`npx -y @colbymchenry/codegraph` runs its installer).

## Planned

Not built yet, and not promised: a `[src:]` doc-claims check, and an optional `uccif-strict` plugin
with blocking gates (only if the never-block core turns out not to be enough).
