# Changelog

## 3.0.0-dev.15

- **Structural edges** (phase 2, step 4; `SCHEMA` 6, an older index is rebuilt automatically):
  - `extends` / `implements` (A1): JS/TS classes (`extends`, `implements`, generics dropped,
    `Ns.Base`), TS `interface X extends Y, Z`, and Python `class X(Base, mod.Base)`. The base is
    resolved through the file's imports, the same file, or `import mod` namespaces; bases from
    packages or the language (`Vue`, `Error`, `ValueError`, `Generic`) are `extends_ext` /
    `implements_ext` (known, not repo code); anything else is `unresolved`. Bases imported
    through a barrel get a derived edge (`via`) straight to the defining file, like calls.
    Mixin calls (`extends Mix(Base)`) are skipped.
  - `contains` (A3): file -> top-level symbol and class -> method, so the graph can be walked
    from a file down to its functions. Impact and the graph view still follow only
    imports/calls, so containment never makes a file "depend" on itself.
  - `tests` (A4): for a test file, each resolved call is also a `tests` edge from the test
    (or its enclosing function) to the symbol it exercises, with `file:line`.
    `tests_for` (and so `--impact` "tests to run") also uses them, which catches tests that
    reach the code through a barrel.
- `--symbol` shows, within the 30-line limit: `Extends / implements`, `Subclasses /
  implementations (n)` and `Tested by (n)` with `file:line`.
- The benchmark's unresolved share ignores `contains`/`tests`/`*_ext` edges (they cannot be
  unresolved). Measured: one-file update 5-6 ms, DB +20% (this repo 1.5 -> 1.8 MB).
- Not yet: method calls on expressions (`new Base().run()`) stay unresolved (roadmap C1), so
  tests that only call methods show the class, not the method.

## 3.0.0-dev.14

- **Import resolution rewritten** (phase 2, step 3), now in `uccif_lib/resolve.py`
  (`SCHEMA` 5; an older index is rebuilt automatically).
  - **JS/TS aliases from config (C5):** the nearest `tsconfig.json` / `jsconfig.json`
    (`baseUrl`, `paths`, relative `extends`; comments and trailing commas allowed) and
    `vite.config.*` `resolve.alias` (object form and `{ find, replacement }`, with
    `fileURLToPath(new URL(...))` or `path.resolve(__dirname, ...)`). "Nearest" means the
    folder with a package.json / tsconfig / vite config, so a monorepo package keeps its own
    aliases. With no config `@/` and `~/` still mean `src/`.
  - **Python (C4):** besides the repo root, `src/`, `lib/` and `app/`, package roots declared
    in `pyproject.toml` / `setup.cfg`, the parent of every top-level package (a folder with
    `__init__.py`), and the importing file's own folder (scripts, pytest siblings). This repo
    went from 28 unresolved imports to 1-2% of edges.
  - **Barrels (A2):** `export * from`, `export { a as b } from` (and Python `__init__.py`
    `from .x import y`) are stored as `re_exports` edges. After each update that changed
    anything, derived edges with `via` = the barrel link importers and callers straight to the
    file that defines the name, so `--impact` on `utils/format.ts` finds `ExpenseList.vue`
    ("imports '@/utils' via src/utils/index.ts"), and tests that import through a barrel count
    as tests for the real file. Derived edges are recomputed from scratch each time, so they
    cannot go stale; the direct edge to the barrel stays.
- New `bindings` table (which local name comes from which import) feeds the barrel pass.
- Measured: one-file update 6-7 ms (budget 300 ms; the barrel pass is a few queries on small
  repos, to be re-measured on a real app); DB +10-15%.
- Unresolved share: vue-app 28%, this repo 68% with tree-sitter (method calls on local
  variables, roadmap C1; 1% without it). No remaining import gaps in the fixture.

## 3.0.0-dev.13

- **Unified code graph** (phase 2, step 2): two new tables, written alongside the existing
  ones (`SCHEMA` 4; an older index is rebuilt automatically, and a reader never serves an
  index from another schema).
  - `nodes(id, kind, name, path, line, end_line, scope, precision)`: one `file` node per file
    plus one per symbol. Ids are stable (`path` / `path#Scope.name`), so edges from other
    files survive a re-parse. Node kinds use `_` (`css_var`); `end_line` is filled later.
  - `edges(src_id, dst_id, kind, line, confidence, detail, src_path, dst_path)`. Kinds today:
    `imports`, `calls` (to the callee's symbol node, from the enclosing function's node),
    and `imports_ext` / `calls_ext` for packages and language built-ins (`vue`, `ref()`,
    `print()`, `console.log()`): fully known, just not repo code. `confidence`:
    `extracted` / `inferred` (none yet) / `unresolved` (name known, target not, `dst_id` NULL).
    `src_path`/`dst_path` are kept on each edge so per-file updates and file queries stay
    indexed lookups.
  - Updates keep the graph whole: a re-parsed file re-points incoming edges to its symbols by
    name (or to the file if the symbol is gone); a deleted file turns incoming edges into
    `unresolved` leads instead of dangling ids.
