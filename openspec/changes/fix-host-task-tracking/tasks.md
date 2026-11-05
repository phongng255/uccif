# Tasks

## 1. Antigravity: file path

- [ ] 1.1 Capture one real `PostToolUse` stdin from `agy` and record whether `Path` is quoted
- [x] 1.2 Add failing tests for `edit_file` and `write_file` with plain, quoted and relative `Path`
- [x] 1.3 Add `Path` to `ANTIGRAVITY_PATH_ARGS` and the normalize helper in `hosts.py`

## 2. Claude Code: task title

- [x] 2.1 Add failing tests: wrapper with text, wrapper only, unterminated wrapper, tag-like user text
- [x] 2.2 Add `_title_text` and use it in `on_user_prompt_submit`
- [x] 2.3 Return early on a wrapper-only prompt, keeping the stored prompt and edited flag

## 3. Verify

- [x] 3.1 Run `python3 -m pytest -q`
- [x] 3.2 Run both build scripts, then both with `--check`
- [ ] 3.3 Install the build in `agy`, edit a file in a test project, and confirm `uccif task show` lists it
- [ ] 3.4 In Claude Code, run a `!` shell command, then edit a file, and confirm the title is clean
- [x] 3.5 Update the changelog
