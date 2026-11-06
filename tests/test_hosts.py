"""Host adapters (hosts.py): one hook logic, translated per host; AGENTS.md as the shared
instructions file; generated skills only in the dirs of the hosts a project uses."""

import io
import json
import os

import pytest

from conftest import hook_log, run_hook
from test_skillgen import app, make_db  # noqa: F401  (fixture)
from uccif_lib import cli, hooks, hosts, skillgen, task


def gem(event, data):
    out = io.StringIO()
    code = hooks.run(event, stdin=io.StringIO(json.dumps(data)), stdout=out, host="gemini")
    text = out.getvalue()
    return code, (json.loads(text) if text else None)


@pytest.fixture
def base(project):
    return {"session_id": "s1", "cwd": str(project.root)}


# ---- pure translation -----------------------------------------------------------

@pytest.mark.parametrize("native,internal", [
    ("SessionStart", "session-start"), ("BeforeAgent", "user-prompt-submit"),
    ("BeforeTool", "pre-tool-use"), ("AfterTool", "post-tool-use"), ("AfterAgent", "stop"),
    ("PreCompress", "pre-compact"), ("SessionEnd", "session-end"),
    ("pre-tool-use", "pre-tool-use"),  # internal names pass through
])
def test_gemini_event_names(native, internal):
    assert hosts.event_name("gemini", native) == internal


def test_claude_event_names_and_passthrough():
    assert hosts.event_name("claude", "PreToolUse") == "pre-tool-use"
    assert hosts.event_name("claude", "stop") == "stop"
    assert hosts.event_name("antigravity", "SessionStart") == "session-start"


@pytest.mark.parametrize("native,claude", [
    ("run_shell_command", "Bash"), ("read_file", "Read"), ("read_many_files", "Read"),
    ("replace", "Edit"), ("write_file", "Write"), ("glob", "Glob"), ("grep_search", "Grep"),
    ("web_fetch", "web_fetch"),  # no Claude equivalent the hooks care about: unchanged
])
def test_gemini_tool_names(native, claude):
    assert hosts.normalize("gemini", "BeforeTool", {"tool_name": native})[1]["tool_name"] == claude


def test_gemini_mcp_tool_names():
    _, d = hosts.normalize("gemini", "BeforeTool", {"tool_name": "mcp_codegraph_codegraph_explore"})
    assert d["tool_name"] == "mcp__codegraph__codegraph_explore"
    _, d = hosts.normalize("gemini", "BeforeTool", {"tool_name": "mcp_my_srv_do_it",
                                                    "mcp_context": {"server_name": "my_srv"}})
    assert d["tool_name"] == "mcp__my_srv__do_it"  # server names with "_" need mcp_context


def test_gemini_failed_tool_becomes_failure_event():
    ev, d = hosts.normalize("gemini", "AfterTool", {"tool_name": "grep_search",
                                                    "tool_response": {"error": {"message": "bad regex"}}})
    assert ev == "post-tool-use-failure" and d["error"] == "bad regex" and d["tool_name"] == "Grep"
    ev, _ = hosts.normalize("gemini", "AfterTool", {"tool_name": "replace", "tool_response": {"llmContent": "ok"}})
    assert ev == "post-tool-use"


def test_normalize_does_not_touch_input():
    data = {"tool_name": "read_file"}
    hosts.normalize("gemini", "BeforeTool", data)
    assert data == {"tool_name": "read_file"}


