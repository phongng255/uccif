---
name: resume
description: Use when the user wants to continue earlier work ("tiếp tục", "continue", "what was I doing") or a hook reports an open UCCIF task the request relates to.
---
<!-- generated from plugins/uccif/skills by plugins/uccif/scripts/build_gemini.py; edit the source -->

# Resume

## Steps

1. `uccif task show`. No open task → say so, and offer the latest closed task from
   `uccif log sessions --days 7` if it looks related.
2. Check what changed since `Last updated`:
   `git status --short`, `git log --oneline --since="<Last updated>"`, and
   `git diff --stat` for the files listed under *Files modified*.
3. Re-verify anything that may be stale: files edited outside this task, tests listed as
   failing, decisions that depend on code that has since changed. Read only those ranges.
4. Continue from *Next step*. If it is no longer valid, update it:
   `uccif task checkpoint --next "<new next step>"`.

## Output (in the user's language)

- Task, goal, status in 2–3 lines.
- What changed since the last checkpoint.
- The next step you are now taking — then take it.
