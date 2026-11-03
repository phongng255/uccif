"""Hook handlers: `uccif hook <event>` reads the hook JSON on stdin.

Rules for every handler:
- the core plugin never blocks: no exit 2, no decision "block", no "deny";
  things a strict mode would stop are logged as decision "would_block";
- any exception is logged as decision "error" and the process still exits 0;
- exactly one hooks.jsonl line per invocation, except PreToolUse calls that
  skip (every main-agent Bash call): logging those would bloat hooks.jsonl;
- output to Claude goes through hookSpecificOutput.additionalContext, output
  to the user through systemMessage (Stop token line only).

`uccif hook --agent antigravity <event>` serves the same handlers to Antigravity CLI
(`agy`, Gemini CLI's successor; plugin hooks in `hooks.json`): its camelCase stdin is
mapped to the Claude-style fields first (`from_antigravity`), and the answer is mapped
back (`to_antigravity`): SessionStart context becomes `injectSteps`.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from uccif_lib import codegraph, detect, drift, log, skillgen, task, usage
from uccif_lib.paths import CORE_MARKER, data_root, read_json, resolve_project, write_json
from uccif_lib.rules import core_rules, user_rules

SLOW_MS = {"session-start": 3000, "user-prompt-submit": 300, "pre-tool-use": 300,
           "post-tool-use": 500, "stop": 1000}
EDIT_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")
SEARCH_CMD = re.compile(r"(^|[\s|;&(])(grep|rg|ag|find|fd|ack)\s")
# Bash commands each UCCIF agent may run; anything else is logged as would_block.
AGENT_BASH = {
    "project-analyst": (r"^uccif\s", r"^codegraph\s"),
    "code-impact-analyzer": (r"^uccif\s", r"^codegraph\s"),
    "change-reviewer": (r"^git\s+(diff|show|log|status)\b", r"^codegraph\s", r"^git\s+diff\b.*\|\s*codegraph\s"),
}
DEFAULTS = {"context_window": "auto", "clear_hint_tokens": 80000,
            "checkpoint_tokens": 150000, "long_session_tokens": 3000000}


# ---- config -----------------------------------------------------------------

def _bool(val, default):
    if val is None or val == "":
        return default
    return str(val).strip().lower() not in ("false", "0", "off", "no")


def options():
    """userConfig values. Hooks get CLAUDE_PLUGIN_OPTION_*; Bash-run commands
    don't, so SessionStart caches them in <data_root>/options.json."""
    cached = read_json(data_root() / CORE_MARKER, {})
    lang = os.environ.get("CLAUDE_PLUGIN_OPTION_REPLY_LANGUAGE") or cached.get("reply_language") or "vi"
    report = _bool(os.environ.get("CLAUDE_PLUGIN_OPTION_TOKEN_REPORT"), cached.get("token_report", True))
    setup = _bool(os.environ.get("CLAUDE_PLUGIN_OPTION_AUTO_SETUP"), cached.get("auto_setup", True))
    return {"reply_language": lang, "token_report": report, "auto_setup": setup}


def project_config(project):
    cfg = dict(DEFAULTS)
    cfg.update(read_json(project.docs_dir / "config.json", {}) or {})
    return cfg


LSP_BUNDLED = {  # languages the plugin's .lsp.json configures -> (binary, install command)
    "typescript": ("typescript-language-server", "npm install -g typescript-language-server typescript"),
    "javascript": ("typescript-language-server", "npm install -g typescript-language-server typescript"),
    "python": ("pyright-langserver", "npm install -g pyright"),
}
ENTRY = Path(__file__).resolve().parent.parent / "scripts" / "uccif_main.py"


