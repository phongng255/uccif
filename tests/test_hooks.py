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
    data = dict(base)
    if event == "pre-tool-use":  # a main-agent PreToolUse skips and is not logged
        data.update(tool_name="Bash", agent_id="a1", agent_type="uccif:change-reviewer",
                    tool_input={"command": "git status"})
    code, _ = run_hook(event, data)
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
        assert "UCCIF CORE RULES" in ctx(out) and "Reply in en" in ctx(out)
    _, out = run_hook("session-start", dict(base, source="resume"))
    assert "UCCIF CORE RULES" not in ctx(out)
    assert "surveyed" not in ctx(out) and "uccif:init" not in ctx(out)  # init is optional
    assert "export UCCIF_DATA_DIR=" in env.read_text()


def test_session_start_mentions_docs_and_open_task(base, project):
    project.docs_dir.mkdir(parents=True)
    (project.docs_dir / "summary.md").write_text("x")
    task.start(project, "Fix login", "bug")
    _, out = run_hook("session-start", dict(base, source="startup"))
    assert ".claude/uccif/summary.md" in ctx(out)
    assert "Open task: Fix login (0 files)" in ctx(out)


def test_session_start_marks_previous_unclean(base, project):
    from uccif_lib import log
    log.session(project, session="OLD", type="start")
    run_hook("session-start", dict(base, source="startup"))
    ends = [r for r in log.read(project, "sessions.jsonl") if r["type"] == "end"]
    assert ends == [dict(ends[0], session="OLD", reason="unclean")]


def test_user_prompt_submit_is_silent_without_news(base, project):
    _, out = run_hook("user-prompt-submit", dict(base, prompt="hello"))
    assert out is None
    task.start(project, "Fix login", "bug")
    _, out = run_hook("user-prompt-submit", dict(base, prompt="go on"))
    assert out is None  # the open task is already in SessionStart's context


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
    rows = hook_log(project)
    if decision == "skip":
        assert rows == []  # skipped PreToolUse calls are not logged
    else:
        assert rows[0]["decision"] == decision


def _edit(base, project, name="src/a.ts"):
    return dict(base, tool_name="Edit", tool_input={"file_path": str(project.root / name)})


def test_edit_is_never_nudged(base, project):
    code, out = run_hook("pre-tool-use", _edit(base, project))
    assert code == 0 and out is None


def test_edit_with_task_quick_or_framework_file_is_not_nudged(base, project):
    _, out = run_hook("pre-tool-use", _edit(base, project, ".claude/x.md"))
    assert out is None
    run_hook("user-prompt-submit", dict(base, prompt="fix typo #quick"))
    _, out = run_hook("pre-tool-use", _edit(base, project))
    assert out is None
    run_hook("user-prompt-submit", dict(base, prompt="real change"))
    task.start(project, "a", "ui")
    _, out = run_hook("pre-tool-use", _edit(base, project))
    assert out is None


def test_search_nudge_once_per_window(base, project, monkeypatch):
    _cg_env(monkeypatch, project, cli=True, indexed=True, plugin=True)
    data = dict(base, tool_name="Grep", tool_input={"pattern": "x"})
    _, out = run_hook("pre-tool-use", data)
    assert "CodeGraph" in ctx(out)
    _, out = run_hook("pre-tool-use", data)
    assert out is None


def _turn(base, project, prompt, path="src/a.ts"):
    run_hook("user-prompt-submit", dict(base, prompt=prompt))
    run_hook("post-tool-use", dict(base, tool_name="Edit",
                                   tool_input={"file_path": str(project.root / path)}))
    run_hook("stop", dict(base))


def test_task_lives_across_turns_and_clear(base, project):
    _turn(base, project, "sửa lỗi đăng nhập khi mật khẩu rỗng")
    cur = task.load_current(project)
    assert cur["auto"] and cur["type"] == "bug" and cur["title"].startswith("sửa lỗi đăng nhập")
    assert cur["status"] == "in_progress"  # Stop no longer closes it
    _turn(base, project, "tiếp, thêm test cho trường hợp đó", "tests/login.test.ts")
    _turn(base, project, "đăng nhập vẫn lỗi khi mật khẩu có dấu cách", "src/b.ts")
    cur = task.load_current(project)
    assert cur["id"] == "T-001" and cur["files"] == ["src/a.ts", "tests/login.test.ts", "src/b.ts"]
    _, out = run_hook("session-start", dict(base, source="clear"))
    assert "Open task: sửa lỗi đăng nhập khi mật khẩu rỗng (3 files)" in ctx(out)


