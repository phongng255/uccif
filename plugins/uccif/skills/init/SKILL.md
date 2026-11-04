---
name: init
description: Optional. Writes what the code graph cannot know (purpose, conventions, external services) to .claude/uccif/summary.md and a small CLAUDE.md block. Use when the user asks to set up or refresh UCCIF notes.
argument-hint: "[refresh]"
---

# UCCIF init — notes the graph does not have

The `<project>-map` / `-mod-*` skills already hold modules, entry points, routes and commands:
do not re-derive them. Budget: ≤ 10 tool calls (normally 7). Run every command on its own (no `;`, `&&`,
`echo`): compound commands need approval.

1. `uccif detect`. `codegraph.indexed` false → run the `uccif:codegraph` skill first.
2. Load the `<project>-map` skill.
3. Read at most 4 files, in one parallel batch, offset/limit: README, main manifest, and
   up to 2 of: the existing `.claude/uccif/summary.md`, CONTRIBUTING / AGENTS.md, an env example.
   Never lockfiles, generated files, `.env`.
4. Pipe the summary into `uccif summary write` (heredoc; `--replace` if one exists, merged with
   the user's text). **≤ 20 lines, only what the graph cannot know**: what the project is for,
   conventions a newcomer would get wrong, external services. Each claim ends with
   `[src: file]`. No modules, commands or layout, and nothing CLAUDE.md / AGENTS.md already
   says (Claude Code loads those anyway): point to them instead. Never use Write/Edit under `.claude/`.
   The command also stores the drift baseline.
5. `uccif verify-tests`, once: it lists the tests (vitest list, jest --listTests, pytest
   --collect-only, go test -list, cargo test -- --list) or runs them only when the runner has no
   list mode, with a 60 s timeout, installing nothing. Whatever it prints, do not retry, do not
   try another command, do not install anything: an unverified command is marked as such.
6. Pipe 2–3 description lines into `uccif claude-md write` (heredoc). It composes the ≤ 15-line
   block (commands from the manifests, `(unverified)` next to those not verified, a pointer to the
   map skill) and appends it at the end of CLAUDE.md. Exit 3 = a block exists: show the change,
   ask, rerun with `--replace`.
7. UCCIF v2 (`detect.uccif_v2` non-empty): list the hook lines calling `uccif.py` in
   `.claude/settings*.json` for the user to remove. Delete nothing yourself.

Reply in the user's language, ≤ 5 lines: files written, what the user may want to confirm.
Never: edit source code, install anything, read secrets, write placeholder docs.
