import json

import pytest

from conftest import assistant, hook_log, prompt, run_hook, write_transcript
from uccif_lib import hooks, task


@pytest.fixture
def base(project, tmp_path):
    t = write_transcript(tmp_path / "t.jsonl", [prompt(), assistant("a", 10, 40000, 2000, 300)])
    return {"session_id": "S1", "cwd": str(project.root), "transcript_path": str(t)}


def ctx(out):
    return out["hookSpecificOutput"]["additionalContext"]


@pytest.mark.parametrize("event", sorted(hooks.HANDLERS))
def test_every_hook_exits_0_and_logs_one_line(event, base, project):
    code, _ = run_hook(event, dict(base))
    assert code == 0
    rows = hook_log(project)
    assert len(rows) == 1 and rows[0]["event"] == event and "ms" in rows[0]
    assert rows[0]["decision"] != "error", rows[0]


@pytest.mark.parametrize("raw", ["", "not json", "[]"])
def test_bad_input_never_breaks(raw, project):
    code, out = run_hook("stop", None, raw=raw)
    assert code == 0
    # empty input is a valid (if useless) event: no transcript -> "Token: n/a"
    assert out in (None, {"systemMessage": "🔢 Token: n/a"})
    assert (out is None) == (raw != "")


def test_unknown_event_logged_as_error(base, project):
    assert run_hook("nope", base) == (0, None)
    assert hook_log(project)[0]["decision"] == "error"


def test_no_hook_ever_blocks(base, project):
    for event in hooks.HANDLERS:
        _, out = run_hook(event, dict(base, tool_name="Bash", agent_id="a", agent_type="uccif:change-reviewer",
                                      tool_input={"command": "rm -rf /"}))
        text = json.dumps(out or {})
        assert '"block"' not in text and '"deny"' not in text


def test_session_start_injects_rules_on_startup_and_compact(base, project, tmp_path, monkeypatch):
    env = tmp_path / "env.sh"
    monkeypatch.setenv("CLAUDE_ENV_FILE", str(env))
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_REPLY_LANGUAGE", "en")
    for source in ("startup", "clear", "compact"):
        _, out = run_hook("session-start", dict(base, source=source))
        assert "UCCIF CORE RULES" in ctx(out) and "Reply to the user in en" in ctx(out)
    _, out = run_hook("session-start", dict(base, source="resume"))
    assert "UCCIF CORE RULES" not in ctx(out)
    assert "not been surveyed" in ctx(out)
    assert "export UCCIF_DATA_DIR=" in env.read_text()


def test_session_start_mentions_docs_and_open_task(base, project):
    project.docs_dir.mkdir(parents=True)
    (project.docs_dir / "summary.md").write_text("x")
    task.start(project, "Fix login", "bug")
    _, out = run_hook("session-start", dict(base, source="startup"))
    assert "Project docs: .claude/uccif/" in ctx(out)
    assert "Open task T-001 (bug): Fix login" in ctx(out)


def test_session_start_marks_previous_unclean(base, project):
    from uccif_lib import log
    log.session(project, session="OLD", type="start")
    run_hook("session-start", dict(base, source="startup"))
    ends = [r for r in log.read(project, "sessions.jsonl") if r["type"] == "end"]
    assert ends == [dict(ends[0], session="OLD", reason="unclean")]


def test_user_prompt_submit(base, project):
    _, out = run_hook("user-prompt-submit", dict(base, prompt="hello"))
    assert ctx(out) == "Reply in vi. Do ops work yourself."
    task.start(project, "Fix login", "bug")
    _, out = run_hook("user-prompt-submit", dict(base, prompt="go on"))
    lines = ctx(out).splitlines()
    assert len(lines) <= 3 and lines[0].startswith("Open task T-001")
    _, out = run_hook("user-prompt-submit", dict(base, prompt="#quick fix typo"))
    assert ctx(out) == "Reply in vi. Do ops work yourself."


@pytest.mark.parametrize("agent,cmd,decision", [
    (None, "ls", "skip"),
    ("uccif:change-reviewer", "git diff HEAD", "allow"),
    ("uccif:change-reviewer", "rm -rf build", "would_block"),
    ("uccif:project-analyst", "uccif detect", "allow"),
    ("uccif:project-analyst", "curl x", "would_block"),
    ("Explore", "rm x", "skip"),
])
def test_pre_tool_use_agent_bash(agent, cmd, decision, base, project):
    data = dict(base, tool_name="Bash", tool_input={"command": cmd})
    if agent:
        data.update(agent_id="a1", agent_type=agent)
    code, out = run_hook("pre-tool-use", data)
    assert code == 0 and out is None
    assert hook_log(project)[0]["decision"] == decision


