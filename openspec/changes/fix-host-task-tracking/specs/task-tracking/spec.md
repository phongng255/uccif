## ADDED Requirements

### Requirement: Antigravity edits are tracked

The system SHALL record the file edited by an Antigravity file-editing tool in the open task,
opening a task first when none is open, whichever supported path argument the tool uses.

#### Scenario: edit_file passes a plain absolute path

- **WHEN** `PostToolUse` reports `edit_file` with `Path` set to an absolute path inside the workspace
- **THEN** the file is listed in the task's modified files relative to the project root

#### Scenario: Path is JSON-quoted

- **WHEN** `PostToolUse` reports `write_file` with `Path` set to a JSON-quoted absolute path
- **THEN** the quotes are removed and the file is listed in the task's modified files

#### Scenario: Path is relative

- **WHEN** `PostToolUse` reports `edit_file` with a relative `Path`
- **THEN** the path is resolved against the first workspace path, not the hook's working directory

#### Scenario: TargetFile keeps working

- **WHEN** `PostToolUse` reports `replace_file_content` with `TargetFile`
- **THEN** the file is listed in the task's modified files

### Requirement: Task text excludes host-added wrappers

The system SHALL remove `system-reminder`, `bash-input`, `bash-stdout` and `bash-stderr` blocks from
a prompt before using it for task titles, new-topic detection or `#quick` detection.

#### Scenario: Prompt mixes a wrapper and user text

- **WHEN** a prompt holds a `system-reminder` block followed by user text and the next edit opens a task
- **THEN** the task title comes only from the user text

#### Scenario: Wrapper is cut off

- **WHEN** a prompt holds an opening wrapper tag with no closing tag
- **THEN** the text from that tag to the end of the prompt is removed

#### Scenario: User writes a tag of their own

- **WHEN** a prompt contains a tag not in the wrapper list
- **THEN** the tag stays in the text

### Requirement: Shell-only prompts are not requests

The system SHALL NOT treat a prompt made only of wrappers as a new request.

#### Scenario: User runs a shell command between edits

- **WHEN** a wrapper-only prompt arrives while a task is open
- **THEN** the stored prompt and edited flag are unchanged, and the open task is neither closed nor replaced
