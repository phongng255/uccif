---
name: init
description: Optional. Writes what the code graph cannot know (project purpose, conventions, external services) to .claude/uccif/summary.md and a small CLAUDE.md block. Use when the user asks to set up or refresh UCCIF project notes, or migrate from UCCIF v2.
argument-hint: "[refresh]"
---

# UCCIF init — notes the graph does not have

The `<project>-map` / `-mod-*` skills (generated from CodeGraph) already hold modules, entry
points, routes and commands: do not re-derive them. Budget: ≤ 10 tool calls, ≤ 8 files read.

1. `uccif detect` (JSON). `codegraph.indexed` false → run the `uccif:codegraph` skill first.
   Then load the `<project>-map` skill. These two calls are the whole mechanical survey.
2. Read at most 8 files, in one parallel batch, with offset/limit: README, the main
   manifest, the main entry (`detect.entry_candidates`), and at most 5 more only for something the
   README leaves open (config, CI, env example). Never lockfiles, generated files, `.env`.
   `large_repo` is no reason to read more.
3. Write `.claude/uccif/summary.md`, **≤ 20 lines, only what the graph cannot know**:
   what the project is for, conventions a newcomer would get wrong, external services
   (DB, APIs, queues, deploy target). Each claim ends with `[src: file]`. No module list, no
   commands, no layout. Merge with an existing file: keep the user's text, edit stale lines.
4. CLAUDE.md block: pipe 2–3 description lines into `uccif claude-md write` (heredoc). The
   command composes the block itself (≤ 15 lines: description, build/test/lint commands from
   the manifests, one line pointing to the map skill) and appends it at the end of CLAUDE.md,
   never touching the text above it. Block already present: it exits 3; show the user what
   changes, ask, rerun with `--replace`.
5. `uccif drift ack` (stores the baseline). Report `uccif doctor` WARN lines only if you ran it.
6. UCCIF v2 (`detect.uccif_v2` non-empty): list the hook entries calling `uccif.py` with line
   numbers for the user to remove from `.claude/settings*.json` (Claude Code protects that file;
   running v2 and v3 hooks together double-logs). Delete nothing yourself.

Reply in the user's language, ≤ 6 lines: files written, and what the user may want to confirm.
Commit `.claude/uccif/summary.md` and the CLAUDE.md block only if asked.

Never: edit source code, install anything, read secrets, write empty placeholder docs.
