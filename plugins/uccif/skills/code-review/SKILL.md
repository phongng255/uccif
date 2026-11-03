---
name: code-review
description: Use when asked to review a change, diff, branch or PR, or before closing a task that changed several files — checks logic, hidden bugs, security, compatibility, project conventions and the user's stated constraints.
---

# Code review

## Steps

1. Get the change: `git diff` (working tree), `git diff <base>...HEAD` (branch) or the PR diff.
2. Collect constraints: the user's words in this task plus conventions in
   `.claude/uccif/architecture.md`.
3. ≥ 3 files, or constraints present → delegate to the `uccif:change-reviewer` agent with the
   diff range and the constraint list. Otherwise review yourself.
4. Verify every finding you report by reading its `file:line`. Drop what you cannot verify,
   or list it under "Not checked".
5. If interfaces changed, add `uccif:code-impact-analysis`.
6. A `violated` constraint must be fixed, or explained to the user — never silently dropped.

## Look for

Logic and edge cases · error handling · security (injection, secrets, auth, unsafe input) ·
concurrency/async · backwards compatibility · tests matching the change · hard-coded values
where the project has tokens/config · dead code left behind.

## Output

1. Constraints: each `met` / `violated` with `file:line`.
2. Findings by severity (high → low), each with `file:line` and a one-line fix.
3. Not checked.
