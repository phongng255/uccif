"""Antigravity plugin (plugins/uccif-antigravity/): files built from the core, hooks run for real
through a shell from the plugin root with JSON shaped like the hooks contract, `agy` itself when it
is installed, and `uccif setup antigravity` touching only what it wrote."""

import io
import json
import os
import re
import shutil
import subprocess
import sys

import pytest

from conftest import PLUGIN, REPO, hook_log
from uccif_lib import antigravity_setup as setup_mod
from uccif_lib import hooks, hostfiles, hosts

DIR = PLUGIN.parent / "uccif-antigravity"
HOOKS = json.loads((DIR / "hooks.json").read_text(encoding="utf-8"))["uccif"]
sys.path.insert(0, str(PLUGIN / "scripts"))
import build_antigravity  # noqa: E402


def common(project, **kw):
    return dict({"conversationId": "c1", "workspacePaths": [str(project.root)],
                 "transcriptPath": str(project.root / "none.jsonl"),
                 "artifactDirectoryPath": "/tmp/a", "modelName": "gemini-3-pro"}, **kw)


def call(event, payload):
    out = io.StringIO()
    hooks.run(event, stdin=io.StringIO(json.dumps(payload)), stdout=out, host="antigravity")
    return json.loads(out.getvalue())


# ---- plugin files ------------------------------------------------------------------

def test_plugin_built_from_the_core():
    stale, extra = build_antigravity.build(check=True)
    assert stale == [] and extra == [], "run python plugins/uccif/scripts/build_antigravity.py"


def test_manifest_follows_the_claude_plugin():
    mine = json.loads((DIR / "plugin.json").read_text(encoding="utf-8"))
    src = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert mine["name"] == "uccif" and mine["version"] == src["version"]
    assert re.match(r"^[a-z0-9]+(-[a-z0-9]+)*$", mine["name"])


def test_skills_have_no_other_host_names():
    assert {p.parent.name for p in (DIR / "skills").glob("*/SKILL.md")} == {
        p.parent.name for p in hostfiles.skill_sources()}
    for p in (DIR / "skills").glob("*/SKILL.md"):
        text = p.read_text(encoding="utf-8")
        head = text.split("\n---\n")[0]
        assert "name: %s\n" % p.parent.name in head + "\n" and "description:" in head
        for word in ("Claude Code", "Gemini", "gemini-extension", "run_shell_command", "uccif:", "$ARGUMENTS"):
            assert word not in text, (p, word)


def test_rule_note_names_the_right_command():
    text = (DIR / "rules" / "AGENTS.md").read_text(encoding="utf-8")
    assert "agy plugin list" in text and "gemini" not in text.lower()
    assert not text.startswith("---")  # rules/AGENTS.md takes no frontmatter