def test_gemini_output_keeps_context_only_where_supported():
    ctx = {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "x"}}
    assert hosts.format_output("gemini", "session-start", ctx) == {
        "hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "x"}}
    assert hosts.format_output("gemini", "user-prompt-submit", ctx)["hookSpecificOutput"]["hookEventName"] == "BeforeAgent"
    assert hosts.format_output("gemini", "post-tool-use-failure", ctx)["hookSpecificOutput"]["hookEventName"] == "AfterTool"
    assert hosts.format_output("gemini", "pre-tool-use", ctx) is None  # BeforeTool has no additionalContext
    assert hosts.format_output("gemini", "stop", {"systemMessage": "t"}) == {"systemMessage": "t"}
    assert hosts.format_output("claude", "pre-tool-use", ctx) is ctx


# ---- end to end through hooks.run -------------------------------------------------

def test_gemini_session_start_injects_rules(base, project):
    code, out = gem("SessionStart", dict(base, source="startup"))
    hso = out["hookSpecificOutput"]
    assert code == 0 and hso["hookEventName"] == "SessionStart" and "CORE RULES" in hso["additionalContext"]
    entry = hook_log(project)[-1]
    assert entry["event"] == "session-start" and entry["host"] == "gemini"
    assert hosts.enabled(project) == ["gemini"]


def test_claude_output_and_log_unchanged(base, project):
    code, out = run_hook("session-start", dict(base, source="startup"))
    assert out["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert "host" not in hook_log(project)[-1]
    assert hosts.enabled(project) == ["claude"]


def test_gemini_edit_records_task_files_in_old_location(base, project):
    gem("BeforeAgent", dict(base, prompt="fix the parser bug"))
    f = project.root / "src" / "p.py"
    f.parent.mkdir()
    f.write_text("x")
    code, out = gem("AfterTool", dict(base, tool_name="replace", tool_input={"file_path": str(f)},
                                      tool_response={"llmContent": "ok"}))
    assert code == 0 and out is None
    cur = task.load_current(project)
    assert cur and "src/p.py" in cur["files"]
    assert (project.root / ".claude" / "uccif" / ".local" / "tasks" / "current.json").exists()


def test_gemini_search_nudge_is_logged_not_printed(base, project, monkeypatch):
    from uccif_lib import codegraph
    monkeypatch.setattr(codegraph, "usable", lambda project: True)
    code, out = gem("BeforeTool", dict(base, tool_name="grep_search", tool_input={"pattern": "foo"}))
    assert code == 0 and out is None  # BeforeTool cannot carry context to the model
    assert hook_log(project)[-1]["rule"] == "search-codegraph-first"


def test_gemini_shell_search_failure_reaches_model(base, project):
    code, out = gem("AfterTool", dict(base, tool_name="run_shell_command", tool_input={"command": "grep -r x ."},
                                      tool_response={"error": "grep: bad"}))
    assert out["hookSpecificOutput"]["hookEventName"] == "AfterTool"
    assert "grep: bad" in out["hookSpecificOutput"]["additionalContext"]


def test_gemini_stop_without_readable_transcript_prints_nothing(base, project):
    code, out = gem("AfterAgent", dict(base, transcript_path=str(project.root / "none.json")))
    assert code == 0 and out is None
    assert hook_log(project)[-1]["rule"] == "token-n/a"


def test_gemini_precompress_and_session_end(base, project):
    task.start(project, "t", "explore")
    assert gem("PreCompress", dict(base, trigger="auto")) == (0, None)
    assert gem("SessionEnd", dict(base, reason="exit")) == (0, None)
    events = [e["event"] for e in hook_log(project)]
    assert events[-2:] == ["pre-compact", "session-end"]


def test_unknown_host_never_breaks(base, project):
    out = io.StringIO()
    assert hooks.run("SessionStart", stdin=io.StringIO("{}"), stdout=out, host="vim") == 0
    assert out.getvalue() == "" and hook_log(project)[-1]["decision"] == "error"


def test_cli_hook_host_flag(base, project, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(dict(base, source="startup"))))
    assert cli.main(["hook", "--host", "gemini", "SessionStart"]) == 0
    assert json.loads(capsys.readouterr().out)["hookSpecificOutput"]["hookEventName"] == "SessionStart"


def test_gemini_project_dir_env(project, monkeypatch, tmp_path):
    from uccif_lib.paths import project_root
    other = tmp_path / "elsewhere"
    other.mkdir()
    monkeypatch.setenv("GEMINI_PROJECT_DIR", str(other))
    assert project_root() == other.resolve()


# ---- AGENTS.md as the one instructions file ----------------------------------------

def _write(monkeypatch, text="A lib.", *argv):
    monkeypatch.setattr("sys.stdin", io.StringIO(text))
    return cli.main(["agents-md", "write", *argv])


def test_fresh_repo_gets_agents_md_and_claude_import(project, repo, monkeypatch):
    assert _write(monkeypatch) == 0
    assert "<!-- UCCIF:BEGIN -->" in (repo / "AGENTS.md").read_text()
    assert (repo / "CLAUDE.md").read_text() == "@AGENTS.md\n"
    assert _write(monkeypatch, "B.", "--replace") == 0
    assert (repo / "CLAUDE.md").read_text() == "@AGENTS.md\n"  # never twice


def _block(text):
    return text[text.index("<!-- UCCIF:BEGIN -->"):text.index("<!-- UCCIF:END -->")]


def test_user_agents_md_not_imported_gets_block_in_both(project, repo, monkeypatch):
    """A user's AGENTS.md that CLAUDE.md does not import is never imported (it could be big):
    the same block goes into both files."""
    (repo / "AGENTS.md").write_text("# team rules\n" + "use tabs\n" * 300)
    (repo / "CLAUDE.md").write_text("# mine\nbe brief\n")
    assert _write(monkeypatch, "A lib.") == 0
    agents, claude = (repo / "AGENTS.md").read_text(), (repo / "CLAUDE.md").read_text()
    assert agents.startswith("# team rules\n" + "use tabs\n" * 300)
    assert claude.startswith("# mine\nbe brief\n\n<!-- UCCIF:BEGIN -->")
    assert "@AGENTS.md" not in claude and "@AGENTS.md" not in agents
    assert _block(agents) == _block(claude) and "A lib." in _block(claude)


def test_dual_block_refuses_then_replaces_both(project, repo, monkeypatch):
    (repo / "AGENTS.md").write_text("# team\n")
    (repo / "CLAUDE.md").write_text("# mine\n")
    assert _write(monkeypatch, "Old.") == 0
    assert _write(monkeypatch, "New.") == 3  # either file has a block: ask first
    assert _write(monkeypatch, "New.", "--replace") == 0
    agents, claude = (repo / "AGENTS.md").read_text(), (repo / "CLAUDE.md").read_text()
    assert _block(agents) == _block(claude) and "New." in claude and "Old." not in agents
    assert agents.startswith("# team\n") and claude.startswith("# mine\n")
    assert agents.count("UCCIF:BEGIN") == claude.count("UCCIF:BEGIN") == 1


def test_user_agents_md_without_claude_md_gets_block_copy_not_import(project, repo, monkeypatch):
    (repo / "AGENTS.md").write_text("# team\n")
    assert _write(monkeypatch) == 0
    claude = (repo / "CLAUDE.md").read_text()
    assert claude.startswith("<!-- UCCIF:BEGIN -->") and "@AGENTS.md" not in claude
    assert _block(claude) == _block((repo / "AGENTS.md").read_text())


def test_1_1_block_with_user_agents_md_is_updated_in_place(project, repo, monkeypatch):
    (repo / "AGENTS.md").write_text("# team\n")
    (repo / "CLAUDE.md").write_text("# mine\n\n<!-- UCCIF:BEGIN -->\nold\n<!-- UCCIF:END -->\n\nafter\n")
    assert _write(monkeypatch, "New.") == 3
    assert _write(monkeypatch, "New.", "--replace") == 0
    claude = (repo / "CLAUDE.md").read_text()
    assert claude.startswith("# mine\n\n<!-- UCCIF:BEGIN -->") and claude.endswith("<!-- UCCIF:END -->\n\nafter\n")
    assert "old" not in claude and "@AGENTS.md" not in claude
    assert _block(claude) == _block((repo / "AGENTS.md").read_text())


def test_uccif_created_agents_md_keeps_import_mode(project, repo, monkeypatch):
    assert _write(monkeypatch, "A.") == 0  # creates AGENTS.md + CLAUDE.md = @AGENTS.md
    assert _write(monkeypatch, "B.", "--replace") == 0  # AGENTS.md exists now, but is imported
    assert (repo / "CLAUDE.md").read_text() == "@AGENTS.md\n"


def test_claude_md_already_importing_is_untouched(project, repo, monkeypatch):
    (repo / "CLAUDE.md").write_text("@AGENTS.md\n# mine\n")
    assert _write(monkeypatch) == 0
    assert (repo / "CLAUDE.md").read_text() == "@AGENTS.md\n# mine\n"


def test_block_from_1_1_moves_out_of_claude_md(project, repo, monkeypatch):
    (repo / "CLAUDE.md").write_text("# mine\n\n<!-- UCCIF:BEGIN -->\nold\n<!-- UCCIF:END -->\n\nafter\n")
    assert _write(monkeypatch, "New.") == 0
    claude = (repo / "CLAUDE.md").read_text()
    assert claude == "# mine\n\n@AGENTS.md\n\nafter\n"
    agents = (repo / "AGENTS.md").read_text()
    assert "New." in agents and "old" not in agents


@pytest.mark.skipif(os.name == "nt", reason="symlinks")
def test_claude_md_symlink_to_other_file_kept(project, repo, monkeypatch):
    (repo / "docs").mkdir()
    (repo / "docs" / "ai.md").write_text("# shared\n")
    os.symlink("docs/ai.md", str(repo / "CLAUDE.md"))
    assert _write(monkeypatch) == 0
    assert (repo / "CLAUDE.md").is_symlink()
    assert (repo / "docs" / "ai.md").read_text() == "# shared\n\n@AGENTS.md\n"


@pytest.mark.skipif(os.name == "nt", reason="symlinks")
def test_claude_md_symlink_to_agents_md_needs_no_import(project, repo, monkeypatch):
    (repo / "AGENTS.md").write_text("# agents\n")
    os.symlink("AGENTS.md", str(repo / "CLAUDE.md"))
    assert _write(monkeypatch) == 0
    text = (repo / "AGENTS.md").read_text()
    assert "@AGENTS.md" not in text and "UCCIF:BEGIN" in text


def test_claude_md_alias_still_works(project, repo, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO("A lib."))
    assert cli.main(["claude-md", "write"]) == 0
    assert "UCCIF:BEGIN" in (repo / "AGENTS.md").read_text()


def test_instructions_loaded_sees_agents_md(base, project):
    md = project.root / "AGENTS.md"
    md.write_text("<!-- UCCIF:BEGIN -->\nx\n<!-- UCCIF:END -->\n")
    run_hook("instructions-loaded", dict(base, file_path=str(md), memory_type="Project"))
    assert hook_log(project)[-1]["target"] == "present"


# ---- skills per host ------------------------------------------------------------------

def test_skills_only_in_claude_dir_by_default(project, app):
    res = skillgen.generate(project)
    assert (project.root / ".claude" / "skills").is_dir()
    assert not (project.root / ".agents").exists()
    assert res["dirs"] == [".claude/skills"] and not any("(" in n for n in res["written"])


def test_skills_for_gemini_only_go_to_agents_dir(project, app):
    hosts.record(project, "gemini")
    skillgen.generate(project)
    assert (project.root / ".agents" / "skills").is_dir()
    assert not (project.root / ".claude" / "skills").exists()
    assert skillgen.generated(project)


def test_skills_for_two_hosts_written_twice_once_per_dir(project, app):
    hosts.record(project, "claude")
    hosts.record(project, "gemini")
    hosts.record(project, "antigravity")  # shares .agents/skills with gemini
    res = skillgen.generate(project)
    assert res["dirs"] == [".claude/skills", ".agents/skills"]
    a = sorted(p.parent.name for p in (project.root / ".claude" / "skills").glob("*/SKILL.md"))
    b = sorted(p.parent.name for p in (project.root / ".agents" / "skills").glob("*/SKILL.md"))
    assert a == b and a


def test_new_host_changes_fingerprint(project, app):
    before = skillgen.fingerprint(project)
    hosts.record(project, "claude")
    assert skillgen.fingerprint(project) == before  # claude only: same key as 1.1
    hosts.record(project, "gemini")
    assert skillgen.fingerprint(project) != before


def test_antigravity_enabled_by_rule_file(project):
    rule = project.root / ".agents" / "rules" / "uccif.md"
    rule.parent.mkdir(parents=True)
    rule.write_text("x")
    assert hosts.enabled(project) == ["antigravity"]
