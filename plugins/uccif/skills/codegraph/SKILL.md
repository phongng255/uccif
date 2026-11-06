---
name: codegraph
description: Install, index, re-index or repair CodeGraph (the code graph UCCIF uses instead of Grep/Read) for this project, then write the project skills from it. Use this whenever the user says yes to installing CodeGraph, asks to set it up, re-index or refresh it ("reindex", "index cũ rồi", "cài codegraph"), or when `codegraph_explore` / `codegraph` fails, returns nothing for code that exists, or a hook says the CLI or the index is missing — even if the user does not name the skill.
argument-hint: "[reindex]"
---

# CodeGraph setup

UCCIF has no code index of its own: CodeGraph is the index, and every later lookup (core rule 2)
depends on it. Run every step yourself; the only thing the user does is restart Claude Code at the
end, because only a restart loads a newly installed MCP server.

**Package name:** always `@colbymchenry/codegraph`. Never `npx codegraph`: the unscoped npm
package `codegraph` is an unrelated project with no CLI, so it fails in confusing ways.

## Steps

1. **State.** Run `uccif codegraph`. It prints JSON (`cli`, `indexed`, `mcp`, `gitignored`); skip
   every step that is already done, so a repair never reinstalls what works.
   `$ARGUMENTS` = `reindex` → go to step 4 with `codegraph index --force`.
2. **CLI** (only if `cli` is null). The user asked for this skill or agreed to it, so install:
   - Node available (`node -v`): `npm install -g @colbymchenry/codegraph`.
   - The global install fails (EACCES, read-only prefix, sandbox): do not retry with `sudo` or
     change npm's prefix, both touch the user's machine beyond this project. Use
     `npx -y @colbymchenry/codegraph <command>` in place of `codegraph <command>` for the rest of
     this skill, and tell the user the CLI is not on PATH yet.
   - No Node: show the user the official installer and ask before running it, since it installs
     outside the project:
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
4. **Index this project** (only if `indexed` is false, or for a re-index): `codegraph init --yes`
   at the project root. It builds `.codegraph/` and keeps it in sync by itself afterwards, so no
   `sync` step is needed. For a stale or broken index, `codegraph index --force` rebuilds it.
5. **Git.** If `gitignored` is false, append `.codegraph/` to `.gitignore`: the index is local,
   machine-specific data and must never be committed.
6. **Check.** `codegraph status` must show files and symbols. Then try one real lookup on the
   main entry point or a module name, `codegraph explore "<name>"`, so you report a working
   index, not just a finished command.
7. **Project skills.** `uccif skills generate` writes `.claude/skills/<project>-map`,
   `<project>-bugfix` and one `<project>-mod-*` per sizeable module from the graph. Hooks
   refresh them by themselves when the project's structure changes (option `auto_setup`).

## Output to the user (in their language)

- What was installed / wired / indexed, with the `codegraph status` numbers, and the skills
  written (they can be committed to share with the team).
- If the CLI was installed in this session: **restart Claude Code** (or start a new session) so
  the plugin's MCP server starts and `codegraph_explore` loads; until then use
  `codegraph explore "<question>"` in Bash. Say this plainly: without the restart the next
  lookups go through the slower CLI.
- Undo: `codegraph uninit` (this project), `codegraph uninstall` (everything).

Afterwards, look code up as UCCIF core rule 2 says: CodeGraph first, the project skills for where
things live, Read/Grep only for what the graph did not return.
