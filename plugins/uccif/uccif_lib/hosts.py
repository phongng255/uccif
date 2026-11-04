"""Host adapters: the one place that knows how Claude Code, Gemini CLI and Antigravity differ.

The hook logic in hooks.py is written once, against Claude Code's names (event kebab names,
tool names Bash/Read/Edit/Write/Grep/Glob, `tool_input.file_path`, `tool_input.command`).
For another host this module translates
- the event name (`uccif hook --host gemini BeforeTool` -> pre-tool-use),
- the hook stdin (tool names, MCP tool names, failure shape),
- the hook stdout (which events may carry additionalContext, and under which event name),
and says where each host reads project skills.

Gemini CLI facts (hooks reference at geminicli.com/docs/hooks/reference, tool names from
@google/gemini-cli 0.66.0): events SessionStart, BeforeAgent, BeforeTool, AfterTool, AfterAgent,
PreCompress, SessionEnd (+ model/notification events UCCIF does not use);
hookSpecificOutput.additionalContext only on SessionStart, BeforeAgent and AfterTool; MCP tools
are named mcp_<server>_<tool>; workspace skills are read from .gemini/skills/ or the
.agents/skills/ alias.

Antigravity facts (antigravity.google/docs/hooks and the contract embedded in agy 1.4.12): events
SessionStart, PreToolUse, PostToolUse, PreInvocation, PostInvocation, Stop; hooks run with the
plugin root as cwd; stdin is camelCase (conversationId, workspacePaths, transcriptPath,
toolCall{name, args}, error, fullyIdle) and has no prompt text; stdout must be a JSON object, with
context in injectSteps and a required decision on Stop and PreToolUse. No event reaches the user
with text unless it is a step the model also gets, and there is no compact or session-end event.
"""

import re
from pathlib import Path

HOSTS = ("claude", "gemini", "antigravity")

# skill dir per host, relative to the project root. Gemini CLI and Antigravity both read
# .agents/skills/, so one copy serves both.
SKILL_DIRS = {
    "claude": Path(".claude") / "skills",
    "gemini": Path(".agents") / "skills",
    "antigravity": Path(".agents") / "skills",
}

CLAUDE_EVENTS = {
    "SessionStart": "session-start", "UserPromptSubmit": "user-prompt-submit",
    "PreToolUse": "pre-tool-use", "PostToolUse": "post-tool-use",
    "PostToolUseFailure": "post-tool-use-failure", "SubagentStart": "subagent-start",
    "SubagentStop": "subagent-stop", "Stop": "stop", "PreCompact": "pre-compact",
    "PostCompact": "post-compact", "SessionEnd": "session-end",
    "InstructionsLoaded": "instructions-loaded",
}
GEMINI_EVENTS = {
    "SessionStart": "session-start", "BeforeAgent": "user-prompt-submit",
    "BeforeTool": "pre-tool-use", "AfterTool": "post-tool-use", "AfterAgent": "stop",
    "PreCompress": "pre-compact", "SessionEnd": "session-end",
}
GEMINI_TOOLS = {
    "run_shell_command": "Bash", "read_file": "Read", "read_many_files": "Read",
    "replace": "Edit", "write_file": "Write", "glob": "Glob", "grep_search": "Grep",
    "search_file_content": "Grep", "list_directory": "LS",
}
ANTIGRAVITY_EVENTS = {
    "SessionStart": "session-start", "PreInvocation": "user-prompt-submit",
    "PreToolUse": "pre-tool-use", "PostToolUse": "post-tool-use", "Stop": "stop",
}
ANTIGRAVITY_TOOLS = {
    "run_command": "Bash", "view_file": "Read", "read_file": "Read", "edit_file": "Edit",
    "replace_file_content": "Edit", "multi_replace_file_content": "Edit", "write_to_file": "Write",
    "write_file": "Write", "grep_search": "Grep", "find_by_name": "Glob", "list_dir": "LS",
}
ANTIGRAVITY_PATH_ARGS = ("TargetFile", "AbsolutePath", "FilePath", "file_path", "absolute_path")
# internal event -> Gemini event that may carry additionalContext
GEMINI_CONTEXT = {"session-start": "SessionStart", "user-prompt-submit": "BeforeAgent",
                  "post-tool-use": "AfterTool", "post-tool-use-failure": "AfterTool"}


class UnknownHost(ValueError):
    pass


def check(host):
    if host not in HOSTS:
        raise UnknownHost("unknown host: %s (expected one of %s)" % (host, ", ".join(HOSTS)))
    return host


def event_name(host, event):
    """Internal kebab event name for what the host passed (native or already kebab)."""
    table = {"gemini": GEMINI_EVENTS, "antigravity": ANTIGRAVITY_EVENTS}.get(host, CLAUDE_EVENTS)
    return table.get(event, event)


