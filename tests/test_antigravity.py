"""Antigravity CLI (agy, Gemini CLI's successor): plugin files, hook adapter, .agents/skills/."""

import io
import json
import re

import pytest

from conftest import PLUGIN, git, hook_log
from test_skillgen import app  # noqa: F401  (fixture)
from uccif_lib import __version__, hooks, skillgen, task

# top-level keys allowed by https://antigravity.google/schemas/v1/plugin.json (additionalProperties: false)
MANIFEST_KEYS = {"$schema", "name", "displayName", "description", "version", "logo", "suggestedPrompts",
                 "skills", "disabled", "author", "homepage", "repository", "license", "keywords", "extensions"}
AG_EVENTS = {"SessionStart", "PreToolUse", "PostToolUse", "PreInvocation", "PostInvocation", "Stop"}


def ag_hook(event, data):
    out = io.StringIO()
    code = hooks.run(event, stdin=io.StringIO(json.dumps(data)), stdout=out, agent="antigravity")
    text = out.getvalue()
    return code, (json.loads(text) if text else None)


@pytest.fixture
def base(project):
    return {"conversationId": "c1", "workspacePaths": [str(project.root)], "transcriptPath": "/nope",
            "modelName": "gemini"}


# ---- plugin files ------------------------------------------------------------------

def test_manifest_is_valid_and_version_matches():
    m = json.loads((PLUGIN / ".antigravity-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert set(m) <= MANIFEST_KEYS
    assert m["name"] == "uccif" and re.match(r"^[a-z0-9]+(-[a-z0-9]+)*$", m["name"])
    assert m["version"] == __version__
    assert len(m.get("suggestedPrompts", [])) <= 3


def test_hooks_json_runs_known_handlers_from_the_plugin_root():
    cfg = json.loads((PLUGIN / "hooks.json").read_text(encoding="utf-8"))
    (name, hook), = cfg.items()
    assert hook["enabled"] is True
    events = {k for k in hook if k != "enabled"}
    assert events <= AG_EVENTS and {"SessionStart", "Stop"} <= events
    assert "PreToolUse" not in events  # its stdout must carry a decision; the core never decides
    for event in events:
        entries = hook[event]
        handlers = ([h for e in entries for h in e["hooks"]] if event in ("PreToolUse", "PostToolUse")
                    else entries)
        for h in handlers:
            m = re.match(r"^sh \./bin/uccif hook --agent antigravity ([a-z-]+)$", h["command"])
            assert m and m.group(1) in hooks.HANDLERS, h["command"]
            assert 0 < h["timeout"] <= 10


def test_mcp_config_declares_codegraph():
    srv = json.loads((PLUGIN / "mcp_config.json").read_text(encoding="utf-8"))["mcpServers"]["codegraph"]
    assert srv == {"command": "codegraph", "args": ["serve", "--mcp"]}


# ---- hook adapter ------------------------------------------------------------------

def test_from_antigravity_maps_fields(tmp_path):
    d = hooks.from_antigravity({"conversationId": "c", "workspacePaths": [str(tmp_path)], "transcriptPath": "t",
                                "toolCall": {"name": "replace_file_content", "args": {"TargetFile": "src/a.py"}}})
    assert d["session_id"] == "c" and d["cwd"] == str(tmp_path) and d["transcript_path"] == "t"
    assert d["tool_name"] == "Edit" and d["tool_input"]["file_path"] == str(tmp_path / "src" / "a.py")
    cmd = hooks.from_antigravity({"toolCall": {"name": "run_command", "args": {"CommandLine": "ls"}}})
    assert cmd["tool_name"] == "Bash" and cmd["tool_input"] == {"command": "ls"}


def test_session_start_injects_rules_as_a_step(base, project):
    code, out = ag_hook("session-start", base)
    assert code == 0 and list(out) == ["injectSteps"]
    (step,) = out["injectSteps"]
    assert "UCCIF CORE RULES" in step["userMessage"] and "Antigravity CLI" in step["userMessage"]
    assert str((PLUGIN / "bin" / "uccif").as_posix()) in step["userMessage"]
    row = hook_log(project)[-1]
    assert row["event"] == "session-start" and row["agent"] == "antigravity" and row["session"] == "c1"


def test_post_tool_use_records_task_file_and_answers_nothing(base, project):
    task.start(project, "a", "ui")
    code, out = ag_hook("post-tool-use", dict(base, toolCall={"name": "write_to_file",
                                                               "args": {"TargetFile": "src/a.ts"}}, stepIdx=1))
    assert code == 0 and out is None
    assert task.load_current(project)["files"] == ["src/a.ts"]


def test_stop_prints_no_token_line(base, project):
    code, out = ag_hook("stop", dict(base, executionNum=1, terminationReason="done", fullyIdle=True))
    assert code == 0 and out is None
    assert hook_log(project)[-1]["rule"] == "maintain"


@pytest.mark.parametrize("raw", ["", "not json", "[1]"])
def test_bad_input_never_breaks(raw, project):
    out = io.StringIO()
    assert hooks.run("session-start", stdin=io.StringIO(raw), stdout=out, agent="antigravity") == 0


def test_cli_accepts_agent_flag(base, project, monkeypatch):
    from uccif_lib import cli
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(base)))
    assert cli.main(["hook", "--agent", "antigravity", "stop"]) == 0