def spawn(args, project, agent=None):
    """Run `uccif <args>` detached so a hook returns at once (drift check).
    UCCIF_SYNC=1 runs it inline instead (tests, debugging)."""
    env = dict(os.environ, UCCIF_DATA_DIR=str(data_root()), CLAUDE_PROJECT_DIR=str(project.root))
    if agent:
        env["UCCIF_AGENT"] = agent  # maintain also writes project skills to .agents/skills/
    if os.environ.get("UCCIF_SYNC") == "1":
        from uccif_lib import cli
        old = os.environ.get("UCCIF_AGENT")
        if agent:
            os.environ["UCCIF_AGENT"] = agent
        try:
            cli.main(list(args))
        finally:
            if agent and old is None:
                os.environ.pop("UCCIF_AGENT", None)
            elif agent:
                os.environ["UCCIF_AGENT"] = old
        return
    kw = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL,
          "cwd": str(project.root), "env": env}
    if os.name == "nt":
        kw["creationflags"] = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    else:
        kw["start_new_session"] = True
    subprocess.Popen([sys.executable, str(ENTRY)] + list(args), **kw)


def lsp_offer(project):
    """One line asking Claude to offer a missing language server, once per binary per machine."""
    langs = detect.language_counts(project.root)
    total = sum(langs.values()) or 1
    offered_path = data_root() / "lsp_offered.json"
    offered = read_json(offered_path, {}) or {}
    for lang, count in sorted(langs.items(), key=lambda kv: -kv[1]):
        if lang not in LSP_BUNDLED or (count < 20 and count / total < 0.1):
            continue
        binary, cmd = LSP_BUNDLED[lang]
        if shutil.which(binary) or binary in offered:
            continue
        offered[binary] = {"ts": time.time(), "project": str(project.root)}
        write_json(offered_path, offered)
        return ("The %s language server (%s) is not installed, so precise go-to-definition/references "
                "fall back to CodeGraph / Grep. Ask the user once, in your next reply, whether to install it "
                "with `%s` (then /reload-plugins). If they agree, run it yourself." % (lang, binary, cmd))
    return None