def test_post_tool_use_records_file(base, project):
    task.start(project, "a", "ui")
    run_hook("post-tool-use", dict(base, tool_name="Edit",
                                   tool_input={"file_path": str(project.root / "src" / "a.ts")}))
    run_hook("post-tool-use", dict(base, tool_name="Write",
                                   tool_input={"file_path": str(project.root / ".claude" / "x.md")}))
    run_hook("post-tool-use", dict(base, tool_name="Write", tool_input={"file_path": "/elsewhere/b.ts"}))
    assert task.load_current(project)["files"] == ["src/a.ts"]


def test_post_tool_use_failure_only_for_searches(base, project):
    _, out = run_hook("post-tool-use-failure", dict(
        base, tool_name="Bash", tool_input={"command": "grep -rn foo src"},
        error="Exit code 2\ngrep: src: No such file or directory", is_interrupt=False))
    assert "A search command failed: grep: src: No such file" in ctx(out)
    assert ctx(out).endswith("Then report to the user in vi.")
    _, out = run_hook("post-tool-use-failure", dict(
        base, tool_name="Bash", tool_input={"command": "npm test"}, error="Exit code 1"))
    assert out is None
    _, out = run_hook("post-tool-use-failure", dict(
        base, tool_name="Grep", tool_input={}, error="x", is_interrupt=True))
    assert out is None


def test_subagent_stop_logs_tokens_and_partial(base, project, tmp_path):
    at = write_transcript(tmp_path / "agent.jsonl", [assistant("z", 1, 2, 3, 4, sidechain=True)])
    run_hook("subagent-stop", dict(base, agent_id="a1", agent_type="uccif:change-reviewer",
                                   agent_transcript_path=str(at), last_assistant_message="partial\nrow"))
    row = hook_log(project)[0]
    assert row["tokens"] == 10 and row["partial"] is True and row["out_lines"] == 2


def test_stop_token_line_and_usage_log(base, project, monkeypatch):
    from uccif_lib import log
    _, out = run_hook("stop", dict(base, stop_hook_active=False))
    assert out == {"systemMessage": "🔢 Turn: in 42.0k (cache 40.0k) · out 300 · Session 42.3k · Ctx 42.0k"}
    assert len(log.read(project, "usage.jsonl")) == 1
    assert run_hook("stop", dict(base, stop_hook_active=True)) == (0, None)
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_TOKEN_REPORT", "false")
    assert run_hook("stop", dict(base))[1] is None


def test_stop_clear_hint_after_closed_task(base, project):
    task.start(project, "a", "ui")
    task.close(project, no_findings=True)
    project.docs_dir.mkdir(parents=True, exist_ok=True)
    (project.docs_dir / "config.json").write_text('{"clear_hint_tokens": 1000}')
    _, out = run_hook("stop", dict(base))
    assert out["systemMessage"].endswith("💡 /clear recommended (task saved)")


def test_compact_and_end_lifecycle(base, project):
    from uccif_lib import log
    task.start(project, "a", "ui")
    run_hook("session-start", dict(base, source="startup"))
    run_hook("pre-compact", dict(base, trigger="auto"))
    run_hook("session-end", dict(base, reason="other"))
    types = [r["type"] for r in log.read(project, "sessions.jsonl")]
    assert types == ["start", "compact", "end"]
    end = log.read(project, "sessions.jsonl")[-1]
    assert end["task"] == "T-001" and end["tokens"] == 42310
    history = list((project.data_dir / "tasks" / "history").glob("*.md"))
    assert {p.name.split("_")[-1] for p in history} == {"precompact.md", "sessionend.md"}


def test_instructions_loaded_checks_block(base, project):
    md = project.root / "CLAUDE.md"
    md.write_text("<!-- UCCIF:BEGIN -->\nx\n<!-- UCCIF:END -->\n")
    run_hook("instructions-loaded", dict(base, file_path=str(md), memory_type="Project"))
    assert hook_log(project)[0]["target"] == "present"