# ---- project skills in .agents/skills/ ---------------------------------------------

def test_auto_target_is_claude_only_by_default(app, project):
    res = skillgen.generate(project)
    assert res["roots"] == [".claude/skills/"]
    assert not (app / ".agents").exists()


def test_agents_target_and_auto_detection(app, project):
    res = skillgen.generate(project, target="agents")
    assert res["roots"] == [".agents/skills/"]
    assert (app / ".agents" / "skills" / "repo-map" / "SKILL.md").exists()
    assert skillgen.generated(project)  # found in .agents/skills/ when .claude/skills/ is empty
    res = skillgen.generate(project)  # .agents/ exists now: auto writes both
    assert res["roots"] == [".claude/skills/", ".agents/skills/"]
    assert ".claude/skills/repo-map" in res["written"] and ".agents/skills/repo-map" in res["unchanged"]


def test_legacy_agent_dir_is_used_when_alone(app, project):
    (app / ".agent").mkdir()
    res = skillgen.generate(project, target="agents")
    assert res["roots"] == [".agent/skills/"]


def test_antigravity_hook_session_writes_agents_skills(app, project, monkeypatch):
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_AUTO_SETUP", "true")
    monkeypatch.setattr("uccif_lib.codegraph.auto_init", lambda p: None)
    git(app, "add", "-A")
    ag_hook("session-start", {"conversationId": "c", "workspacePaths": [str(app)]})
    assert (app / ".agents" / "skills" / "repo-map" / "SKILL.md").exists()
    assert (app / ".claude" / "skills" / "repo-map" / "SKILL.md").exists()


# ---- Antigravity / Gemini folder resolution (.gemini/uccif) -------------------------

def test_antigravity_uses_gemini_uccif_folder(repo, monkeypatch):
    from uccif_lib import paths, rules, detect
    monkeypatch.setenv("UCCIF_AGENT", "antigravity")
    proj = paths.resolve_project()
    assert proj.agent == "antigravity"
    assert proj.docs_subdir.as_posix() == ".gemini/uccif"
    assert proj.docs_dir == repo / ".gemini" / "uccif"

    # task operations write to .gemini/uccif/.local/
    task.start(proj, "Fix login", "bug")
    assert (repo / ".gemini" / "uccif" / ".local" / "tasks" / "current.json").exists()
    assert (repo / ".gemini" / "uccif" / ".local" / "current-task.md").exists()
    cur = task.load_current(proj)
    assert cur["title"] == "Fix login"
    task.close(proj, no_findings=True)

    # user rules check .gemini/uccif/rules.md
    rule_files = [p for _, p in rules.user_rule_files(proj)]
    assert any(".gemini/uccif/rules.md" in p.as_posix() for p in rule_files)

    # detect recognizes GEMINI.md and .gemini/uccif/summary.md
    (repo / "GEMINI.md").write_text("<!-- UCCIF:BEGIN -->\n## Project\n<!-- UCCIF:END -->\n", encoding="utf-8")
    (repo / ".gemini" / "uccif" / "summary.md").write_text("# Project Summary\n", encoding="utf-8")
    d = detect.detect(proj)
    assert d["claude_md_block"] is True
    assert d["docs"]["summary.md"] is True

    # session-start mentions .gemini/uccif/
    code, out = ag_hook("session-start", {"conversationId": "c2", "workspacePaths": [str(repo)]})
    assert code == 0
    msg = out["injectSteps"][0]["userMessage"]
    assert "Project docs: .gemini/uccif/" in msg


def test_antigravity_respects_existing_claude_folder_for_backwards_compatibility(repo, monkeypatch):
    from uccif_lib import paths
    # Create existing .claude/uccif folder
    (repo / ".claude" / "uccif").mkdir(parents=True)
    monkeypatch.setenv("UCCIF_AGENT", "antigravity")
    proj = paths.resolve_project()
    # Still knows agent is antigravity, but preserves existing .claude/uccif
    assert proj.agent == "antigravity"
    assert proj.docs_subdir.as_posix() == ".claude/uccif"