def test_close_with_a_finding(base, project):
    _turn(base, project, "fix the crash when the cart is empty")
    task.close(project, issues=["empty cart -> guard in total()"])
    cur = task.load_current(project)
    assert cur["status"] == "done" and cur["issues"] == ["empty cart -> guard in total()"]
    assert "empty cart" in (project.docs_dir / "known-issues.md").read_text(encoding="utf-8")
    _turn(base, project, "add dark mode toggle to settings page")
    assert task.load_current(project)["id"] == "T-002"


def test_new_topic_closes_the_old_task_and_opens_a_new_one(base, project):
    _turn(base, project, "fix the crash when the cart is empty")
    _turn(base, project, "add a dark mode toggle to the settings page", "src/settings.ts")
    old = task.load_current(project)
    assert old["id"] == "T-002" and old["files"] == ["src/settings.ts"]
    hist = sorted((project.local_dir / "tasks" / "history").glob("*_T-001.md"))
    assert hist  # T-001 closed (no findings) and snapshotted


def test_stale_task_is_closed_by_session_start(base, project):
    import json
    _turn(base, project, "fix the crash when the cart is empty")
    cur_path = project.local_dir / "tasks" / "current.json"
    data = json.loads(cur_path.read_text())
    data["last_edit"] = "2000-01-01T00:00:00+00:00"
    cur_path.write_text(json.dumps(data))
    _, out = run_hook("session-start", dict(base, source="startup"))
    assert task.load_current(project)["status"] == "done"
    assert "Open task" not in ctx(out)


VI_TASK = {"title": "sửa lỗi nút thanh toán không bấm được", "topic": []}


@pytest.mark.parametrize("prompt", [
    "sửa luôn cái nút đó", "sua luon cai nut do", "fix tiep loi do", "fix tiếp lỗi đó",
    "thêm test nữa", "vậy còn màu nút", "nút thanh toán vẫn lỗi", "nut thanh toan van loi",
    "ok", "tiếp đi", "kiểm tra lại giúp mình",
])
def test_vietnamese_continuation_keeps_the_task(prompt):
    assert not task.is_new_topic(prompt, VI_TASK)


@pytest.mark.parametrize("prompt", [
    "giờ làm trang login", "gio lam trang login", "tiếp theo làm trang đăng ký tài khoản",
    "thêm chức năng xuất báo cáo excel theo tháng", "them chuc nang xuat bao cao excel theo thang",
])
def test_vietnamese_new_work_switches(prompt):
    assert task.is_new_topic(prompt, VI_TASK)


def test_accents_do_not_matter():
    assert task.topic_words("sửa lỗi đăng nhập") == task.topic_words("sua loi dang nhap")


def test_new_topic_heuristic():
    t = {"title": "fix the crash when the cart is empty", "topic": []}
    assert not task.is_new_topic("also check the totals", t)  # continuation word
    assert not task.is_new_topic("tiếp đi", t)
    assert not task.is_new_topic("cart still crashes when empty", t)
    assert task.is_new_topic("add dark mode toggle to settings", t)


def test_quick_prompt_opens_no_task(base, project):
    run_hook("user-prompt-submit", dict(base, prompt="sửa typo #quick"))
    run_hook("post-tool-use", dict(base, tool_name="Edit",
                                   tool_input={"file_path": str(project.root / "src" / "a.ts")}))
    assert task.load_current(project) is None


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
    assert out == {"systemMessage": "🔢 Tokens\n   This turn: 42.0k input (40.0k from cache), 300 output\n   Session total: 42.3k\n   Context now: 42.0k"}
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
    history = list((project.local_dir / "tasks" / "history").glob("*.md"))
    assert {p.name.split("_")[-1] for p in history} == {"precompact.md", "sessionend.md"}


def test_instructions_loaded_checks_block(base, project):
    md = project.root / "CLAUDE.md"
    md.write_text("<!-- UCCIF:BEGIN -->\nx\n<!-- UCCIF:END -->\n")
    run_hook("instructions-loaded", dict(base, file_path=str(md), memory_type="Project"))
    assert hook_log(project)[0]["target"] == "present"


def _src(project, rel, text):
    p = project.root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


