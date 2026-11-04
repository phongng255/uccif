---
name: codegraph
description: Install, index or repair CodeGraph for this project (CLI, .codegraph/ index, project skills). Use when the user agrees to install it, or asks to set up, re-index or fix it.
---
<!-- generated from plugins/uccif/skills by plugins/uccif/scripts/build_gemini.py; edit the source -->

# CodeGraph setup

UCCIF has no code index of its own: CodeGraph is the index. Run every step yourself; the
user only restarts Gemini CLI at the end.

**Package name:** always `@colbymchenry/codegraph`. Never `npx codegraph` — the unscoped
npm package `codegraph` is an unrelated project with no CLI.

## Steps

1. **State.** Run `uccif codegraph` (JSON: `cli`, `indexed`, `mcp`, `gitignored`). Skip the
   steps that are already done. The user asked to re-index → go to step 4 with `codegraph index --force`.
2. **CLI** (only if `cli` is null). The user asked for this skill or agreed to it, so install:
   - Node available (`node -v`): `npm install -g @colbymchenry/codegraph`.
   - npm global fails (EACCES, sandbox): use `npx -y @colbymchenry/codegraph <command>` in
     place of `codegraph <command>` for the rest of this skill.
   - No Node: show the user the official installer and ask before running it:
     `curl -fsSL https://raw.githubusercontent.com/colbymchenry/codegraph/main/install.sh | sh`
     (Windows PowerShell: `irm https://raw.githubusercontent.com/colbymchenry/codegraph/main/install.ps1 | iex`).
3. **MCP tool.** Nothing to run: the extension declares the server itself
   (`gemini-extension.json`: `codegraph serve --mcp`). It starts once the CLI is on PATH, after
   a restart of Gemini CLI. Do **not** run `codegraph install`: it would register a second
   server with the same tools.
4. **Index this project** (only if `indexed` is false): `codegraph init --yes` at the project
   root. It builds `.codegraph/` and keeps it in sync by itself afterwards (no `sync` needed).
5. **Git.** If `gitignored` is false, append `.codegraph/` to `.gitignore` (the index is local,
   machine-specific data; never commit it).
6. **Check.** `codegraph status` must show files and symbols. Then try one real lookup:
   `codegraph explore "<main entry point or a module name>"`.
7. **Project skills.** `uccif skills generate` writes `.agents/skills/<project>-map`,
   `<project>-bugfix` and one `<project>-mod-*` per sizeable module from the graph. Hooks
   refresh them by themselves when the project's structure changes (option `auto_setup`).

## Output to the user (in their language)

- What was installed / wired / indexed, with the `codegraph status` numbers, and the skills
  written (they can be committed to share with the team).
- If the CLI was installed in this session: **restart Gemini CLI** (or start a new session) so
  the extension's MCP server starts and `codegraph_explore` loads; until then use
  `codegraph explore "<question>"` with run_shell_command.
- Undo: `codegraph uninit` (this project), `codegraph uninstall` (everything).

Afterwards lookups follow UCCIF core rule 2.
