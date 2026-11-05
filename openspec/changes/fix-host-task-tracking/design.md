# Design

## Evidence

| Host | Check | Result |
|---|---|---|
| Antigravity | `post-tool-use` records | 269 (`Edit` 259, `Write` 10), all `skip`, all `target=None` |
| Antigravity | Path argument in transcripts | `edit_file` and `write_file` use `Path`; `replace_file_content` and `write_to_file` use `TargetFile` |
| Antigravity | Shape of `Path` in transcripts | 1487 of 1487 start with `"/`, an absolute path wrapped in JSON quotes |
| Claude Code | `post-tool-use` records with an edit | 44 of 44 carry a target |
| Claude Code | Task titles | wrapper text found in real titles |

Not known: whether the hook's stdin carries `Path` quoted as the transcript does, because hook
logs do not store raw input. Task 1.1 settles this; the code accepts both shapes either way.

## Decisions

### Normalize the path in `_normalize_antigravity`

Add `Path` to `ANTIGRAVITY_PATH_ARGS`, then normalize the value in one helper:

1. If the value is a JSON-quoted string, decode it. Leave anything undecodable unchanged.
2. If the result is relative, join it to `workspacePaths[0]`.

`hosts.py` already translates host input into Claude's shape, so `on_post_tool_use` stays
host-independent and `_rel` needs no change.

### Clean the prompt in `on_user_prompt_submit`

Add `_title_text(prompt)`, which removes `system-reminder`, `bash-input`, `bash-stdout` and
`bash-stderr` blocks, including an unterminated block cut off by truncation. Clean before the
`[:400]` cut, so a long wrapper cannot use up the stored text.

If nothing remains, return early: keep `last_prompt.txt` and `prompt_edited.flag`. A command typed
by the user is not a new request, so it must not open a new task or close the current one.

`#quick` detection keeps reading the cleaned text, so a flag inside command output cannot trigger it.

## Alternatives

- **Clean only in `_new_auto`:** rejected, because `is_new_topic` would still read the wrappers.
- **Strip every XML-like tag:** rejected, because a user may write tags in a real prompt.

## Risks

- App wrapper names can change. A new wrapper then gives a bad title again, which is cosmetic.
- Antigravity may add other path argument names. The `target=None` log signal exposes that, and
  `uccif doctor` is not changed here.
