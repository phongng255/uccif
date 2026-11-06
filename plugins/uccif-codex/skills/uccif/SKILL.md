---
name: uccif
description: "Use UCCIF in Codex chat: initialize project notes, resume saved work, or set up CodeGraph. Use when the user mentions $uccif:uccif, uccif init/resume/codegraph, or asks for the UCCIF menu. Not for unrelated coding requests."
---

Use Python 3.8+ and the [bundled UCCIF entry point](../../core/scripts/uccif_main.py).
Resolve that link relative to this SKILL.md directory, not the project cwd.
In the commands below, `UCCIF` means the Python interpreter followed by that
resolved absolute script path, quoted separately for the current shell.
Run from the user's project directory. Do not run a literal executable named UCCIF.
This plugin does not install hooks or automatically track edits.

# UCCIF for Codex

Read the request after the skill mention as normal user text, not shell code.
- init / initialize project notes: follow the `uccif:init` skill.
- resume / continue saved work: follow `uccif:resume`.
- codegraph / index / reindex: follow `uccif:codegraph`.
- status: run `UCCIF task show`, then `UCCIF doctor --host codex`.
If no action is supplied, show these four choices in the user's language and wait.
Do not invent a slash command or silently execute an unknown action.
