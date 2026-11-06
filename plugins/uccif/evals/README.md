# UCCIF evals

Behaviour tests for the plugin's skills, run with real Claude sessions. One case folder per test,
in the layout `claude plugin eval` reads (`<group>/<case>/prompt.md`, `case.yaml`, `graders/`,
`place-files.sh`):

| Group | What it checks |
|---|---|
| `codegraph/` | the `uccif:codegraph` skill: install from the scoped package, re-index, fall back to `npx` when a global install is denied |
| `init/` | the `uccif:init` skill: short sourced summary, one `verify-tests`, never replace an AGENTS.md block or read `.env` without asking |
| `resume/` | the `uccif:resume` skill: open task, no task, a next step that is already done |
| `project-skills/` | the skills `uccif skills generate` writes (`-map`, `-bugfix`, `-mod-*`) together with the hooks: CodeGraph before Read/Grep, every copy of a bug fixed, impact checked before a rename |

Every case starts from `fixtures/trip-budget/`, a small TypeScript expense tracker for a group trip
(entry kinds `Thu`, `Chi`, `Chuyển`). `fixtures/setup.sh` copies it, makes it a git repository and,
for most cases, indexes it with CodeGraph and generates the project skills from the plugin under
test (`UCCIF_EVAL_PLUGIN`, default: this plugin). `fixtures/trip-budget/dot-env` becomes `.env`:
a fake key that the `init/no-secrets` case checks is never read.

## Run

Requirements: Claude Code 2.1.269 or later, git, python3, and the CodeGraph CLI
(`npm install -g @colbymchenry/codegraph`).

```
claude plugin eval plugins/uccif --scaffold --allow-tools Bash,Write,Edit -j 4
claude plugin eval plugins/uccif --scaffold --allow-tools Bash,Write,Edit --case install-on-yes
```

These are real, billed model runs (about 24 runs with the no-plugin baseline).

Two `codegraph/` cases need a machine state that a scaffold script cannot set:
`install-on-yes` expects no `codegraph` on PATH, and `npm-global-denied` expects `npm install -g`
to fail with EACCES. Run them on a machine (or container) prepared that way, or skip them with
`--case`.
