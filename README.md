# UCCIF — Universal Claude Code Intelligence Framework

A Claude Code plugin marketplace. Install the core plugin `uccif` once; from then on, in
**any** repository, with nothing to run by hand:

- **CodeGraph setup** ([@colbymchenry/codegraph](https://github.com/colbymchenry/codegraph)):
  the `uccif:codegraph` skill installs the CLI, wires its MCP server into Claude Code and
  indexes the project (`.codegraph/`, SQLite, tree-sitter); hooks then tell Claude to query
  `codegraph_explore` before any Grep/Read;
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
`uccif doctor` lists which rule files are loaded. `/uccif:init` offers an empty project file with
commented examples, and never overwrites one.

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

## CodeGraph

UCCIF has no code index of its own any more: [CodeGraph](https://github.com/colbymchenry/codegraph)
is the index. After installing UCCIF, the first session says whether CodeGraph is missing, not
wired or not indexed for this project, and Claude offers to run the `uccif:codegraph` skill, which
runs:

```bash
npm install -g @colbymchenry/codegraph
```

```bash
codegraph install --target=claude --location=global --yes
```

```bash
codegraph init --yes
```

then keeps `.codegraph/` out of git and checks `codegraph status`. Restart Claude Code once
afterwards so the `codegraph_explore` MCP tool loads. `uccif codegraph` prints the current state.

**Automatic from then on** (option `auto_setup`, default on): when the `codegraph` CLI is on the
machine, opening any project indexes it in the background (`codegraph init --yes`, project-local;
`.codegraph/` goes into `.git/info/exclude`, your `.gitignore` is not touched) and writes
**project skills** from the graph:

| Skill | Content |
|---|---|
| `.claude/skills/<project>-map` | modules (dir, size, role), entry points, routes, most-used symbols, commands, how to look code up |
| `.claude/skills/<project>-bugfix` | shortest path from a symptom to a tested fix: `codegraph explore` → callers → impact → smallest fix → `codegraph affected` → the project's own test commands (sub-packages included) |
| `.claude/skills/<project>-mod-*` | one per sizeable module: key files and symbols with `file:line`, routes, the modules it depends on / is used by, tests and how to run one |

They are rewritten only when the project's structure changes, and only files UCCIF wrote and
nobody edited (a sha marker tells); text inside the `<!-- uccif:notes -->` block survives every
rewrite, a file without the marker is never touched. By hand: `uccif skills generate [--force]
[--dry-run]`, `uccif skills list`. Commit them to share with your team.

Do not use `npx codegraph`: the unscoped npm package `codegraph` is an unrelated project with no
CLI. The real one is `@colbymchenry/codegraph` (`npx -y @colbymchenry/codegraph` runs its installer).

## Roadmap

| Version | Content |
|---|---|
| 3.0 | task/resume, token line, logs, `/uccif:init`, CORE RULES via hooks, 3 agents, CodeGraph setup, LSP config, drift detection, tests + CI |
| 3.1 | `[src:]` doc-claims check |
| 3.0-dev.11+ | code graph: optional tree-sitter parsing (done), call edges (done), multi-level `--impact` and `--path` queries (done), HTML graph view `uccif index graph` (done); phase 2 (nodes/edges model, Vue/Pinia/router edges, deeper resolution) in progress, step 0 fixture + benchmark done, nodes/edges model with confidence done, config-driven aliases + barrels + Python roots done, extends/implements + contains + function-level tests done, Vue template edges (`renders`, template calls) done, Pinia stores + composables + variable origins done, props/emits + vue-router done, callbacks + late resolution + built-in methods done, CSS variables + classes done, type references + variable reads/writes done, git co-change done, new graph queries done, graph view with kind filters / component tree / function level done, Go / Rust / Java (layer E) done; framework layer (Vue templates, Pinia, vue-router, CSS links) removed in dev.31: UCCIF is one framework-neutral core, project-specific knowledge goes in your own rules / skills / agents |
| 3.0-dev.33 | own code index and graph removed; CodeGraph setup skill + hooks that route code lookups to it |
| 3.0-dev.34 | automatic CodeGraph indexing + project skills (map, bugfix, modules) generated from the graph |
| 3.3 | `uccif-strict` (blocking gates), only if needed |