def _ctx(event, text):
    return {"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}}


def _rel(project, path):
    try:
        # always '/'-separated: task file lists and index keys must match on Windows too
        return Path(os.path.realpath(path)).relative_to(project.root).as_posix()
    except (ValueError, TypeError):
        return None


# ---- handlers: each returns (output_dict_or_None, log_fields) ---------------

def on_session_start(data, project):
    source = data.get("source") or "startup"
    sid = data.get("session_id")
    opts = options()

    task.migrate_from_data_dir(project)  # 3.0.0-dev.1..3 kept tasks in the plugin data dir
    prev = log.last_session_unclosed(project)
    if prev and prev != sid:
        log.session(project, session=prev, type="end", reason="unclean")
    cur = task.load_current(project)
    log.session(project, session=sid, type="start", source=source,
                task=cur["id"] if cur and cur.get("status") != "done" else None)

    write_json(data_root() / CORE_MARKER, opts)
    env_file = os.environ.get("CLAUDE_ENV_FILE")
    if env_file:
        quoted = "'" + str(data_root()).replace("'", "'\\''") + "'"
        with open(env_file, "a", encoding="utf-8") as f:
            f.write("export UCCIF_DATA_DIR=%s\n" % quoted)

    parts, n_user = [], 0
    if source in ("startup", "clear", "compact"):
        parts.append(core_rules(opts["reply_language"]))
        try:  # the user's own rules, right after the core (never fails the hook)
            extra = user_rules(project)
        except Exception:
            extra = ""
        if extra:
            parts.append(extra)
            n_user = extra.count("USER RULES (")
    spawn(["maintain"], project, data.get("_agent"))  # drift check, CodeGraph index + project skills in the background
    parts.append(codegraph.context_line(project))
    mine = skillgen.generated(project)
    is_ag = data.get("_agent") == ANTIGRAVITY or getattr(project, "agent", "claude") == ANTIGRAVITY
    if mine:
        maps = [n for n in mine if n.endswith("-map")]
        fixes = [n for n in mine if n.endswith("-bugfix")]
        skills_folder = ".agents/skills/" if is_ag else ".claude/skills/"
        parts.append("Project skills generated from CodeGraph in %s: %s%s, %d module skills. "
                     "Use the map skill to know where code lives and the bugfix skill for any reported bug."
                     % (skills_folder, ", ".join(maps + fixes), "" if maps else " (no map)", len(mine) - len(maps) - len(fixes)))
    if is_ag:
        parts.append(antigravity_line())
    else:
        offer = lsp_offer(project)  # .lsp.json is a Claude Code plugin feature
        if offer:
            parts.append(offer)
    docs = project.docs_dir
    docs_rel = project.docs_subdir.as_posix()
    if (docs / "summary.md").exists():
        parts.append("Project docs: %s/ (summary.md, architecture.md). Read only the section you need." % docs_rel)
    else:
        parts.append("UCCIF: this project has not been surveyed yet. Before the first code change, "
                     "run the uccif:init skill (limited survey, read-only until docs are written).")
    lines = task.summary_lines(project)
    if lines:
        parts.append("\n".join(lines) + "\nIf the user's request continues it, use the uccif:resume skill.")
    fields = {"rule": "context", "target": source}
    if n_user:
        fields["user_rules"] = n_user
    return _ctx("SessionStart", "\n\n".join(parts)), fields


def on_user_prompt_submit(data, project):
    prompt = data.get("prompt") or ""
    lang = options()["reply_language"]
    quick = "#quick" in prompt
    lines = [] if quick else task.summary_lines(project)
    stale = drift.pending(project)
    if stale:
        docs_rel = project.docs_subdir.as_posix()
        lines.append("Project docs are stale (%s/): " % docs_rel + "; ".join(stale) +
                     ". Update only those sections when convenient, then run `uccif drift ack`.")
    lines.append("Reply in %s. Do ops work yourself. To find code, query CodeGraph first "
                 "(`codegraph_explore`, or `codegraph explore` in Bash); code changes follow the uccif task flow."
                 % lang)
    return _ctx("UserPromptSubmit", "\n".join(lines)), {"rule": "quick" if quick else "reminder",
                                                       "drift": len(stale) or None}


def on_pre_tool_use(data, project):
    agent = (data.get("agent_type") or "").split(":")[-1]
    if not data.get("agent_id") or agent not in AGENT_BASH:
        return None, {"decision": "skip"}
    cmd = ((data.get("tool_input") or {}).get("command") or "").strip()
    if any(re.match(p, cmd) for p in AGENT_BASH[agent]):
        return None, {"decision": "allow", "rule": "agent-bash", "target": cmd}
    return None, {"decision": "would_block", "rule": "agent-bash", "target": cmd, "agent": agent}


def on_post_tool_use(data, project):
    ti = data.get("tool_input") or {}
    path = ti.get("file_path") or ti.get("notebook_path")
    rel = _rel(project, path) if path else None
    if not rel or rel.startswith((".claude/", ".gemini/", ".agents/")):
        return None, {"decision": "skip", "target": path}
    added = task.add_modified(project, rel)
    return None, {"rule": "task-files" if added else "no-task", "target": rel}


def on_post_tool_use_failure(data, project):
    if data.get("is_interrupt"):
        return None, {"decision": "skip"}
    tool = data.get("tool_name")
    cmd = (data.get("tool_input") or {}).get("command") or ""
    if tool not in ("Grep", "Glob") and not (tool == "Bash" and SEARCH_CMD.search(" " + cmd)):
        return None, {"decision": "skip"}
    first = next((l for l in (data.get("error") or "").splitlines()
                  if l.strip() and not l.startswith("Exit code")), "unknown error")
    msg = ("A search command failed: %s. Fix the command and rerun it, or report it; "
           "do not treat it as 'no matches'. Then report to the user in %s."
           % (first[:200], options()["reply_language"]))
    return _ctx("PostToolUseFailure", msg), {"decision": "nudge", "rule": "search-failed", "target": first}


def on_subagent_start(data, project):
    return None, {"rule": "agent", "target": data.get("agent_type"), "agent_id": data.get("agent_id")}


def on_subagent_stop(data, project):
    last = data.get("last_assistant_message") or ""
    return None, {
        "rule": "agent", "target": data.get("agent_type"), "agent_id": data.get("agent_id"),
        "tokens": usage.agent_tokens(data.get("agent_transcript_path")),
        "partial": "partial" in last.lower(), "out_lines": len(last.splitlines()),
    }


def on_stop(data, project):
    if data.get("stop_hook_active"):
        return None, {"decision": "skip", "rule": "rerun"}
    # structural changes made by Bash, by the user, or by git pull/checkout this turn
    spawn(["maintain"], project, data.get("_agent"))
    if data.get("_agent") == ANTIGRAVITY:  # its transcript is not Claude's: no real token count to report
        return None, {"rule": "maintain"}
    cfg = project_config(project)
    window = cfg["context_window"] if isinstance(cfg["context_window"], int) else "auto"
    s = usage.summarize(data.get("transcript_path"), window)
    cur = task.load_current(project)
    open_task = cur["id"] if cur and cur.get("status") != "done" else None
    if s:
        log.usage(project, session=data.get("session_id"), turn=s["turns"], task=open_task,
                  tokens_in=s["turn"]["in"], tokens_out=s["turn"]["output_tokens"],
                  cache_read=s["turn"]["cache_read_input_tokens"], ctx=s["ctx"], model=s["model"])
    if not options()["token_report"]:
        return None, {"rule": "token-off"}
    line = "🔢 " + usage.token_line(s)
    if s:
        total = s["session"]["in"] + s["session"]["output_tokens"]
        if not open_task and cur and s["ctx"] >= cfg["clear_hint_tokens"]:
            line += " · 💡 /clear recommended (task saved)"
        elif open_task and s["ctx"] >= cfg["checkpoint_tokens"]:
            line += " · 💡 checkpoint, then /clear"
        elif total >= cfg["long_session_tokens"]:
            line += " · 💡 long session"
    return {"systemMessage": line}, {"rule": "token-line"}


def on_pre_compact(data, project):
    task.snapshot(project, label="precompact")
    log.session(project, session=data.get("session_id"), type="compact", trigger=data.get("trigger"))
    return None, {"rule": "snapshot", "target": data.get("trigger")}


def on_post_compact(data, project):
    return None, {"rule": "log", "target": data.get("trigger")}


def on_session_end(data, project):
    task.snapshot(project, label="sessionend")
    s = usage.summarize(data.get("transcript_path"))
    cur = task.load_current(project)
    log.session(project, session=data.get("session_id"), type="end", reason=data.get("reason"),
                turns=s["turns"] if s else None,
                tokens=(s["session"]["in"] + s["session"]["output_tokens"]) if s else None,
                task=cur["id"] if cur else None, task_status=cur.get("status") if cur else None)
    log.prune(project)
    return None, {"rule": "snapshot", "target": data.get("reason")}


def on_instructions_loaded(data, project):
    path = data.get("file_path") or ""
    if data.get("memory_type") != "Project" or _rel(project, path) not in ("CLAUDE.md", "GEMINI.md", "AGENTS.md"):
        return None, {"decision": "skip"}
    try:
        has_block = "<!-- UCCIF:BEGIN -->" in Path(path).read_text(encoding="utf-8")
    except OSError:
        has_block = False
    return None, {"rule": "claude-md-block", "target": "present" if has_block else "missing"}


# ---- Antigravity CLI (agy) -------------------------------------------------------

ANTIGRAVITY = "antigravity"
AGENTS = ("claude", ANTIGRAVITY)
# Antigravity tool names -> the Claude tool names the handlers know
AG_TOOLS = {"run_command": "Bash", "write_to_file": "Write", "replace_file_content": "Edit",
            "multi_replace_file_content": "MultiEdit", "grep_search": "Grep", "find_by_name": "Glob",
            "view_file": "Read"}
AG_PATH_KEYS = ("TargetFile", "targetFile", "target_file", "file_path", "filePath", "AbsolutePath",
                "absolutePath", "path")
AG_CMD_KEYS = ("CommandLine", "commandLine", "command", "cmd")
LAUNCHER = Path(__file__).resolve().parent.parent / "bin" / "uccif"


def _first(d, keys):
    for k in keys:
        v = d.get(k)
        if isinstance(v, str) and v:
            return v
    return None


def from_antigravity(data):
    """Antigravity hook stdin (camelCase: conversationId, workspacePaths, transcriptPath, toolCall
    {name, args}, error, ...) -> the Claude-style fields the handlers read."""
    call = data.get("toolCall") or {}
    args = call.get("args") if isinstance(call.get("args"), dict) else {}
    ws = data.get("workspacePaths") or []
    out = {"_agent": ANTIGRAVITY, "session_id": data.get("conversationId"),
           "transcript_path": data.get("transcriptPath"),
           "cwd": ws[0] if isinstance(ws, list) and ws else None,
           "source": "startup"}
    if call:
        out["tool_name"] = AG_TOOLS.get(call.get("name"), call.get("name"))
        ti = {}
        path, cmd = _first(args, AG_PATH_KEYS), _first(args, AG_CMD_KEYS)
        if path:
            if out["cwd"] and not os.path.isabs(path):
                path = os.path.join(out["cwd"], path)
            ti["file_path"] = os.path.normpath(path)  # Windows: no mixed / and \ separators
        if cmd:
            ti["command"] = cmd
        out["tool_input"] = ti
    if data.get("error"):
        out["error"] = str(data["error"])
    return out


def to_antigravity(event, out):
    """Handler output -> Antigravity stdout. Context is injected as a step at SessionStart; other
    events have no context channel, and the core never blocks, so they answer nothing."""
    text = ((out or {}).get("hookSpecificOutput") or {}).get("additionalContext")
    if event == "session-start" and text:
        return {"injectSteps": [{"userMessage": text}]}
    return None


def antigravity_line():
    return ("Antigravity CLI: UCCIF's `uccif` command is not on PATH here; run it by its full path "
            "`sh \"%s\" <args>` wherever a skill says `uccif <args>`. Project skills generated from "
            "CodeGraph are also written to .agents/skills/. Claude-only steps (restart Claude Code, "
            "/reload-plugins, Claude subagents) do not apply: restart `agy` instead." % LAUNCHER.as_posix())


HANDLERS = {
    "session-start": on_session_start,
    "user-prompt-submit": on_user_prompt_submit,
    "pre-tool-use": on_pre_tool_use,
    "post-tool-use": on_post_tool_use,
    "post-tool-use-failure": on_post_tool_use_failure,
    "subagent-start": on_subagent_start,
    "subagent-stop": on_subagent_stop,
    "stop": on_stop,
    "pre-compact": on_pre_compact,
    "post-compact": on_post_compact,
    "session-end": on_session_end,
    "instructions-loaded": on_instructions_loaded,
}


def run(event, stdin=None, stdout=None, agent="claude"):
    """Entry for `uccif hook [--agent claude|antigravity] <event>`. Always returns 0."""
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    t0 = time.time()
    fields, out, project = {}, None, None
    try:
        raw = stdin.read()
        data = json.loads(raw) if raw.strip() else {}
        if agent == ANTIGRAVITY:
            data = from_antigravity(data if isinstance(data, dict) else {})
        handler = HANDLERS.get(event)
        if handler is None:
            raise ValueError("unknown hook event: %s" % event)
        project = resolve_project(data.get("cwd"), agent=agent)
        out, fields = handler(data, project)
        fields.setdefault("decision", "nudge" if out and event != "stop" else "allow")
        fields.update(session=data.get("session_id"), tool=data.get("tool_name"),
                      task=(task.load_current(project) or {}).get("id"))
        if data.get("agent_id") and "agent_id" not in fields:
            fields["agent_id"] = data.get("agent_id")
        if agent != "claude":
            fields["agent"] = agent
    except Exception as e:  # never break the session
        fields = {"decision": "error", "error": "%s: %s" % (type(e).__name__, str(e)[:200])}
        out = None
    ms = int((time.time() - t0) * 1000)
    fields.update(event=event, ms=ms)
    if ms > SLOW_MS.get(event, 1000):
        fields["slow"] = True
    quiet = event == "pre-tool-use" and fields.get("decision") == "skip" and not fields.get("slow")
    try:
        if project is None:
            project = resolve_project()
        if not quiet:
            log.hook(project, **fields)
    except Exception:
        pass
    if agent == ANTIGRAVITY:
        out = to_antigravity(event, out)
    if out:
        try:
            # ASCII-escaped JSON: valid for Claude Code whatever the stream encoding is
            stdout.write(json.dumps(out, ensure_ascii=True))
        except Exception:
            pass
    return 0
