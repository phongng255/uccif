# Change: Fix task tracking on Antigravity and task titles on Claude Code

## Why

Hook logs and transcripts on the maintainer's machine (2026-11-05) show two defects in the
automatic task memory, on the two hosts UCCIF actively supports.

- **Antigravity:** all 269 logged `post-tool-use` events were skipped with `target=None`, so no
  task opened and no modified file was recorded. Transcripts show `edit_file` (1204 calls) and
  `write_file` (283 calls) pass the file as `Path`, which `ANTIGRAVITY_PATH_ARGS` does not list.
  The guides promise this feature for the Antigravity CLI.
- **Claude Code:** the raw prompt is stored as the task title source, including wrappers the app
  adds. Real titles include `<bash-input>gemini extensions update uccif...` and
  `<system-reminder> ## The user forked...`. The same text feeds new-topic detection, so wrappers
  can also affect whether a task is closed.

## What Changes

- Read the edited file path from `Path` on Antigravity, and accept both a plain value and a
  JSON-quoted one (transcripts store `"/abs/path"` with the quotes).
- Resolve a relative path against the workspace, not the hook's cwd (the plugin root).
- Remove host-added wrappers from the prompt before it is used for titles and topic detection.
- Treat a prompt that is only wrappers (a shell command typed by the user) as no new prompt.
- Add regression tests using the argument shapes seen in real transcripts.

## Impact

- Affected specs: `task-tracking` (new)
- Affected code: `plugins/uccif/uccif_lib/hosts.py`, `plugins/uccif/uccif_lib/hooks.py`,
  `tests/test_antigravity.py`, `tests/test_hooks.py`
- Generated files: the Antigravity plugin's `core` must stay in sync; run both build scripts.
- Gemini CLI shares the wrapper removal but has no behaviour change for normal prompts.

## Non-Goals

- Showing the token line on Antigravity: the host has no user-only text channel on `Stop`.
- Reading Antigravity token counts into `usage.jsonl`: feasible, since `PLANNER_RESPONSE` steps
  carry `input_tokens`, `cache_read_tokens` and `output_tokens`, but it is a feature. Propose it
  separately.
- `no workspacePaths in the hook input` (111 errors between 16:26 and 16:44 on 2026-11-04, none
  since): cause unknown and the hook fails safely. Watch it; do not change it here.
- `hosts.json.tmp` race (one error at 21:21 on 2026-11-04): it predates the 1.2.0 concurrent-write
  fix (21:40 the same day) and has not recurred.
- Repeated "notes are stale" reminders in `thailand-trip-3n2d` (114): a state of that project, to
  be cleared there with `uccif drift ack` after updating its notes.