def tool_name(host, name):
    """Claude Code tool name for a host tool name; unknown names pass through."""
    table = {"gemini": GEMINI_TOOLS, "antigravity": ANTIGRAVITY_TOOLS}.get(host)
    if not table or not name:
        return name
    return table.get(name, name)


def _gemini_mcp(name, mcp_context):
    server = (mcp_context or {}).get("server_name") if isinstance(mcp_context, dict) else None
    if server and name.startswith("mcp_%s_" % server):
        return "mcp__%s__%s" % (server, name[len("mcp_%s_" % server):])
    m = re.match(r"^mcp_([^_]+)_(.+)$", name)
    return "mcp__%s__%s" % (m.group(1), m.group(2)) if m else name


def _error_text(resp):
    if not isinstance(resp, dict):
        return None
    err = resp.get("error")
    if isinstance(err, dict):
        return err.get("message") or str(err)
    return str(err) if err else None


def _normalize_antigravity(event, data):
    paths = data.get("workspacePaths") or []
    if not paths:  # cwd is the plugin root here, which is not the user's project
        raise ValueError("no workspacePaths in the hook input")
    out = dict(data, cwd=paths[0], session_id=data.get("conversationId"),
               transcript_path=data.get("transcriptPath"))
    call = data.get("toolCall") or {}
    if call:
        args = call.get("args") if isinstance(call.get("args"), dict) else {}
        out["tool_name"] = tool_name("antigravity", call.get("name"))
        out["tool_input"] = {"command": args.get("CommandLine"),
                             "file_path": next((args[k] for k in ANTIGRAVITY_PATH_ARGS if args.get(k)), None)}
    if event == "post-tool-use" and data.get("error"):
        event = "post-tool-use-failure"
    if event == "stop":  # background work still running: the turn is not over
        out["stop_hook_active"] = not data.get("fullyIdle", True)
    return event, out


def normalize(host, event, data):
    """(internal_event, data) with Claude Code names. `data` is not modified in place."""
    event = event_name(host, event)
    if host == "antigravity":
        return _normalize_antigravity(event, data)
    if host != "gemini":
        return event, data
    data = dict(data)
    name = data.get("tool_name") or ""
    if name.startswith("mcp_"):
        data["tool_name"] = _gemini_mcp(name, data.get("mcp_context"))
    else:
        data["tool_name"] = tool_name(host, name) or None
    if event == "post-tool-use":
        err = _error_text(data.get("tool_response"))
        if err:  # Gemini has no PostToolUseFailure: a failed tool is an AfterTool with an error
            event, data["error"] = "post-tool-use-failure", err
    return event, data


def format_output(host, event, out):
    """Turn a Claude-shaped hook result into what the host reads; None drops it."""
    if not out or host == "claude":
        return out
    ctx = (out.get("hookSpecificOutput") or {}).get("additionalContext")
    if host == "antigravity":
        if ctx and event == "session-start":  # systemMessage must be a nested object
            return {"injectSteps": [{"systemMessage": {"systemMessage": ctx}}]}
        if ctx and event == "user-prompt-submit":
            return {"injectSteps": [{"ephemeralMessage": ctx}]}
        return None
    res = {}
    if out.get("systemMessage"):
        res["systemMessage"] = out["systemMessage"]
    if ctx and event in GEMINI_CONTEXT:
        res["hookSpecificOutput"] = {"hookEventName": GEMINI_CONTEXT[event], "additionalContext": ctx}
    return res or None


def default_output(host, event):
    """What a host needs on stdout when a hook has nothing to say. Antigravity requires a JSON
    object, and on Stop a decision; anything but "continue" lets the agent stop."""
    if host != "antigravity":
        return None
    return {"decision": "allow"} if event == "stop" else {}


# ---- which hosts a project uses ----------------------------------------------------

def _state_path(project):
    return Path(project.local_dir) / "hosts.json"


def record(project, host):
    """Remember that `host` ran a session in this project (SessionStart)."""
    from uccif_lib.paths import ensure_local, now_iso, read_json, write_json
    seen = read_json(_state_path(project), {}) or {}
    if host in seen:
        return
    ensure_local(project)
    seen[host] = now_iso()
    write_json(_state_path(project), seen)


def enabled(project):
    """Hosts this project uses: the ones that ran a session here, plus Antigravity when
    `uccif setup antigravity` wrote its rule file. Nothing recorded -> Claude Code (1.1 behavior)."""
    from uccif_lib.paths import read_json
    seen = set(read_json(_state_path(project), {}) or {})
    if (Path(project.root) / ".agents" / "rules" / "uccif.md").exists():
        seen.add("antigravity")
    if not seen:
        seen.add("claude")
    return [h for h in HOSTS if h in seen]


def skill_dirs(project, hosts=None):
    """Distinct skill dirs (absolute) for the given hosts (default: the enabled ones)."""
    out = []
    for h in hosts or enabled(project):
        d = Path(project.root) / SKILL_DIRS[h]
        if d not in out:
            out.append(d)
    return out
