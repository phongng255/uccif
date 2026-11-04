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
.agents/skills/ alias. Antigravity is not verified yet: its I/O is treated as Claude-shaped.
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
    table = GEMINI_EVENTS if host == "gemini" else CLAUDE_EVENTS
    return table.get(event, event)


def tool_name(host, name):
    """Claude Code tool name for a host tool name; unknown names pass through."""
    if host != "gemini" or not name:
        return name
    if name in GEMINI_TOOLS:
        return GEMINI_TOOLS[name]
    return name


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


def normalize(host, event, data):
    """(internal_event, data) with Claude Code names. `data` is not modified in place."""
    event = event_name(host, event)
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
    if not out or host != "gemini":
        return out
    res = {}
    if out.get("systemMessage"):
        res["systemMessage"] = out["systemMessage"]
    ctx = (out.get("hookSpecificOutput") or {}).get("additionalContext")
    if ctx and event in GEMINI_CONTEXT:
        res["hookSpecificOutput"] = {"hookEventName": GEMINI_CONTEXT[event], "additionalContext": ctx}
    return res or None


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