def test_same_codegraph_server_as_the_claude_plugin():
    mine = json.loads((DIR / "mcp_config.json").read_text(encoding="utf-8"))["mcpServers"]["codegraph"]
    claude = json.loads((PLUGIN / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]["codegraph"]
    assert mine == {k: claude[k] for k in ("command", "args", "env")}


def test_hooks_json_shape():
    assert set(HOOKS) == {"SessionStart", "PreInvocation", "PostToolUse", "Stop"}
    for event in ("SessionStart", "PreInvocation", "Stop"):  # flat arrays
        assert all("command" in h and "matcher" not in h for h in HOOKS[event])
    entry = HOOKS["PostToolUse"][0]
    re.compile(entry["matcher"])
    for event, handlers in [(e, HOOKS[e]) for e in ("SessionStart", "PreInvocation", "Stop")] + [
            ("PostToolUse", entry["hooks"])]:
        for h in handlers:
            assert h["type"] == "command" and h["timeout"] <= 10  # seconds in Antigravity
            assert h["command"] == "./core/bin/uccif hook --host antigravity " + event


def test_no_pre_tool_use_hook():
    """Its required decision can only allow, deny or ask, and allow skips the permission prompt."""
    assert "PreToolUse" not in HOOKS


@pytest.mark.skipif(os.name == "nt", reason="symlinks need a special git setting on Windows")
def test_core_is_a_symlink_to_the_plugin():
    assert os.readlink(str(DIR / "core")) == "../uccif"
    assert (DIR / "core" / "bin" / "uccif").is_file()


def test_no_clash_with_the_other_hosts_at_the_repo_root():
    """Nothing of Antigravity's at the root: a root plugin.json or hooks.json would change what
    `agy plugin install` of the repo does, and the Gemini extension's files stay where it needs them."""
    for name in ("plugin.json", "hooks.json", "mcp_config.json", "rules", ".antigravity-plugin"):
        assert not (REPO / name).exists(), name
    assert (REPO / "gemini-extension.json").is_file() and (REPO / "hooks" / "hooks.json").is_file()
    market = json.loads((REPO / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
    assert [p["source"] for p in market["plugins"]] == ["./plugins/uccif"]


# ---- adapter -----------------------------------------------------------------------

@pytest.mark.parametrize("native,internal", [
    ("SessionStart", "session-start"), ("PreInvocation", "user-prompt-submit"),
    ("PostToolUse", "post-tool-use"), ("Stop", "stop"), ("stop", "stop"),
])
def test_event_names(native, internal):
    assert hosts.event_name("antigravity", native) == internal


@pytest.mark.parametrize("native,claude", [
    ("run_command", "Bash"), ("view_file", "Read"), ("edit_file", "Edit"), ("replace_file_content", "Edit"),
    ("multi_replace_file_content", "Edit"), ("write_to_file", "Write"), ("grep_search", "Grep"),
    ("find_by_name", "Glob"), ("search_web", "search_web"),
])
def test_tool_names(native, claude):
    data = {"workspacePaths": ["/w"], "toolCall": {"name": native, "args": {}}}
    assert hosts.normalize("antigravity", "PostToolUse", data)[1]["tool_name"] == claude


def test_normalize_fields():
    event, d = hosts.normalize("antigravity", "PostToolUse", {
        "conversationId": "c", "workspacePaths": ["/w", "/x"], "transcriptPath": "/t",
        "toolCall": {"name": "run_command", "args": {"CommandLine": "npm test", "Cwd": "/w"}}, "error": "exit status 1"})
    assert event == "post-tool-use-failure"
    assert d["cwd"] == "/w" and d["session_id"] == "c" and d["transcript_path"] == "/t"
    assert d["tool_input"]["command"] == "npm test"


def test_no_workspace_is_logged_and_never_uses_the_plugin_dir(project, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    assert call("SessionStart", {"conversationId": "c", "workspacePaths": []}) == {}
    assert not (tmp_path / ".claude").exists()


def test_session_start_uses_the_workspace_not_the_hook_cwd(project, monkeypatch, tmp_path):
    other = tmp_path / "plugin-root"
    other.mkdir()
    monkeypatch.chdir(other)  # hooks run with the plugin root as cwd
    spawned = []  # the real spawn passes project.root as cwd; UCCIF_SYNC's inline run would not
    monkeypatch.setattr(hooks, "spawn", lambda args, proj: spawned.append(proj.root))
    out = call("SessionStart", common(project))
    assert spawned == [project.root]
    step = out["injectSteps"][0]["systemMessage"]
    assert set(out) == {"injectSteps"} and "CORE RULES" in step["systemMessage"]
    assert "is not on PATH here" in step["systemMessage"] and "Claude Code restart" not in step["systemMessage"]
    assert not (other / ".claude").exists()
    assert "antigravity" in hosts.enabled(project)


def test_agents_block_is_not_injected(project):
    """Antigravity reads AGENTS.md itself."""
    (project.root / "AGENTS.md").write_text("<!-- UCCIF:BEGIN -->\n## demo\nA lib.\n<!-- UCCIF:END -->\n")
    assert "A lib." not in call("SessionStart", common(project))["injectSteps"][0]["systemMessage"]["systemMessage"]


def test_pre_invocation_counts_one_prompt_per_turn(project, monkeypatch):
    (project.data_dir / "prompt_edited.flag").parent.mkdir(parents=True, exist_ok=True)
    flag = project.data_dir / "prompt_edited.flag"
    flag.write_text("1")
    monkeypatch.setattr(hooks.drift, "pending", lambda p: ["src/ changed"])
    first = call("PreInvocation", common(project, invocationNum=1, initialNumSteps=10))
    assert "src/ changed" in first["injectSteps"][0]["ephemeralMessage"] and not flag.exists()
    flag.write_text("1")
    assert call("PreInvocation", common(project, invocationNum=2, initialNumSteps=10)) == {}
    assert flag.exists()  # the same turn: the first edit is still the first edit
    assert call("PreInvocation", common(project, invocationNum=1, initialNumSteps=25))["injectSteps"]
    assert not flag.exists()
    assert [e["event"] for e in hook_log(project)].count("user-prompt-submit") == 2  # same-turn call is quiet


def test_edit_is_recorded_and_opens_a_task(project):
    src = project.root / "src" / "a.py"
    src.parent.mkdir()
    src.write_text("x = 1\n")
    args = {"TargetFile": str(src), "CodeMarkdownLanguage": "python"}
    assert call("PostToolUse", common(project, stepIdx=3, toolCall={"name": "edit_file", "args": args})) == {}
    log = hook_log(project)[-1]
    assert log["target"] == "src/a.py" and log["host"] == "antigravity" and log["decision"] != "error"


def test_failed_tool_gets_an_empty_object(project):
    payload = common(project, stepIdx=3, error="exit status 1",
                     toolCall={"name": "run_command", "args": {"CommandLine": "grep x"}})
    assert call("PostToolUse", payload) == {}


def test_stop_never_continues_and_waits_for_idle(project):
    idle = call("Stop", common(project, executionNum=1, terminationReason="NO_TOOL_CALL", fullyIdle=True))
    busy = call("Stop", common(project, executionNum=2, terminationReason="NO_TOOL_CALL", fullyIdle=False))
    assert idle == {"decision": "allow"} and busy == {"decision": "allow"}
    log = hook_log(project)
    assert log[-1]["rule"] == "rerun" and log[-2]["rule"] != "rerun"


def test_bad_input_still_prints_a_json_object(project):
    out = io.StringIO()
    hooks.run("Stop", stdin=io.StringIO("not json"), stdout=out, host="antigravity")
    assert json.loads(out.getvalue()) == {"decision": "allow"}


def test_other_hosts_still_print_nothing_when_silent(project):
    for host in ("claude", "gemini"):
        out = io.StringIO()
        hooks.run("post-tool-use", stdin=io.StringIO(json.dumps({"cwd": str(project.root)})), stdout=out, host=host)
        assert out.getvalue() == ""


@pytest.mark.skipif(os.name == "nt", reason="bin/uccif is a sh script; Antigravity on Windows not verified")
def test_every_hook_runs_through_the_shell_from_the_plugin_root(project):
    env = dict(os.environ, CLAUDE_PROJECT_DIR="")
    env.pop("UCCIF_SYNC", None)  # the real path: upkeep runs detached, in the project
    src = project.root / "a.py"
    src.write_text("x = 1\n")
    steps = {
        "SessionStart": common(project),
        "PreInvocation": common(project, invocationNum=1, initialNumSteps=0),
        "PostToolUse": common(project, stepIdx=1, toolCall={"name": "write_to_file", "args": {"TargetFile": str(src)}}),
        "Stop": common(project, executionNum=1, terminationReason="NO_TOOL_CALL", fullyIdle=True),
    }
    outs = {}
    for event, payload in steps.items():
        entry = HOOKS[event][0]
        cmd = (entry["hooks"][0] if "hooks" in entry else entry)["command"]
        r = subprocess.run(cmd, shell=True, cwd=str(DIR), input=json.dumps(payload).encode("utf-8"),
                           capture_output=True, env=env, timeout=60)
        assert r.returncode == 0, event
        outs[event] = json.loads(r.stdout.decode("utf-8"))
    assert "CORE RULES" in outs["SessionStart"]["injectSteps"][0]["systemMessage"]["systemMessage"]
    assert outs["PreInvocation"] == {} and outs["PostToolUse"] == {} and outs["Stop"] == {"decision": "allow"}
    log = hook_log(project)
    assert all(e["host"] == "antigravity" and e["decision"] != "error" for e in log)
    assert [e for e in log if e["event"] == "post-tool-use"][0]["target"] == "a.py"
    assert not (DIR / ".claude").exists()


# ---- agy itself, when installed ---------------------------------------------------

AGY = shutil.which("agy") or shutil.which(os.path.expanduser("~/.local/bin/agy"))


@pytest.mark.skipif(not AGY, reason="agy is not installed (CI's validate job runs it)")
def test_agy_validate_strict():
    r = subprocess.run([AGY, "plugin", "validate", "--strict", str(DIR)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr


# ---- uccif setup antigravity ------------------------------------------------------

def agents(project):
    return project.root / ".agents"


def tree(root):
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()) if root.is_dir() else []


def test_setup_writes_the_workspace_files(project):
    setup_mod.setup(project)
    root = agents(project)
    assert set(tree(root)) == {".uccif-setup.json", "rules/uccif.md", "mcp_config.json",
                               "skills/init/SKILL.md", "skills/codegraph/SKILL.md", "skills/resume/SKILL.md"}
    rule = (root / "rules" / "uccif.md").read_text(encoding="utf-8")
    assert rule.startswith("---\ntrigger: always_on\n") and "UCCIF CORE RULES" in rule
    assert hooks.UCCIF_BIN.as_posix() in rule
    cfg = json.loads((root / "mcp_config.json").read_text(encoding="utf-8"))
    assert cfg["mcpServers"]["codegraph"]["command"] == "codegraph"
    assert (root / "skills" / "init" / "SKILL.md").read_text(encoding="utf-8") == hostfiles.skills("antigravity")["init"]
    assert hosts.enabled(project) == ["antigravity"]


def test_setup_rule_means_session_start_does_not_repeat_core_rules(project):
    setup_mod.setup(project)
    text = call("SessionStart", common(project))["injectSteps"][0]["systemMessage"]["systemMessage"]
    assert "CORE RULES" not in text


def test_remove_restores_an_empty_project(project):
    setup_mod.setup(project)
    setup_mod.remove(project)
    assert not agents(project).exists()


def test_user_files_survive_setup_and_remove(project):
    root = agents(project)
    (root / "rules").mkdir(parents=True)
    (root / "skills" / "mine").mkdir(parents=True)
    (root / "rules" / "team.md").write_text("team")
    (root / "skills" / "mine" / "SKILL.md").write_text("mine")
    (root / "mcp_config.json").write_text('{"mcpServers": {"other": {"command": "x"}}}')
    lines = setup_mod.setup(project)
    assert json.loads((root / "mcp_config.json").read_text())["mcpServers"] == {"other": {"command": "x"}}
    assert any("Skipped .agents/mcp_config.json" in l for l in lines)
    assert any('"codegraph"' in l for l in lines)  # says what to add
    setup_mod.remove(project)
    assert set(tree(root)) == {"rules/team.md", "skills/mine/SKILL.md", "mcp_config.json"}
    assert (root / "mcp_config.json").read_text().startswith('{"mcpServers": {"other"')


def test_existing_skill_with_the_same_name_is_not_overwritten(project):
    p = agents(project) / "skills" / "init" / "SKILL.md"
    p.parent.mkdir(parents=True)
    p.write_text("mine")
    setup_mod.setup(project)
    assert p.read_text() == "mine"
    setup_mod.remove(project)
    assert p.read_text() == "mine"


def test_edited_file_is_kept_by_rerun_and_remove(project):
    setup_mod.setup(project)
    p = agents(project) / "rules" / "uccif.md"
    p.write_text("edited")
    assert any("you edited it" in l for l in setup_mod.setup(project))
    assert p.read_text() == "edited"
    assert any("Kept .agents/rules/uccif.md" in l for l in setup_mod.remove(project))
    assert p.read_text() == "edited"


def test_rerun_refreshes_its_own_files(project, monkeypatch):
    setup_mod.setup(project)
    p = agents(project) / "rules" / "uccif.md"
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_REPLY_LANGUAGE", "en")
    setup_mod.setup(project)
    assert "Reply in en" in p.read_text(encoding="utf-8")
    setup_mod.remove(project)
    assert not agents(project).exists()


def test_remove_without_setup_changes_nothing(project):
    assert "Nothing to remove" in setup_mod.remove(project)[0]


def test_cli_setup_and_remove(project, repo, monkeypatch):
    from uccif_lib import cli
    monkeypatch.chdir(repo)
    assert cli.main(["setup", "antigravity"]) == 0
    assert (repo / ".agents" / "rules" / "uccif.md").exists()
    assert cli.main(["setup", "antigravity", "--remove"]) == 0
    assert not (repo / ".agents").exists()
