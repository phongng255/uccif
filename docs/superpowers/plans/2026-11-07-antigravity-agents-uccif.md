# Antigravity .agents/uccif Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable Antigravity in UCCIF to use `.agents/uccif/` for docs and task memory, `.agents/skills/` for generated skills, and never touch or create `.claude/`.

**Architecture:** Add agent environment detection (`ANTIGRAVITY_LS_ADDRESS`, `ANTIGRAVITY_CSRF_TOKEN`, `UCCIF_AGENT`) to `hosts.py` and dynamic `docs_subdir` to `Project` in `paths.py` (preferring existing directories for backwards compatibility, defaulting to `.agents/uccif` on Antigravity). Update `hostfiles.py` and `build_antigravity.py` to adapt skill templates, commands, and links for Antigravity. Verify with full test suite and test in the Antigravity IDE workspace.

**Tech Stack:** Python 3.9+, pytest, Antigravity CLI (`agy`), CodeGraph.

**Spec:** [Design Doc in conversation transcript (2026-11-07)]

## Global Constraints

- Never break backwards compatibility: existing `.claude/uccif/` or `.gemini/uccif/` directories must continue to be respected if present.
- Never write or create `.claude/` when running under Antigravity in a clean repo.
- Python code must remain compatible with Python 3.9+ without new external dependencies.
- All changes must pass `pytest tests/test_antigravity.py tests/test_hosts.py`.
- `plugins/uccif-antigravity/` must always be built via `build_antigravity.py`, never manually edited.

## Review Focus

1. Projects with existing `.claude/uccif/` must NOT have a second `.agents/uccif/` created.
2. Projects in Antigravity without prior setup must write `summary.md` and `.local/` into `.agents/uccif/`.
3. Generated skills on Antigravity must always go to `.agents/skills/` even if `hosts.json` does not exist yet.
4. `AGENTS.md` block written by `uccif agents-md write` must point to `.agents/uccif/summary.md` when on Antigravity.
5. All 52+ tests in `tests/test_antigravity.py` and `test_hosts.py` must pass.

---

### Task 1: Environment Detection and Dynamic `docs_subdir`

**Files:**
- Modify: `plugins/uccif/uccif_lib/hosts.py`
- Modify: `plugins/uccif/uccif_lib/paths.py`
- Test: `tests/test_hosts.py`

- [ ] Add `is_antigravity(project=None)` in `hosts.py` checking `UCCIF_AGENT == 'antigravity'`, `ANTIGRAVITY_LS_ADDRESS`, `ANTIGRAVITY_CSRF_TOKEN`, or presence of `.agents/rules/uccif.md` / `AGENTS.md`.
- [ ] Update `hosts.enabled(project)` in `hosts.py` to include `"antigravity"` when `is_antigravity(project)` is true, preventing fallback to `["claude"]`.
- [ ] In `paths.py`, update `Project`:
  - Add `@property def docs_subdir(self)`:
    - If `(self.root / ".agents" / "uccif").exists()` -> `Path(".agents") / "uccif"`
    - If `(self.root / ".claude" / "uccif").exists()` -> `Path(".claude") / "uccif"`
    - If `(self.root / ".gemini" / "uccif").exists()` -> `Path(".gemini") / "uccif"`
    - If `hosts.is_antigravity(self)`: return `Path(".agents") / "uccif"`
    - Default: `Path(".claude") / "uccif"`
  - Update `Project.docs_dir` to return `self.root / self.docs_subdir`.
- [ ] Run `python3 -m pytest tests/test_hosts.py` to ensure host adapter tests pass.

---

### Task 2: Update CLI and Skill Generation for Dynamic Docs and Skills

**Files:**
- Modify: `plugins/uccif/uccif_lib/cli.py`
- Modify: `plugins/uccif/uccif_lib/skillgen.py`
- Modify: `plugins/uccif/uccif_lib/hooks.py`

- [ ] In `cli.py` `cmd_agents_md_write`: replace hardcoded `.claude/uccif/summary.md` with `f"{proj.docs_subdir.as_posix()}/summary.md"`.
- [ ] In `cli.py` `cmd_summary_show` and `summary write`: ensure messages and paths reference `proj.docs_subdir`.
- [ ] In `skillgen.py` `wants_agents`: ensure `is_antigravity(project)` triggers agents standard.
- [ ] In `hooks.py`: ensure injected system message references `proj.docs_subdir / "summary.md"` instead of hardcoded `.claude/uccif/summary.md`.

---

### Task 3: Antigravity Skill Transformation and Plugin Rebuild

**Files:**
- Modify: `plugins/uccif/uccif_lib/hostfiles.py`
- Modify: `plugins/uccif/scripts/build_antigravity.py`
- Generated: `plugins/uccif-antigravity/`

- [ ] In `hostfiles.py`: in `ANTIGRAVITY` substitutions:
  - Add substitution: replace `.claude/uccif/` with `.agents/uccif/`.
  - Add substitution: replace `uccif skills generate` with `uccif skills generate --host antigravity`.
- [ ] Run `python3 plugins/uccif/scripts/build_antigravity.py` to regenerate `plugins/uccif-antigravity/`.
- [ ] Check `git diff plugins/uccif-antigravity/` to confirm all skill markdown and rules files reflect `.agents/uccif/`.

---

### Task 4: Unit Testing Antigravity Isolation

**Files:**
- Modify: `tests/test_antigravity.py`
- Test: `tests/test_antigravity.py`

- [ ] Add test `test_antigravity_clean_repo_uses_agents_uccif_and_no_claude_folder`:
  - Verify that running `SessionStart`, `uccif summary write`, and `uccif skills generate` on a clean project creates `.agents/uccif/` and `.agents/skills/`, and `.claude/` does NOT exist.
- [ ] Add test `test_antigravity_respects_existing_claude_folder`:
  - Verify that if `.claude/uccif` already exists, Antigravity uses it and does not create `.agents/uccif`.
- [ ] Run full test suite: `python3 -m pytest tests/test_antigravity.py tests/test_hosts.py`.

---

### Task 5: Installation and End-to-End Verification

**Files:**
- Workspace: `/Users/phongdp/.gemini/antigravity/scratch/gemini-issue-coder`
- Installed plugin: `/Users/phongdp/.gemini/config/plugins/uccif`

- [ ] Reinstall plugin using `agy plugin install /Users/phongdp/code/phongng255/uccif/plugins/uccif-antigravity`.
- [ ] In `gemini-issue-coder`:
  - Move/clean up `.claude` folder.
  - Run `uccif summary write` and `uccif skills generate`.
  - Verify that `.agents/uccif/summary.md` and `.agents/skills/` are created and `.claude/` is NOT created.

