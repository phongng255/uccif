---
name: resume
description: "Resume work saved in UCCIF task memory in Codex. Use for $uccif:resume or a request to continue a recorded UCCIF task; recheck stale progress before editing."
---

Use Python 3.8+ and the [bundled UCCIF entry point](../../core/scripts/uccif_main.py).
Resolve that link relative to this SKILL.md directory, not the project cwd.
In the commands below, `UCCIF` means the Python interpreter followed by that
resolved absolute script path, quoted separately for the current shell.
Run from the user's project directory. Do not run a literal executable named UCCIF.
This plugin does not install hooks or automatically track edits.

# Resume a saved task

1. Run `UCCIF task show`. If no task exists, say so; do not invent prior work.
2. Check `git status --short`, relevant history since the checkpoint and the recorded files.
3. Recheck only facts that may be stale, then continue the recorded next step. If it is
   already done, update it with `UCCIF task checkpoint --next "..."` first.
4. Hooks are not enabled by this setup. After actual changes, checkpoint the modified files
   with repeated `--file` arguments, actual test results with `--test`, and the next step.
   Start a task with `task start "title" --type <supported-type>` only if needed; consult
   `UCCIF task start --help` instead of guessing the type.
5. Close only when work is done, recording decisions/issues or `--no-findings` explicitly.
Summarize verified progress in the user's language. Do not claim automatic tracking.
