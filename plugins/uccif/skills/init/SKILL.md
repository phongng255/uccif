---
name: init
description: Survey this repository once and write UCCIF project docs (.claude/uccif/summary.md, architecture.md) plus the project's UCCIF block in CLAUDE.md. Use when a hook says the project is not surveyed yet, before the first code change in a new repo, when the user asks to set up or refresh UCCIF, or when migrating from UCCIF v2.
argument-hint: "[refresh]"
---

# UCCIF init — limited project survey

Goal: give future sessions enough project knowledge to find code without re-scanning the repo,
at the lowest token cost. Read little, write short, mark every claim.

## Steps

1. **Mechanical survey.** Run `uccif detect` (JSON) and `uccif index status`; use
   `uccif index query --file <entry>` to map imports instead of opening files. Do not re-derive what it reports
   (languages, manifests, scripts, test dirs, entry candidates, LSP status, v2 traces).
2. **Choose the reader.**
   - `large_repo: false` → survey yourself.
   - `large_repo: true` → delegate to the `uccif:project-analyst` agent, one call per top-level
     module, and use only its summaries.
3. **Read at most ~25 files**: manifests, entry candidates, router/DI/build config, and one
   representative file per top-level source dir. Use offset/limit; never read lockfiles,
   generated or minified files. Skip anything already in existing docs unless `$ARGUMENTS`
   is `refresh`.
4. **Write `.claude/uccif/summary.md`** (≤ 40 lines): what the project does, stack, how to
   run/build/test (exact commands from `detect`), top-level layout, external services.
5. **Write `.claude/uccif/architecture.md`**: one section per module — responsibility, entry
   points, main dependencies, conventions. Every behaviour claim ends with
   `[src: path/to/file]` (a file, not a dir) and a tag `verified` (you read it), `inferred`
   (from names/structure) or `unknown`. Directories in `[src:]` only for structure claims.
   Merge into existing files: keep the user's text, update only stale sections.
6. **Prepare the CLAUDE.md block** — project facts only, ≤ 30 lines, never the CORE RULES
   (hooks inject those):
   ```
   <!-- UCCIF:BEGIN -->
   ## Project (UCCIF)
   <3–5 line summary>  · Docs: .claude/uccif/summary.md, architecture.md
   ## Commands
   <build / test / lint / run, exact>
   ## Conventions
   <only conventions a newcomer would get wrong; each with [src:]>
   <!-- UCCIF:END -->
   ```
   Show the block (or the diff against an existing block) to the user and **ask before
   writing CLAUDE.md**. Replace only the text between the markers; never touch the rest.
7. **UCCIF v2 migration** (only if `detect.uccif_v2` is non-empty). Do not delete anything.
   - Read `.claude/settings.json` / `settings.local.json`; list the exact hook entries that
     call `uccif.py`, with line numbers, and any `deny`/`ask` rules v2 added. Claude Code
     protects these files: try one Edit only if the user agrees; if blocked, give the user
     the exact lines to remove. Running v2 and v3 hooks together double-logs and v2 may block.
   - Keep `.claude/data/project/*` — copy useful facts into the new docs (re-tag them).
   - The old v2 CLAUDE.md block (CORE RULES, workflow) is replaced by the v3 block in step 6.
   - Suggest, not perform, removing `.claude/scripts/uccif.py` and `.claude/data/` afterwards.
8. **User rules file.** Only if `.claude/uccif/rules.md` is missing, create it holding one
   comment: `<!-- Project rules for Claude, one per line, max 15 loaded after the core rules. e.g.
   Run npm run lint before saying a change is done. Every project: ~/.claude/uccif/rules.md -->`.
9. **Baseline.** After writing the docs run `uccif drift ack`, so later structural changes
   (new module, new dependency) are reported to you automatically.
10. **Check.** Run `uccif doctor`; report its WARN lines only (INFO lines need nothing).
   LSP: only a language in `detect.lsp` with `installed: false` is worth one question —
   offer its `install` command; never install unasked. Languages in `detect.no_lsp` (e.g. vue)
   have no LSP in this plugin and are covered by the code index: do not mention or ask.

## Output to the user (in their language)

- Files written/updated, each with one line on its role.
- Stack and commands found.
- Claims tagged `inferred`/`unknown` that the user could confirm.
- Files to commit: `.claude/uccif/` docs and `.claude/uccif/.gitignore` (UCCIF's own; it keeps
  `.local/` out of git). State this in one line; do not ask about them, and commit only if the
  user asks. Unrelated untracked files are not init's business: leave them alone.
- What still needs the user: CLAUDE.md approval, v2 settings lines, and an LSP install only
  when a configured language server is missing.

## Never

Edit source code; install anything; read `.env` or secrets; claim a command works without
running it; write empty placeholder docs (create decisions.md / known-issues.md only through
`uccif task checkpoint --decision/--issue`).
