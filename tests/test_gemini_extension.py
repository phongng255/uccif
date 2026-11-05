"""Gemini CLI extension at the repo root: manifest, hooks/hooks.json run for real through a shell
with JSON shaped like the Gemini hooks reference, skills built from the Claude plugin's skills,
and the Gemini transcript read for the token line."""

import json
import os
import re
import subprocess
import sys

import pytest

from conftest import PLUGIN, REPO, hook_log, write_transcript
from uccif_lib import hooks, usage

MANIFEST = json.loads((REPO / "gemini-extension.json").read_text(encoding="utf-8"))
HOOKS = json.loads((REPO / "hooks" / "hooks.json").read_text(encoding="utf-8"))
GEMINI_EVENTS = {"BeforeTool", "AfterTool", "BeforeAgent", "AfterAgent", "BeforeModel",
                 "BeforeToolSelection", "AfterModel", "SessionStart", "SessionEnd", "Notification",
                 "PreCompress"}


def test_manifest_fields():
    assert MANIFEST["name"] == "uccif"
    plugin = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert MANIFEST["version"] == plugin["version"]
    assert (REPO / MANIFEST["contextFileName"]).is_file()
    cg = MANIFEST["mcpServers"]["codegraph"]
    assert cg["command"] == "codegraph" and cg["args"] == ["serve", "--mcp"]
    assert cg["env"]["CODEGRAPH_MCP_TOOLS"] == "explore"
    claude_mcp = json.loads((PLUGIN / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]["codegraph"]
    assert cg["env"] == claude_mcp["env"] and cg["args"] == claude_mcp["args"]  # same server as Claude
    assert {s["envVar"] for s in MANIFEST["settings"]} == {
        "UCCIF_REPLY_LANGUAGE", "UCCIF_TOKEN_REPORT", "UCCIF_AUTO_SETUP"}


def test_settings_env_reach_options(monkeypatch):
    monkeypatch.delenv("CLAUDE_PLUGIN_OPTION_AUTO_SETUP", raising=False)
    monkeypatch.setenv("UCCIF_REPLY_LANGUAGE", "en")
    monkeypatch.setenv("UCCIF_TOKEN_REPORT", "false")
    monkeypatch.setenv("UCCIF_AUTO_SETUP", "false")
    assert hooks.options() == {"reply_language": "en", "token_report": False, "auto_setup": False}


def test_hooks_json_shape():
    assert set(HOOKS["hooks"]) <= GEMINI_EVENTS
    assert set(HOOKS["hooks"]) == {"SessionStart", "BeforeAgent", "BeforeTool", "AfterTool",
                                   "AfterAgent", "PreCompress", "SessionEnd"}
    for event, entries in HOOKS["hooks"].items():
        for entry in entries:
            for h in entry["hooks"]:
                assert h["type"] == "command" and h["timeout"] <= 10000  # milliseconds in Gemini
                assert h["command"].startswith('"${extensionPath}${/}plugins${/}uccif${/}bin${/}uccif"')
                assert h["command"].endswith("hook --host gemini " + event)
            if "matcher" in entry:
                re.compile(entry["matcher"])


def hydrate(cmd):
    """What Gemini CLI does to hooks.json strings (recursivelyHydrateStrings, 0.66.0)."""
    return cmd.replace("${extensionPath}", str(REPO)).replace("${/}", os.sep)


def run_shell(event, payload, env):
    cmd = hydrate(HOOKS["hooks"][event][0]["hooks"][0]["command"])
    r = subprocess.run(cmd, shell=True, input=json.dumps(payload).encode("utf-8"),
                       capture_output=True, env=env, timeout=60)
    return r.returncode, (json.loads(r.stdout.decode("utf-8")) if r.stdout.strip() else None)


@pytest.mark.skipif(os.name == "nt", reason="bin/uccif is a sh script; Gemini CLI on Windows not verified")
def test_every_hook_runs_through_the_shell(project, tmp_path):
    env = dict(os.environ, GEMINI_PROJECT_DIR=str(project.root), CLAUDE_PROJECT_DIR=str(project.root))
    common = {"session_id": "g1", "transcript_path": str(tmp_path / "t.jsonl"), "cwd": str(project.root),
              "timestamp": "2026-11-04T00:00:00Z"}
    src = project.root / "src" / "a.py"
    src.parent.mkdir()
    src.write_text("x = 1\n")
    write_transcript(tmp_path / "t.jsonl", [
        {"sessionId": "g1", "projectHash": "h", "startTime": "t"},
        {"id": "u1", "type": "user", "content": [{"text": "fix a"}]},
        {"id": "m1", "type": "gemini", "content": "ok", "model": "gemini-3-pro",
         "tokens": {"input": 12000, "output": 300, "cached": 8000, "thoughts": 50, "tool": 0, "total": 12350}},
    ])
    steps = [
        ("SessionStart", {"hook_event_name": "SessionStart", "source": "startup"}),
        ("BeforeAgent", {"hook_event_name": "BeforeAgent", "prompt": "fix the bug in a.py"}),
        ("BeforeTool", {"hook_event_name": "BeforeTool", "tool_name": "grep_search",
                        "tool_input": {"pattern": "x"}, "mcp_context": None, "original_request_name": "grep_search"}),
        ("AfterTool", {"hook_event_name": "AfterTool", "tool_name": "replace",
                       "tool_input": {"file_path": str(src), "old_string": "1", "new_string": "2"},
                       "tool_response": {"llmContent": "ok", "returnDisplay": "ok"}}),
        ("AfterAgent", {"hook_event_name": "AfterAgent", "prompt": "fix", "prompt_response": "done",
                        "stop_hook_active": False}),
        ("PreCompress", {"hook_event_name": "PreCompress", "trigger": "manual"}),
        ("SessionEnd", {"hook_event_name": "SessionEnd", "reason": "exit"}),
    ]
    outs = {}
    for event, payload in steps:
        code, out = run_shell(event, dict(common, **payload), env)
        assert code == 0, event
        outs[event] = out
    ss = outs["SessionStart"]["hookSpecificOutput"]
    assert ss["hookEventName"] == "SessionStart" and "CORE RULES" in ss["additionalContext"]
    assert "is not on PATH here" in ss["additionalContext"]
    assert outs["BeforeTool"] is None  # BeforeTool takes no additionalContext
    assert outs["AfterTool"] is None
    assert outs["AfterAgent"]["systemMessage"].startswith("\U0001f522 Tokens\n   This turn: 12.0k input (8.0k from cache), 350 output")
    assert set(outs["AfterAgent"]) == {"systemMessage"}
    log = [e for e in hook_log(project)]
    assert [e["event"] for e in log] == ["session-start", "user-prompt-submit", "pre-tool-use",
                                         "post-tool-use", "stop", "pre-compact", "session-end"]
    assert all(e.get("host") == "gemini" and e["decision"] != "error" for e in log)
    assert log[2]["rule"] == "search-codegraph-first" and log[3]["target"] == "src/a.py"


def test_skills_built_from_the_plugin_skills():
    sys.path.insert(0, str(PLUGIN / "scripts"))
    import build_gemini
    stale, extra = build_gemini.build(check=True)
    assert stale == [] and extra == [], "run python plugins/uccif/scripts/build_gemini.py"
    for p in (REPO / "skills").glob("*/SKILL.md"):
        text = p.read_text(encoding="utf-8")
        assert "uccif:" not in text and "$ARGUMENTS" not in text and "argument-hint" not in text
        assert "Claude Code" not in text


def test_gemini_transcript_usage(tmp_path):
    t = write_transcript(tmp_path / "s.jsonl", [
        {"sessionId": "s", "projectHash": "h"},
        {"id": "u1", "type": "user", "content": [{"text": "a"}]},
        {"id": "m1", "type": "gemini", "model": "gm", "content": ""},
        {"id": "m1", "type": "gemini", "model": "gm", "content": "x",
         "tokens": {"input": 1000, "output": 10, "cached": 400, "thoughts": 5}},
        {"$set": {"summary": "x"}},
        {"id": "u2", "type": "user", "content": [{"text": "b"}]},
        {"id": "m2", "type": "gemini", "model": "gm", "tokens": {"input": 2000, "output": 20, "cached": 1500}},
        {"id": "m2", "type": "gemini", "model": "gm", "tokens": {"input": 2100, "output": 30, "cached": 1500}},
    ])
    s = usage.summarize(str(t))
    assert s["turns"] == 2 and s["messages"] == 2
    assert s["turn"]["in"] == 2100 and s["turn"]["cache_read_input_tokens"] == 1500 and s["turn"]["output_tokens"] == 30
    assert s["session"]["in"] == 3100 and s["session"]["output_tokens"] == 45 and s["ctx"] == 2100


def test_gemini_whole_json_session(tmp_path):
    p = tmp_path / "session.json"
    p.write_text(json.dumps({"sessionId": "s", "messages": [
        {"id": "u", "type": "user", "content": "a"},
        {"id": "m", "type": "gemini", "tokens": {"input": 50, "output": 5, "cached": 0}}]}))
    s = usage.summarize(str(p))
    assert s["turn"]["in"] == 50 and s["turn"]["output_tokens"] == 5


def test_agents_block_reaches_gemini_not_claude(project):
    from conftest import run_hook
    import io
    (project.root / "AGENTS.md").write_text("# team\nsecret long text\n<!-- UCCIF:BEGIN -->\n## demo\nA lib.\n<!-- UCCIF:END -->\n")
    out = io.StringIO()
    hooks.run("SessionStart", stdin=io.StringIO(json.dumps({"cwd": str(project.root), "source": "startup"})),
              stdout=out, host="gemini")
    ctx = json.loads(out.getvalue())["hookSpecificOutput"]["additionalContext"]
    assert "## demo\nA lib." in ctx and "secret long text" not in ctx
    _, claude = run_hook("session-start", {"cwd": str(project.root), "source": "startup"})
    assert "A lib." not in claude["hookSpecificOutput"]["additionalContext"]  # Claude reads the file itself
    assert "not on PATH" not in claude["hookSpecificOutput"]["additionalContext"]