def _cg_env(monkeypatch, project, cli=False, mcp=False, indexed=False, plugin=False):
    from uccif_lib import codegraph
    home = project.root.parent / "home"
    home.mkdir(exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setattr(codegraph, "cli", lambda: "/usr/bin/codegraph" if cli else None)
    monkeypatch.setattr(codegraph, "plugin_mcp", lambda: plugin)  # the real plugin always ships .mcp.json
    if mcp:
        (home / ".claude.json").write_text(json.dumps(
            {"mcpServers": {"codegraph": {"command": "codegraph", "args": ["serve", "--mcp"]}}}))
    if indexed:
        (project.root / ".codegraph").mkdir(exist_ok=True)


def test_session_start_offers_codegraph_when_missing(base, project, monkeypatch):
    _cg_env(monkeypatch, project)
    _, out = run_hook("session-start", dict(base, source="startup"))
    text = ctx(out)
    assert "NOT installed" in text and "FIRST reply" in text and "yes/no" in text
    assert "uccif:codegraph" in text and "uccif skills generate" in text
    assert "Never `npx codegraph`" in text


def test_codegraph_decline_stops_the_offer(base, project, monkeypatch):
    from uccif_lib import cli
    _cg_env(monkeypatch, project)
    assert cli.main(["codegraph", "decline"]) == 0
    _, out = run_hook("session-start", dict(base, source="startup"))
    assert "FIRST reply" not in ctx(out) and "declined" in ctx(out)


def test_session_start_cli_without_index(base, project, monkeypatch):
    _cg_env(monkeypatch, project, cli=True)
    _, out = run_hook("session-start", dict(base, source="startup"))
    assert "indexing this project in the background" in ctx(out) and "codegraph init --yes" in ctx(out)


def test_session_start_codegraph_active(base, project, monkeypatch):
    _cg_env(monkeypatch, project, cli=True, mcp=True, indexed=True)
    _, out = run_hook("session-start", dict(base, source="startup"))
    assert "CodeGraph is active" in ctx(out) and "core rule 2" in ctx(out)
    assert "`codegraph_explore`" in ctx(out)  # the routing itself lives in the core rules


def test_session_start_index_without_mcp(base, project, monkeypatch):
    _cg_env(monkeypatch, project, cli=True, indexed=True)  # an older plugin without .mcp.json
    _, out = run_hook("session-start", dict(base, source="startup"))
    assert "not wired" in ctx(out)


def test_session_start_active_with_plugin_provided_mcp(base, project, monkeypatch):
    """No ~/.claude.json entry needed: the plugin's own .mcp.json provides the server."""
    _cg_env(monkeypatch, project, cli=True, indexed=True, plugin=True)
    _, out = run_hook("session-start", dict(base, source="startup"))
    assert "CodeGraph is active" in ctx(out) and "not wired" not in ctx(out)


def test_session_start_index_without_cli(base, project, monkeypatch):
    """The server cannot start without the CLI, so never claim CodeGraph is active."""
    _cg_env(monkeypatch, project, cli=False, indexed=True, plugin=True)
    _, out = run_hook("session-start", dict(base, source="startup"))
    assert "CodeGraph is active" not in ctx(out) and "CLI is not installed" in ctx(out)
    assert "uccif:codegraph" in ctx(out)


def test_post_tool_use_records_task_file(base, project):
    task.start(project, "Fix login", "bug")
    _src(project, "src/a.ts", "export function alpha() {}\n")
    run_hook("post-tool-use", dict(base, tool_name="Edit",
                                   tool_input={"file_path": str(project.root / "src" / "a.ts")}))
    assert hook_log(project)[-1]["rule"] == "task-files"


def test_drift_reaches_claude_then_ack_clears_it(base, project):
    from uccif_lib import drift
    _src(project, "src/a.ts", "export const a = 1\n")
    run_hook("session-start", dict(base, source="startup"))  # baseline
    _src(project, "src/payments/pay.ts", "export const p = 1\n")
    run_hook("stop", dict(base))
    _, out = run_hook("user-prompt-submit", dict(base, prompt="hi"))
    assert out is None or "stale" not in ctx(out)  # no docs yet: nothing to keep in sync
    _src(project, ".claude/uccif/summary.md", "# x\n")
    drift.ack(project)
    _src(project, "src/orders/o.ts", "export const o = 1\n")
    (project.root / "package.json").write_text('{"dependencies": {"pinia": "2"}}')
    run_hook("stop", dict(base))
    _, out = run_hook("user-prompt-submit", dict(base, prompt="hi"))
    text = ctx(out)
    assert "added pinia" in text and "uccif drift ack" in text
    assert "src/orders" not in text and "architecture" not in text  # dirs: the map skill refreshes itself
    edit = dict(base, tool_name="Edit", tool_input={"file_path": str(project.root / "src" / "a.ts")})
    _src(project, "src/a.ts", "export const a = 2\n")  # a change inside code is not drift
    run_hook("post-tool-use", edit)
    drift.ack(project)
    run_hook("stop", dict(base))
    _, out = run_hook("user-prompt-submit", dict(base, prompt="hi"))
    assert out is None or "stale" not in ctx(out)


def test_lsp_offer_once_per_binary(base, project, monkeypatch):
    from uccif_lib import hooks as H
    for i in range(3):
        _src(project, "app/m%d.py" % i, "def f%d():\n    pass\n" % i)
    monkeypatch.setattr(H.shutil, "which", lambda b: None)
    _, out = run_hook("session-start", dict(base, source="startup"))
    assert "pyright-langserver" in ctx(out) and "npm install -g pyright" in ctx(out)
    _, out = run_hook("session-start", dict(base, source="startup"))
    assert "pyright-langserver" not in ctx(out)  # asked once only


REMINDER = "<system-reminder>\nforked from another session\n</system-reminder>"
SHELL = "<bash-input>npm test</bash-input><bash-stdout>#quick ok</bash-stdout><bash-stderr></bash-stderr>"


def _edit_file(base, path):
    run_hook("post-tool-use", dict(base, tool_name="Edit", tool_input={"file_path": path}))


@pytest.mark.parametrize("text,clean", [
    (REMINDER + "\nFix the login page", "Fix the login page"),
    ("<system-reminder>cut off by truncation", ""),
    (SHELL, ""),
    ("Explain <div> and <bash-output> tags", "Explain <div> and <bash-output> tags"),
])
def test_title_text_removes_only_host_wrappers(text, clean):
    assert hooks._title_text(text) == clean


def test_task_title_comes_from_user_text(base, project):
    run_hook("user-prompt-submit", dict(base, prompt=REMINDER + "\nFix the login page"))
    _edit_file(dict(base), str(project.root / "src" / "a.ts"))
    assert task.load_current(project)["title"] == "Fix the login page"


def test_long_wrapper_does_not_use_up_the_stored_prompt(base, project):
    long = "<system-reminder>" + "x" * 1000 + "</system-reminder>Fix the login page"
    run_hook("user-prompt-submit", dict(base, prompt=long))
    _edit_file(dict(base), str(project.root / "src" / "a.ts"))
    assert task.load_current(project)["title"] == "Fix the login page"


def test_shell_only_prompt_is_not_a_request(base, project):
    path = str(project.root / "src" / "a.ts")
    run_hook("user-prompt-submit", dict(base, prompt="Fix the login page"))
    _edit_file(dict(base), path)
    opened = task.load_current(project)
    run_hook("user-prompt-submit", dict(base, prompt=SHELL))
    _edit_file(dict(base), str(project.root / "src" / "b.ts"))
    cur = task.load_current(project)
    assert cur["id"] == opened["id"] and cur["title"] == "Fix the login page"
    assert "src/b.ts" in cur["files"]


def test_shell_only_prompt_does_not_title_a_task(base, project):
    run_hook("user-prompt-submit", dict(base, prompt=SHELL))
    _edit_file(dict(base), str(project.root / "src" / "a.ts"))
    assert "bash-input" not in task.load_current(project)["title"]


def test_quick_inside_command_output_does_not_count(base, project):
    run_hook("user-prompt-submit", dict(base, prompt=SHELL))
    assert not hooks._is_quick(project)


# ---- CodeGraph news mid-session (state changes after SessionStart) -----------------------

def test_codegraph_ready_mid_session_is_announced_once(base, project, monkeypatch):
    _cg_env(monkeypatch, project)  # nothing installed at session start
    _, out = run_hook("session-start", dict(base, source="startup"))
    assert "NOT installed" in ctx(out)
    _, out = run_hook("user-prompt-submit", dict(base, prompt="ok"))
    assert out is None  # nothing changed yet
    _cg_env(monkeypatch, project, cli=True, indexed=True, plugin=True)  # installed + indexed meanwhile
    _, out = run_hook("user-prompt-submit", dict(base, prompt="now fix the ledger"))
    text = ctx(out)
    assert "replaces the earlier note" in text and "CodeGraph is active" in text
    assert hook_log(project)[-1]["codegraph"] == 1
    _, out = run_hook("user-prompt-submit", dict(base, prompt="and the totals"))
    assert out is None  # said once


def test_new_map_skill_mid_session_is_announced(base, project, monkeypatch):
    _cg_env(monkeypatch, project, cli=True, indexed=True, plugin=True)
    run_hook("session-start", dict(base, source="startup"))
    monkeypatch.setattr(hooks, "_map_skill", lambda project: "trip-map")
    _, out = run_hook("user-prompt-submit", dict(base, prompt="fix it"))
    text = ctx(out)
    assert "New project skills" in text and "`trip-map`" in text and "`trip-mod-*`" in text
    assert "CodeGraph changed" not in text


def test_news_is_per_session(base, project, monkeypatch):
    _cg_env(monkeypatch, project)
    run_hook("session-start", dict(base, source="startup"))
    _cg_env(monkeypatch, project, cli=True, indexed=True, plugin=True)
    run_hook("session-start", dict(base, session_id="S2", source="startup"))  # told "active" already
    _, out = run_hook("user-prompt-submit", dict(base, session_id="S2", prompt="x"))
    assert out is None
    _, out = run_hook("user-prompt-submit", dict(base, prompt="x"))  # S1 was told "missing"
    assert "CodeGraph is active" in ctx(out)


# ---- what counts as reading code without CodeGraph -------------------------------------

@pytest.mark.parametrize("tool,ti,kind", [
    ("Read", {"file_path": "src/a.ts"}, "read"),
    ("Read", {"file_path": "README.md"}, None),
    ("Bash", {"command": "sed -n 1,80p src/stores/ledger.ts"}, "read"),
    ("Bash", {"command": "cat package.json"}, None),
    ("Bash", {"command": "grep -rn computeLedger src"}, "search"),
    ("Grep", {"pattern": "x"}, "search"),
    ("Bash", {"command": "codegraph explore \"computeLedger\""}, "lookup"),
    ("Bash", {"command": "npx -y @colbymchenry/codegraph callers computeLedger"}, "lookup"),
    ("mcp__plugin_uccif_codegraph__codegraph_explore", {"query": "x"}, "lookup"),
    ("Bash", {"command": "npm test"}, None),
])
def test_classify(tool, ti, kind):
    assert hooks._classify(tool, ti) == kind


def test_read_of_source_is_nudged_with_a_concrete_call(base, project, monkeypatch):
    _cg_env(monkeypatch, project, cli=True, indexed=True, plugin=True)
    monkeypatch.setattr(hooks, "_map_skill", lambda project: "trip-map")
    _, out = run_hook("pre-tool-use", dict(base, tool_name="Read", tool_input={"file_path": "src/a.ts"}))
    text = ctx(out)
    assert "reads source code" in text and "`codegraph_explore`" in text and "`trip-mod-*`" in text


def test_no_nudge_after_a_lookup_this_turn_and_reset_next_prompt(base, project, monkeypatch):
    _cg_env(monkeypatch, project, cli=True, indexed=True, plugin=True)
    run_hook("user-prompt-submit", dict(base, prompt="fix"))
    run_hook("pre-tool-use", dict(base, tool_name="mcp__plugin_uccif_codegraph__codegraph_explore",
                                  tool_input={"query": "ledger"}))
    assert hook_log(project)[-1]["rule"] == "codegraph-lookup"
    _, out = run_hook("pre-tool-use", dict(base, tool_name="Grep", tool_input={"pattern": "x"}))
    assert out is None
    run_hook("user-prompt-submit", dict(base, prompt="next thing"))
    _, out = run_hook("pre-tool-use", dict(base, tool_name="Grep", tool_input={"pattern": "x"}))
    assert "CodeGraph" in ctx(out)


def test_no_codegraph_nudge_without_an_index(base, project, monkeypatch):
    _cg_env(monkeypatch, project)
    _, out = run_hook("pre-tool-use", dict(base, tool_name="Read", tool_input={"file_path": "src/a.ts"}))
    assert out is None


def _decision(out):
    return ((out or {}).get("hookSpecificOutput") or {}).get("permissionDecision")


def test_strict_refuses_first_code_read_of_a_turn_then_allows(base, project, monkeypatch):
    _cg_env(monkeypatch, project, cli=True, indexed=True, plugin=True)
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_STRICT_CODEGRAPH", "true")
    run_hook("user-prompt-submit", dict(base, prompt="fix"))
    read = dict(base, tool_name="Read", tool_input={"file_path": "src/a.ts"})
    _, out = run_hook("pre-tool-use", read)
    assert _decision(out) == "deny"
    assert "retry the same call" in out["hookSpecificOutput"]["permissionDecisionReason"]
    assert hook_log(project)[-1]["rule"] == "strict-codegraph"
    _, out = run_hook("pre-tool-use", read)
    assert _decision(out) is None  # a retry goes through
    run_hook("user-prompt-submit", dict(base, prompt="next"))
    run_hook("pre-tool-use", dict(base, tool_name="Bash", tool_input={"command": "codegraph explore x"}))
    _, out = run_hook("pre-tool-use", read)
    assert _decision(out) is None  # looked up first: nothing to refuse


def test_strict_is_off_by_default_and_needs_codegraph(base, project, monkeypatch):
    _cg_env(monkeypatch, project, cli=True, indexed=True, plugin=True)
    read = dict(base, tool_name="Read", tool_input={"file_path": "src/a.ts"})
    _, out = run_hook("pre-tool-use", read)
    assert _decision(out) is None
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_STRICT_CODEGRAPH", "true")
    _cg_env(monkeypatch, project)
    (project.root / ".codegraph").rmdir()
    _, out = run_hook("pre-tool-use", read)
    assert _decision(out) is None  # nothing to look up with


def test_strict_never_refuses_glob_or_subagents(base, project, monkeypatch):
    _cg_env(monkeypatch, project, cli=True, indexed=True, plugin=True)
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_STRICT_CODEGRAPH", "true")
    _, out = run_hook("pre-tool-use", dict(base, tool_name="Glob", tool_input={"pattern": "**/*.ts"}))
    assert _decision(out) is None
    _, out = run_hook("pre-tool-use", dict(base, tool_name="Read", agent_id="a1", agent_type="Explore",
                                           tool_input={"file_path": "src/a.ts"}))
    assert _decision(out) is None


# ---- files changed by Bash / scripts reach the task -----------------------------------

def test_bash_edits_are_recorded_at_stop(base, project):
    from conftest import git
    _src(project, "src/old.ts", "export const o = 1\n")  # dirty before the prompt, left alone
    run_hook("user-prompt-submit", dict(base, prompt="sửa tổng chi trong ledger"))
    _src(project, "src/ledger.ts", "export const l = 1\n")  # e.g. a Python script wrote it
    _src(project, ".claude/uccif/summary.md", "x\n")
    run_hook("stop", dict(base))
    cur = task.load_current(project)
    assert cur and cur["title"].startswith("sửa tổng chi") and cur["files"] == ["src/ledger.ts"]
    assert hook_log(project)[-1]["git_files"] == 1
    run_hook("user-prompt-submit", dict(base, prompt="tiếp tục sửa ledger"))
    _src(project, "src/ledger.ts", "export const l = 2\n")
    git(project.root, "add", "src/ledger.ts")
    git(project.root, "commit", "-q", "-m", "x")  # committed during the turn: still seen
    _src(project, "src/view.ts", "export const v = 1\n")
    git(project.root, "add", "src/view.ts")
    git(project.root, "commit", "-q", "-m", "y")
    run_hook("stop", dict(base))
    assert task.load_current(project)["files"] == ["src/ledger.ts", "src/view.ts"]


def test_no_git_tracking_on_quick_or_without_changes(base, project):
    run_hook("user-prompt-submit", dict(base, prompt="what does this do"))
    run_hook("stop", dict(base))
    assert task.load_current(project) is None
    run_hook("user-prompt-submit", dict(base, prompt="fix typo #quick"))
    _src(project, "src/a.ts", "x\n")
    run_hook("stop", dict(base))
    assert task.load_current(project) is None


def test_git_tracking_outside_git_is_skipped(base, project, monkeypatch):
    monkeypatch.setattr(hooks, "_git_state", lambda root: None)
    run_hook("user-prompt-submit", dict(base, prompt="fix"))
    _src(project, "src/a.ts", "x\n")
    _, out = run_hook("stop", dict(base))
    assert task.load_current(project) is None and hook_log(project)[-1]["decision"] != "error"
