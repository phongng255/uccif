---
name: codegraph
description: Install and wire CodeGraph (@colbymchenry/codegraph) for this project - a tree-sitter code graph in .codegraph/ (SQLite) that Claude queries through the codegraph_explore MCP tool instead of grep/find. Use when a UCCIF hook says CodeGraph is missing or the project has no index, when the user asks to install, set up, re-index or fix CodeGraph, or before the first code search in a new repo.
argument-hint: "[reindex]"
---

# CodeGraph setup

UCCIF has no code index of its own: CodeGraph is the index. Run every step yourself; the
user only restarts Claude Code at the end.

**Package name:** always `@colbymchenry/codegraph`. Never `npx codegraph` — the unscoped
npm package `codegraph` is an unrelated project with no CLI.

## Steps

1. **State.** Run `uccif codegraph` (JSON: `cli`, `indexed`, `mcp`, `gitignored`). Skip the
   steps that are already done. `$ARGUMENTS` = `reindex` → go to step 4 with `codegraph index --force`.
2. **CLI** (only if `cli` is null). The user asked for this skill or agreed to it, so install:
   - Node available (`node -v`): `npm install -g @colbymchenry/codegraph`.
   - npm global fails (EACCES, sandbox): use `npx -y @colbymchenry/codegraph <command>` in
     place of `codegraph <command>` for the rest of this skill.
   - No Node: show the user the official installer and ask before running it:
     `curl -fsSL https://raw.githubusercontent.com/colbymchenry/codegraph/main/install.sh | sh`
     (Windows PowerShell: `irm https://raw.githubusercontent.com/colbymchenry/codegraph/main/install.ps1 | iex`).
3. **MCP tool.** Nothing to run: the plugin declares the server itself (`.mcp.json`:
   `codegraph serve --mcp`), so no Claude config is edited, which Claude Code would refuse
   anyway. It starts once the CLI is on PATH, after a restart of Claude Code; the first call
   of `codegraph_explore` may ask the user to allow the tool. Do **not** run
   `codegraph install --target=claude`: it would register a second server with the same
   tools. Only when `mcp` is false (an older plugin without `.mcp.json`) give the user
   `codegraph install --target=claude --location=global --yes` to run in their terminal; do
   not retry another way if the sandbox denies it.
4. **Index this project** (only if `indexed` is false): `codegraph init --yes` at the project
   root. It builds `.codegraph/` and keeps it in sync by itself afterwards (no `sync` needed).
5. **Git.** If `gitignored` is false, append `.codegraph/` to `.gitignore` (the index is local,
   machine-specific data; never commit it).
6. **Check.** `codegraph status` must show files and symbols. Then try one real lookup:
   `codegraph explore "<main entry point or a module name>"`.
7. **Project skills.** `uccif skills generate` writes `.claude/skills/<project>-map`,
   `<project>-bugfix` and one `<project>-mod-*` per sizeable module from the graph. Hooks
   refresh them by themselves when the project's structure changes (option `auto_setup`).

## Output to the user (in their language)

- What was installed / wired / indexed, with the `codegraph status` numbers, and the skills
  written (they can be committed to share with the team).
- If the CLI was installed in this session: **restart Claude Code** (or start a new session) so
  the plugin's MCP server starts and `codegraph_explore` loads; until then use
  `codegraph explore "<question>"` in Bash.
- Undo: `codegraph uninit` (this project), `codegraph uninstall` (everything).

## After setup: how to look up code

1. `codegraph_explore` MCP tool (subagents and shell: `codegraph explore "<question>"`) for
   "where is X", "how does X work", "what calls X", "what breaks if I change X".
2. Trust its returned source as already read; read a file only for lines it did not return.
3. Grep/Glob only for what a code graph cannot know: string literals, config, docs.
4. Impact before editing: `codegraph impact <symbol>`; tests to run after:
   `git diff --name-only | codegraph affected --stdin --quiet`.
