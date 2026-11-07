---
name: uccif-init
description: Write the project notes the code graph cannot know (what the project is for, conventions a newcomer would get wrong, external services) to .agents/uccif/summary.md and a short UCCIF block in AGENTS.md, with test commands verified. Use this when the user runs /uccif-init, asks to set up, initialise or refresh UCCIF for a project ("init uccif", "ghi summary", "cập nhật ghi chú dự án"), or a hook says the project notes are stale. Not for code changes.
---
<!-- generated from plugins/uccif/skills by plugins/uccif/scripts/build_antigravity.py; edit the source -->

# UCCIF init: the notes the graph does not have

The `<project>-map` and `-mod-*` skills already hold modules, entry points, routes and commands,
generated from CodeGraph and refreshed by hooks. Init exists only for the facts no index can
derive, so re-deriving the layout here would just duplicate the map and drift from it.

Budget: about 7 tool calls, at most 10. Run each command on its own (no `;`, `&&`, `echo`):
compound commands need the user's approval, and this skill should run without prompts.

1. `uccif detect`. If `codegraph.indexed` is false, run the `uccif-codegraph` skill first: the
   notes point to the map skill, which needs the index.
2. Load the `<project>-map` skill, so you know the layout without reading files for it.
3. Read at most 4 files, in one parallel batch, with offset/limit: README, the main manifest, and
   up to 2 of: the existing `.agents/uccif/summary.md`, CONTRIBUTING / AGENTS.md, an env example
   (`.env.example`). Never lockfiles or generated files, and never `.env` or any file that may
   hold secrets: an external service is named in the env example or the code, and reading a key
   would put it in the transcript.
4. Pipe the summary into `uccif summary write` (heredoc; `--replace` if one exists, merged with
   the user's text). **At most 20 lines, only what the graph cannot know**: what the project is
   for, conventions a newcomer would get wrong, external services. End each claim with
   `[src: file]` so a reader can check it. No modules, commands or layout, and nothing CLAUDE.md /
   AGENTS.md already says (the agent reads those anyway): point to them instead.
   Write under `.agents/uccif/` only through these `uccif` commands. The command also stores the drift baseline that later
   tells you when these notes go stale.
5. `uccif verify-tests`, once. It lists the tests (vitest list, jest --listTests, pytest
   --collect-only, go test -list, cargo test -- --list) or runs them only when the runner has no
   list mode, with a 60 s timeout, installing nothing. Whatever it prints, do not retry, try
   another command or install anything: a command it could not verify is marked `(unverified)`,
   which is the honest result.
6. Pipe 2–3 description lines into `uccif agents-md write` (heredoc). It composes the block of
   at most 15 lines (commands from the manifests, `(unverified)` next to those not verified, a
   pointer to the map skill) and writes it to AGENTS.md (CLAUDE.md imports it, or gets a copy).
   Exit 3 means a block already exists: show the user the change and ask before rerunning with
   `--replace`, because that block may hold their edits. Without an answer, stop there.

Reply in the user's language, in at most 5 lines: the files written and what the user may want to
confirm. Never edit source code, install anything, read secrets or write placeholder docs.
