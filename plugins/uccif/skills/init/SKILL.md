---
name: init
description: Survey this repository once and write UCCIF project docs (.gemini/uccif/ or .claude/uccif/: summary.md, architecture.md) plus the project's UCCIF block in GEMINI.md / AGENTS.md / CLAUDE.md. Use when a hook says the project is not surveyed yet, before the first code change in a new repo, when the user asks to set up or refresh UCCIF, or when migrating from UCCIF v2.
argument-hint: "[refresh]"
---

# UCCIF init — limited project survey

Goal: give future sessions enough project knowledge to find code without re-scanning the repo,
at the lowest token cost. Read little, write short, mark every claim.

## Steps

1. **Mechanical survey.** `uccif detect` (JSON); `detect.codegraph.indexed` false → run the
   `uccif:codegraph` skill first. Then read the generated `<project>-map` skill (modules, routes,
   entry points, commands) and map the rest with `codegraph explore` / `codegraph files`, not by
   opening files. Do not re-derive what these report.
2. **Choose the reader.**
   - `large_repo: false` → survey yourself.
   - `large_repo: true` → delegate to the `uccif:project-analyst` agent, one call per top-level
     module, and use only its summaries.
3. **Read at most ~25 files**: manifests, entry candidates, router/DI/build config, and one
   representative file per top-level source dir. Use offset/limit; never read lockfiles,
   generated or minified files. Skip anything already in existing docs unless `$ARGUMENTS`
   is `refresh`.
4. **Determine docs directory & rules file**:
   - On **Antigravity / Gemini CLI** (or if project already uses `.gemini/`): use `.gemini/uccif/` and `GEMINI.md` (or `AGENTS.md`).
   - On **Claude Code** (or if project already uses `.claude/`): use `.claude/uccif/` and `CLAUDE.md`.
5. **Write `<docs_dir>/summary.md`** (≤ 40 lines): what the project does, stack, how to
   run/build/test (exact commands from `detect`), top-level layout, external services.
6. **Write `<docs_dir>/architecture.md`**: one section per module — responsibility, entry
   points, main dependencies, conventions. Every behaviour claim ends with
   `[src: path/to/file]` (a file, not a dir) and a tag `verified` (you read it), `inferred`
   (from names/structure) or `unknown`. Directories in `[src:]` only for structure claims.
   Merge into existing files: keep the user's text, update only stale sections.
7. **Prepare the Rules file block** — project facts only, ≤ 30 lines, never the CORE RULES
   (hooks inject those):
   ```
   <!-- UCCIF:BEGIN -->
   ## Project (UCCIF)
   <3–5 line summary>  · Docs: <docs_dir>/summary.md, architecture.md
   ## Commands
   <build / test / lint / run, exact>
   ## Conventions
   <only conventions a newcomer would get wrong; each with [src:]>
   <!-- UCCIF:END -->
   ```
   Show the block (or the diff against an existing block) to the user and **ask before
   writing GEMINI.md / AGENTS.md / CLAUDE.md**. Replace only the text between the markers; never touch the rest.
8. **UCCIF v2 migration** (only if `detect.uccif_v2` is non-empty). Do not delete anything.
   - Read `.claude/settings.json` / `settings.local.json`; list the exact hook entries that
     call `uccif.py`, with line numbers, and any `deny`/`ask` rules v2 added.
   - Keep `.claude/data/project/*` — copy useful facts into the new docs (re-tag them).
   - Suggest, not perform, removing `.claude/scripts/uccif.py` and `.claude/data/` afterwards.
9. **User rules file.** Only if `<docs_dir>/rules.md` is missing, create it holding one
   comment: `<!-- Project rules, one per line, max 15 loaded after the core rules. e.g.
   Run npm run lint before saying a change is done. Every project: ~/.gemini/uccif/rules.md or ~/.claude/uccif/rules.md -->`.
10. **Baseline.** After writing the docs run `uccif drift ack`, so later structural changes
   (new module, new dependency) are reported to you automatically.
11. **Check.** Run `uccif doctor`; report its WARN lines only (INFO lines need nothing).
   LSP: only a language in `detect.lsp` with `installed: false` is worth one question —
   offer its `install` command; never install unasked. Languages in `detect.no_lsp` (e.g. vue)
   have no LSP in this plugin and are covered by CodeGraph: do not mention or ask.

## Output to the user (in their language)

- Files written/updated, each with one line on its role.
- Stack and commands found.
- Claims tagged `inferred`/`unknown` that the user could confirm.
- Files to commit: `<docs_dir>/` docs and `<docs_dir>/.gitignore` (UCCIF's own; it keeps
  `.local/` out of git). State this in one line; do not ask about them, and commit only if the
  user asks. Unrelated untracked files are not init's business: leave them alone.
- What still needs the user: rules file approval and an LSP install only
  when a configured language server is missing.

## Never

Edit source code; install anything; read `.env` or secrets; claim a command works without
running it; write empty placeholder docs (create decisions.md / known-issues.md only through
`uccif task checkpoint --decision/--issue`).
