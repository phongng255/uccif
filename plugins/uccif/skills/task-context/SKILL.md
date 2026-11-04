---
name: task-context
description: Use before fixing a bug, adding a feature, writing tests or changing UI — decides the scope, which files to read, what information is missing and the risks, and opens the UCCIF task so progress survives /clear and compaction.
---

# Task context

## Steps

1. Classify: `bug | feature | refactor | review | test | explore | ui`. Ops work (run, inspect,
   configure, logs) needs no task — just do it.
2. If `uccif task show` has an open task: related → continue it (`uccif:resume`); unrelated →
   `uccif task close` it first (`--no-findings` if nothing worth keeping).
3. `uccif task start "<title>" --type <type> --goal "<one line>"` — run it as its own command.
   Add `--rewrite` only if the user asked for a rewrite of an existing file.
4. Scope: load the `<project>-mod-*` skill of the modules involved, then use
   `uccif:smart-code-search`. List the files to read/change and the open questions.
5. Constraints from the user's prompt ("don't change logic", "use tokens", "keep light theme")
   are acceptance criteria. Write them into the goal; at the end report each one as
   met / not met with `file:line`.
6. Shared code (interface, store, props, type used in many files) or `refactor` →
   `uccif:code-impact-analysis` before editing.
7. Edit existing files with Edit; Write only for new files or an agreed rewrite.
8. After the change: run the related tests → `uccif task checkpoint --test "<cmd>: <result>"
   --next "<next step>"`. Record what is worth keeping with `--decision` / `--issue`.
9. Done → `uccif task close --decision … | --issue … | --no-findings`.
   ≥ 3 files changed or user constraints present → run `uccif:change-reviewer` first.

## Debugging (type bug)

1. Reproduce, or describe the exact symptom.
2. Hypothesis with `file:line` evidence; verify before changing code.
3. Fix, then re-check with the same reproduction.
4. Two failed fixes → stop guessing: collect logs/console/network, or ask the user for repro
   steps. Record rejected hypotheses with `uccif task checkpoint --issue`.

## When to use an agent

Only when much reading must shrink to a short answer: `uccif:project-analyst` (module purpose unclear), `uccif:code-impact-analyzer` (shared change), `uccif:change-reviewer`
(before close, per step 9). Not when the file is known or one search answers it.

## Output

Short plan: files, open questions, risks, tests to run.
