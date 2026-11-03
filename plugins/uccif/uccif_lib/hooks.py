"""Hook handlers: `uccif hook <event>` reads the hook JSON on stdin.

Rules for every handler:
- the core plugin never blocks: no exit 2, no decision "block", no "deny";
  things a strict mode would stop are logged as decision "would_block";
- any exception is logged as decision "error" and the process still exits 0;
- exactly one hooks.jsonl line per invocation, except PreToolUse calls that
  skip (every main-agent Bash call): logging those would bloat hooks.jsonl;
- output to Claude goes through hookSpecificOutput.additionalContext, output
  to the user through systemMessage (Stop token line only).
"""

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from uccif_lib import drift, index, log, task, usage
from uccif_lib.paths import CORE_MARKER, data_root, read_json, resolve_project, write_json
from uccif_lib.rules import core_rules, user_rules

SLOW_MS = {"session-start": 3000, "user-prompt-submit": 300, "pre-tool-use": 300,
           "post-tool-use": 500, "stop": 1000}
EDIT_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")
SEARCH_CMD = re.compile(r"(^|[\s|;&(])(grep|rg|ag|find|fd|ack)\s")
# Bash commands each UCCIF agent may run; anything else is logged as would_block.
AGENT_BASH = {
    "project-analyst": (r"^uccif\s",),
    "code-impact-analyzer": (r"^uccif\s",),
    "change-reviewer": (r"^git\s+(diff|show|log|status)\b",),
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
    return {"reply_language": lang, "token_report": report}


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


def spawn(args, project):
    """Run `uccif <args>` detached so a hook returns at once (index build, drift).
    UCCIF_SYNC=1 runs it inline instead (tests, debugging)."""
    env = dict(os.environ, UCCIF_DATA_DIR=str(data_root()), CLAUDE_PROJECT_DIR=str(project.root))
    if os.environ.get("UCCIF_SYNC") == "1":
        from uccif_lib import cli
        cli.main(list(args))
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
    langs = index.languages(project)
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
                "fall back to the code index. Ask the user once, in your next reply, whether to install it "
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
    ready = index.exists(project)
    spawn(["maintain"], project)  # build/refresh the code index and check drift in the background
    if ready:
        parts.append("Code index ready: `uccif index query --symbol X | --file P | --impact P|X | --path A B | "
                     "--tests-for P | --cochange P` "
                     "(refreshes itself; never read the .db).")
    else:
        parts.append("Code index is being built in the background; `uccif index query` waits for it.")
    offer = lsp_offer(project)
    if offer:
        parts.append(offer)
    docs = project.docs_dir
    if (docs / "summary.md").exists():
        parts.append("Project docs: .claude/uccif/ (summary.md, architecture.md). Read only the section you need.")
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
        lines.append("Project docs are stale (.claude/uccif/): " + "; ".join(stale) +
                     ". Update only those sections when convenient, then run `uccif drift ack`.")
    lines.append("Reply in %s. Do ops work yourself. To find code, `uccif index query` first; "
                 "code changes follow the uccif task flow." % lang)
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
    if not rel or rel.startswith(".claude/"):
        return None, {"decision": "skip", "target": path}
    added = task.add_modified(project, rel)
    st = index.update(project, wait=0.3, paths=[rel]) if index.exists(project) else None
    if st and st.get("derived_stale"):
        spawn(["maintain"], project)  # big repo: derived edges catch up in the background
    return None, {"rule": "task-files" if added else "no-task", "target": rel,
                  "indexed": bool(st and st["parsed"])}


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
    # catch edits made by Bash, by the user, or by git pull/checkout this turn
    spawn(["maintain"], project)
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
    if data.get("memory_type") != "Project" or _rel(project, path) != "CLAUDE.md":
        return None, {"decision": "skip"}
    try:
        has_block = "<!-- UCCIF:BEGIN -->" in Path(path).read_text(encoding="utf-8")
    except OSError:
        has_block = False
    return None, {"rule": "claude-md-block", "target": "present" if has_block else "missing"}


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


def run(event, stdin=None, stdout=None):
    """Entry for `uccif hook <event>`. Always returns 0."""
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    t0 = time.time()
    fields, out, project = {}, None, None
    try:
        raw = stdin.read()
        data = json.loads(raw) if raw.strip() else {}
        handler = HANDLERS.get(event)
        if handler is None:
            raise ValueError("unknown hook event: %s" % event)
        project = resolve_project(data.get("cwd"))
        out, fields = handler(data, project)
        fields.setdefault("decision", "nudge" if out and event != "stop" else "allow")
        fields.update(session=data.get("session_id"), tool=data.get("tool_name"),
                      task=(task.load_current(project) or {}).get("id"))
        if data.get("agent_id") and "agent_id" not in fields:
            fields["agent_id"] = data.get("agent_id")
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
    if out:
        try:
            # ASCII-escaped JSON: valid for Claude Code whatever the stream encoding is
            stdout.write(json.dumps(out, ensure_ascii=True))
        except Exception:
            pass
    return 0