- `--impact`, `--path`, `--symbol` callers, `dependents` and the HTML graph now read `edges`.
  `impact()` takes `kinds` and `min_confidence` (CLI flags come with the query step).
- `index status` adds `Graph: N nodes, M edges (extracted a, inferred b, unresolved c)`;
  `tests/bench_index.py` adds nodes, edges and the unresolved share (warns above 30%).
- Measured (this sandbox): one-file update still 5 ms (budget 300 ms). The DB is about 2.5×
  larger (this repo: 520 → 1300 KB) while old and new tables are both written; a later PR can
  drop the old ones.
- **Unresolved share (reported per the plan):** vue-app fixture 29%, at the 30% limit. The
  remainder are store actions called on a variable (`store.addExpense()`, roadmap B4/C1), test
  globals (`expect`, `it`) and `emit`. This repo: 79%, nearly all method calls on local
  variables (`x.get()`, `con.execute()`), roadmap C1, plus Python absolute imports outside
  `src/`/`lib/`/`app/` (`uccif_lib.*`, roadmap C4), now shown as `unresolved` leads rather than
  as packages.

## 3.0.0-dev.12

- **Code graph, phase 2, step 0** (no change to the plugin's behaviour): groundwork for the
  detailed-graph roadmap.
  - `tests/fixtures/vue-app/`: a fixed Vue 3 + Vite + Pinia + vue-router mini app (24 indexed
    files) with `<script setup>`, props/emits, a composable, two stores (options and setup
    style), lazy routes, a barrel `index.ts`, `@/` imports and CSS variables.
  - `tests/test_fixture_vue_app.py`: pins what the index knows about it today, including the
    known gaps later PRs close (barrel re-exports, `store.action()` calls unresolved).
  - `tests/bench_index.py`: full build, one-file update (budget 300 ms) and no-op update
    timings, DB size and row counts; run by hand, not collected by pytest or CI.
- Baseline (this sandbox, median of 5): fixture 57 ms full build / 4 ms one-file update / 64 KB;
  this repo 107 ms / 4 ms / 520 KB (tree-sitter), 57 ms / 3 ms / 160 KB (regex).

## 3.0.0-dev.11

- **Graph view** (step 4 of the code-graph roadmap): `uccif index graph [--out FILE]
  [--max-nodes N]` writes one self-contained HTML page (no network, no libraries) with the
  most-connected files (default 300) as dots and resolved imports/calls as lines. Click a dot
  for what it uses and what uses it (with the `--impact` command to run next), search by
  name, hide tests or call edges, pan and zoom; light and dark themes.
- The page is written next to the index (outside the repo); where that is read-only (Claude
  Code's Bash sandbox) it goes to the git-ignored `.claude/uccif/.local/`. Nothing tracked is
  touched. Meant for a person to open; Claude keeps using `--impact` / `--path`.
- Known limit (index, not the view): Python absolute imports only resolve from `src/`,
  `lib/`, `app/` or the repo root, so a package under another folder (e.g. `plugins/x/pkg`)
  shows no links.

## 3.0.0-dev.10

- **Graph queries** (step 3 of the code-graph roadmap):
  - `uccif index query --impact <file> [--depth N]` (default 3, max 6): the files that import
    or call into a file, level by level, each as `file:line` with the import and the call that
    link it, plus the tests to run. Breadth-first over import edges and, where tree-sitter
    parsed the file, call edges.
  - `uccif index query --path <A> <B>`: the shortest import/call chain between two files or
    symbols (tries A uses B, then B uses A), one `file:line` hop per line.
  - Both stay within 30 lines (counted "... +N more"), work without tree-sitter (import edges
    only) and read the index read-only like the other queries.
- Imports now store their line number (`SCHEMA` 3; an older index is rebuilt automatically).
- `code-impact-analysis`, `code-impact-analyzer`, `smart-code-search` and the session hint use
  `--impact` / `--path`.

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
