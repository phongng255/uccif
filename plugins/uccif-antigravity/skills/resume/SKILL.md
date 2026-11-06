---
name: resume
description: Pick up earlier work from UCCIF task memory: show the open task, check what changed since its last checkpoint, re-verify what may be stale, and continue from its next step. Use this whenever the user wants to continue ("tiếp tục", "làm tiếp", "continue", "where were we", "what was I doing", "việc hôm qua"), or a hook reports an open UCCIF task the request relates to, even if they do not mention a task.
---
<!-- generated from plugins/uccif/skills by plugins/uccif/scripts/build_antigravity.py; edit the source -->

# Resume

Task memory survives turns and `/clear`, but the code may have moved since it was written: the
user, another session or a `git pull` can have changed files, fixed what was open or made the
next step pointless. So treat the task as a lead to check, not as the truth.

## Steps

1. `uccif task show`. No open task → say so plainly instead of guessing what the user meant, and
   offer the latest closed task from `uccif log sessions --days 7` if it looks related.
2. Check what changed since `Last updated`:
   `git status --short`, `git log --oneline --since="<Last updated>"`, and
   `git diff --stat` for the files listed under *Files modified*.
3. Re-verify only what may be stale: files edited outside this task, tests listed as failing,
   decisions that depend on code that has since changed. Look them up with CodeGraph and read
   only those ranges.
4. Continue from *Next step*. If it is already done or no longer valid, say why and update it
   first, so the next session does not repeat the check:
   `uccif task checkpoint --next "<new next step>"`.

## Output (in the user's language)

- Task, goal, status in 2–3 lines.
- What changed since the last checkpoint.
- The next step you are now taking, then take it.
