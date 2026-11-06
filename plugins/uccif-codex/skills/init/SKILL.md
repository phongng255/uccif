---
name: init
description: "Initialize or refresh UCCIF project notes in Codex. Use for $uccif:init, initializing UCCIF, or updating project purpose and conventions. Not source changes."
---

Use Python 3.8+ and the [bundled UCCIF entry point](../../core/scripts/uccif_main.py).
Resolve that link relative to this SKILL.md directory, not the project cwd.
In the commands below, `UCCIF` means the Python interpreter followed by that
resolved absolute script path, quoted separately for the current shell.
Run from the user's project directory. Do not run a literal executable named UCCIF.
This plugin does not install hooks or automatically track edits.

# Initialize UCCIF notes

1. Run `UCCIF detect` from the project working directory.
2. Read README, the main manifest, AGENTS.md and existing `.claude/uccif/summary.md` if present.
   Read at most four relevant files; never read secrets or real .env files.
3. Record only verified purpose, unusual conventions and named external services, at most
   20 lines. Cite each claim with `[src: path]`; do not invent facts or duplicate the code map.
4. Send the text on stdin to `UCCIF summary write`. If notes exist, show the merged
   change before using `--replace`; preserve user edits. Do not write CLAUDE.md.
5. Run `UCCIF verify-tests` once; report unverified commands honestly.
6. If CodeGraph is already indexed, run `UCCIF skills generate --host codex`.
   Otherwise offer the CodeGraph workflow separately; notes do not require installing it.
Reply in the user's language with the files written and facts needing confirmation.
