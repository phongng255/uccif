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

from uccif_lib import codegraph, detect, drift, hosts, log, skillgen, task, usage
from uccif_lib.paths import CORE_MARKER, data_root, read_json, resolve_project, write_json
from uccif_lib.rules import core_rules, user_rules

SLOW_MS = {"session-start": 3000, "user-prompt-submit": 300, "pre-tool-use": 300,
           "post-tool-use": 500, "stop": 1000}
EDIT_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")
SEARCH_CMD = re.compile(r"(^|[\s|;&(])(grep|rg|ag|find|fd|ack)\s")
READ_CMD = re.compile(r"(^|[\s|;&(])(cat|sed|head|tail|less|more|bat|nl|awk)\s")
CODEGRAPH_CMD = re.compile(r"(^|[\s|;&(])(codegraph|npx\s+-y\s+@colbymchenry/codegraph)\s")
FRAMEWORK_DIRS = (".claude/", ".agents/", ".gemini/", ".codegraph/")
_WRAPPER = re.compile(r"<(system-reminder|bash-input|bash-stdout|bash-stderr)>.*?(</\1>|\Z)", re.S)
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
    env = lambda key: os.environ.get("CLAUDE_PLUGIN_OPTION_" + key) or os.environ.get("UCCIF_" + key)
    lang = env("REPLY_LANGUAGE") or cached.get("reply_language") or "vi"  # UCCIF_*: Gemini extension settings
    report = _bool(env("TOKEN_REPORT"), cached.get("token_report", True))
    setup = _bool(env("AUTO_SETUP"), cached.get("auto_setup", True))
    strict = _bool(env("STRICT_CODEGRAPH"), cached.get("strict_codegraph", False))
    return {"reply_language": lang, "token_report": report, "auto_setup": setup, "strict_codegraph": strict}


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
    """Run `uccif <args>` detached so a hook returns at once (drift check).
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

    hosts.record(project, data.get("_host") or "claude")
    task.migrate_from_data_dir(project)  # 3.0.0-dev.1..3 kept tasks in the plugin data dir
    prev = log.last_session_unclosed(project)
    if prev and prev != sid:
        log.session(project, session=prev, type="end", reason="unclean")
    try:
        task.close_stale(project)
    except task.TaskError:
        pass
    cur = task.load_current(project)
    log.session(project, session=sid, type="start", source=source,
                task=cur["id"] if cur and cur.get("status") != "done" else None)

    write_json(data_root() / CORE_MARKER, opts)
    env_file = os.environ.get("CLAUDE_ENV_FILE")
    if env_file:
        quoted = "'" + str(data_root()).replace("'", "'\\''") + "'"
        with open(env_file, "a", encoding="utf-8") as f:
            f.write("export UCCIF_DATA_DIR=%s\n" % quoted)

    host = data.get("_host") or "claude"
    parts, n_user = [], 0
    if source in ("startup", "clear", "compact"):
        # `uccif setup antigravity` puts the core rules in an always-on rule file: not twice
        if not (host == "antigravity" and (Path(project.root) / ".agents" / "rules" / "uccif.md").exists()):
            parts.append(core_rules(opts["reply_language"]))
        try:  # the user's own rules, right after the core (never fails the hook)
            extra = user_rules(project)
        except Exception:
            extra = ""
        if extra:
            parts.append(extra)
            n_user = extra.count("USER RULES (")
    spawn(["maintain"], project)  # drift check, CodeGraph index + project skills in the background
    parts.append(_codegraph_line(project, host))
    map_skill = _map_skill(project)
    if map_skill:  # the map skill is the code map; init is optional
        parts.append(_map_line(map_skill))
    _announce(project, sid, codegraph.level(project), map_skill)
    offer = lsp_offer(project)
    if offer:
        parts.append(offer)
    if (project.docs_dir / "summary.md").exists():
        parts.append("Project purpose, conventions, external services: .claude/uccif/summary.md.")
    lines = task.summary_lines(project)
    if lines:
        parts.append("\n".join(lines) + " (continue it if the request is related: uccif:resume)")
    if host != "claude":
        parts.extend(_other_host_lines(project, host))
    fields = {"rule": "context", "target": source}
    if n_user:
        fields["user_rules"] = n_user
    return _ctx("SessionStart", "\n\n".join(parts)), fields


def _codegraph_line(project, host):
    line = codegraph.context_line(project)
    return line if host == "claude" else line.replace("one Claude Code restart", "one restart")


def _map_skill(project):
    maps = [n for n in skillgen.generated(project) if n.endswith("-map")]
    return maps[0] if maps else None


def _map_line(map_skill):
    base = map_skill[:-4]
    return ("Code map: skill `%s` (modules, entry points, commands). Module skills: `%s-mod-*`; "
            "bug reports: `%s-bugfix`." % (map_skill, base, base))


# ---- what this session was told about CodeGraph -----------------------------------------
# SessionStart computes the CodeGraph line once. When the user installs and indexes CodeGraph in
# that same session, Claude would keep following the old line ("use Grep until .codegraph/
# exists"). So SessionStart remembers what it said, per session, and UserPromptSubmit tells Claude
# as soon as the level or the code map changes.

ANNOUNCED_KEEP = 20  # sessions remembered per project


def _announced_path(project):
    return Path(project.data_dir) / "announced.json"


def _announce(project, sid, level, map_skill):
    seen = read_json(_announced_path(project), {}) or {}
    seen.pop(str(sid), None)
    seen[str(sid)] = {"level": level, "map": map_skill or "", "ts": time.time()}
    keep = sorted(seen.items(), key=lambda kv: kv[1].get("ts", 0))[-ANNOUNCED_KEEP:]
    try:
        write_json(_announced_path(project), dict(keep))
    except OSError:
        pass


def _codegraph_news(data, project):
    """Lines for UserPromptSubmit when CodeGraph or the code map changed since Claude was told."""
    sid = str(data.get("session_id"))
    seen = (read_json(_announced_path(project), {}) or {}).get(sid)
    level, map_skill = codegraph.level(project), _map_skill(project)
    if seen is None:  # no SessionStart for this session (plugin enabled mid-session): just remember
        _announce(project, sid, level, map_skill)
        return []
    lines = []
    if level != seen.get("level"):
        lines.append("CodeGraph changed since this session started; this replaces the earlier note: " +
                     _codegraph_line(project, data.get("_host") or "claude"))
    if map_skill and map_skill != seen.get("map"):
        lines.append("New project skills: " + _map_line(map_skill) +
                     " Load the matching skill before reading code in a module.")
    if lines:
        _announce(project, sid, level, map_skill)
    return lines


UCCIF_BIN = Path(__file__).resolve().parent.parent / "bin" / "uccif"


def _other_host_lines(project, host):
    """What Claude Code gets from the plugin system and other hosts do not: the `uccif` command
    on PATH, and for Gemini CLI the project's AGENTS.md (it reads only GEMINI.md by default;
    Antigravity reads AGENTS.md itself). Only the UCCIF block is injected, never the rest of a
    user's AGENTS.md."""
    out = ['`uccif` is not on PATH here: run it as `"%s"` (same arguments).' % UCCIF_BIN.as_posix()]
    if host != "gemini":
        return out
    try:
        text = (Path(project.root) / "AGENTS.md").read_text(encoding="utf-8")
    except OSError:
        text = ""
    b, e = "<!-- UCCIF:BEGIN -->", "<!-- UCCIF:END -->"
    if b in text and e in text:
        out.append("Project notes (AGENTS.md):\n" + text[text.index(b) + len(b):text.index(e)].strip())
    return out


def _prompt_path(project):
    return Path(project.data_dir) / "last_prompt.txt"


def _edited_path(project):
    return Path(project.data_dir) / "prompt_edited.flag"


def _title_text(prompt):
    """The user's own words: without the blocks the host adds, closed or cut off."""
    return _WRAPPER.sub("", prompt).strip()


def _same_turn(data, project):
    """Antigravity's PreInvocation runs before every model call and has no prompt text. A turn is
    one (conversationId, initialNumSteps): only its first call counts as the prompt."""
    key = "%s:%s" % (data.get("conversationId"), data.get("initialNumSteps"))
    f = Path(project.data_dir) / "last_turn.txt"
    try:
        if f.read_text(encoding="utf-8") == key:
            return True
    except OSError:
        pass
    try:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(key, encoding="utf-8")
    except OSError:
        pass
    return False


def on_user_prompt_submit(data, project):
    """Injects only news: an open task kept across turns, or stale docs. Nothing new -> nothing."""
    if data.get("_host") == "antigravity" and _same_turn(data, project):
        return None, {"decision": "skip", "rule": "same-turn"}
    raw_prompt = data.get("prompt") or ""
    prompt = _title_text(raw_prompt)
    if raw_prompt and not prompt:  # a shell command the user typed: not a new request
        return None, {"decision": "skip", "rule": "shell-only"}
    _set_quick(project, "#quick" in prompt)
    try:  # the title of the implicit task the first edit opens
        _prompt_path(project).parent.mkdir(parents=True, exist_ok=True)
        _prompt_path(project).write_text(prompt[:400], encoding="utf-8")
    except OSError:
        pass
    for f in (_edited_path(project), _looked_up_path(project), _denied_path(project)):
        try:  # a new prompt: no edit, no CodeGraph lookup, no strict refusal yet
            f.unlink()
        except OSError:
            pass
    _snapshot_git(project)
    news = _codegraph_news(data, project)
    lines = list(news)  # the open task is in SessionStart's context already
    stale = drift.pending(project)
    if stale:
        lines.append("Project notes are stale: " + "; ".join(stale) +
                     ". Update only those lines when convenient, then run `uccif drift ack`.")
    if not lines:
        return None, {"decision": "skip"}
    return _ctx("UserPromptSubmit", "\n".join(lines)), {"rule": "news", "drift": len(stale) or None,
                                                       "codegraph": len(news) or None}


NUDGE_EVERY = 600  # seconds between two search nudges


def _quick_path(project):
    return Path(project.data_dir) / "quick.flag"


def _set_quick(project, quick):
    try:
        if quick:
            _quick_path(project).parent.mkdir(parents=True, exist_ok=True)
            _quick_path(project).write_text("1", encoding="utf-8")
        else:
            _quick_path(project).unlink()
    except OSError:
        pass


def _is_quick(project):
    return _quick_path(project).exists()


def _nudge_due(project, name):
    """True at most once per NUDGE_EVERY seconds for the marker `name`."""
    f = Path(project.data_dir) / name
    try:
        if time.time() - f.stat().st_mtime < NUDGE_EVERY:
            return False
    except OSError:
        pass
    try:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("1", encoding="utf-8")
    except OSError:
        pass
    return True


def _looked_up_path(project):
    return Path(project.data_dir) / "turn_lookup.flag"


def _denied_path(project):
    return Path(project.data_dir) / "turn_denied.flag"


def _touch(path):
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("1", encoding="utf-8")
    except OSError:
        pass


def _is_source(path):
    return Path(str(path)).suffix.lower() in detect.LANG_EXT


def _classify(tool, ti):
    """What a main-agent tool call does to find code: "lookup" (CodeGraph), "read" (source file),
    "search" (Grep/Glob or a search command), or None."""
    cmd = ti.get("command") or ""
    if (tool or "").startswith("mcp__") and "codegraph" in tool.lower():
        return "lookup"
    if tool == "Bash" and CODEGRAPH_CMD.search(" " + cmd):
        return "lookup"
    if tool == "Read":
        return "read" if _is_source(ti.get("file_path") or "") else None
    if tool in ("Grep", "Glob"):
        return "search"
    if tool == "Bash":
        if SEARCH_CMD.search(" " + cmd):
            return "search"
        if READ_CMD.search(" " + cmd) and any(_is_source(w.strip("'\"")) for w in cmd.split()):
            return "read"
    return None


def _lookup_hint(project):
    # smallest first: `explore` returns source from many files and costs far more than one `node`
    flow = ("MCP `codegraph_explore`" if codegraph.level(project) == "active"
            else "Bash `codegraph explore --max-files 3 \"<question>\"`")
    how = ("Bash `codegraph node <symbol>` (a file: `codegraph node -f <path> --symbols-only`); "
           "%s only for a flow with no symbol to name" % flow)
    map_skill = _map_skill(project)
    skill = (", or load skill `%s-mod-*` for that module" % map_skill[:-4]) if map_skill else ""
    return how + skill


def _main_agent_nudge(data, project):
    """Main agent: record CodeGraph lookups; before reading or searching code without one, remind
    (default) or, with the opt-in `strict_codegraph` option, refuse the first such call of the turn."""
    tool = data.get("tool_name")
    kind = _classify(tool, data.get("tool_input") or {})
    if kind == "lookup":
        _touch(_looked_up_path(project))
        return None, {"decision": "allow", "rule": "codegraph-lookup", "target": tool}
    if kind is None or not codegraph.usable(project) or _looked_up_path(project).exists():
        return None, {"decision": "skip"}
    strict = (options()["strict_codegraph"] and (data.get("_host") or "claude") == "claude"
              and kind in ("read", "search") and tool != "Glob")
    if strict and not _denied_path(project).exists():
        _touch(_denied_path(project))  # once per turn: a retry goes through
        reason = ("UCCIF strict mode: look this up with CodeGraph first (%s). It returns the source, so "
                  "you may not need this call at all. For a literal or config value, retry the same call: "
                  "it is allowed." % _lookup_hint(project))
        return ({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                        "permissionDecisionReason": reason}},
                {"decision": "deny", "rule": "strict-codegraph", "target": tool})
    if _nudge_due(project, "search.nudge"):
        msg = ("UCCIF: this %s source code without a CodeGraph lookup this turn. Look it up first (%s); "
               "Read/Grep only what it did not return, or literals and config, scoped to a module dir."
               % ("reads" if kind == "read" else "searches", _lookup_hint(project)))
        return _ctx("PreToolUse", msg), {"rule": "search-codegraph-first", "target": tool, "kind": kind}
    return None, {"decision": "skip"}


def on_pre_tool_use(data, project):
    agent = (data.get("agent_type") or "").split(":")[-1]
    if not data.get("agent_id"):
        return _main_agent_nudge(data, project)
    if agent not in AGENT_BASH:
        return None, {"decision": "skip"}
    cmd = ((data.get("tool_input") or {}).get("command") or "").strip()
    if any(re.match(p, cmd) for p in AGENT_BASH[agent]):
        return None, {"decision": "allow", "rule": "agent-bash", "target": cmd}
    return None, {"decision": "would_block", "rule": "agent-bash", "target": cmd, "agent": agent}


def on_post_tool_use(data, project):
    ti = data.get("tool_input") or {}
    path = ti.get("file_path") or ti.get("notebook_path")
    rel = _rel(project, path) if path else None
    if not rel or rel.startswith((".claude/", ".agents/", ".gemini/")):
        return None, {"decision": "skip", "target": path}
    opened = closed = None
    if not _is_quick(project) and not _edited_path(project).exists():
        try:
            prompt = _prompt_path(project).read_text(encoding="utf-8")
        except OSError:
            prompt = ""
        try:
            opened, closed = task.on_first_edit(project, prompt)
            _edited_path(project).parent.mkdir(parents=True, exist_ok=True)
            _edited_path(project).write_text("1", encoding="utf-8")
        except (task.TaskError, OSError):
            pass
    added = task.add_modified(project, rel)
    fields = {"rule": "task-files" if added else "no-task", "target": rel}
    if opened:
        fields["opened"] = opened["id"]
    if closed:
        fields["closed"] = closed["id"]
    return None, fields


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


# ---- files changed outside Edit/Write --------------------------------------------------
# PostToolUse only sees Edit/Write. Claude also edits with Bash (sed -i, a Python script, a code
# generator), so UserPromptSubmit records the dirty files (path -> mtime) and HEAD, and Stop adds
# every file that changed in between to the task, opening one as a first edit would.

GIT_TIMEOUT = 2
GIT_MAX_FILES = 5000


def _git_state(root):
    """({path: mtime_ns or -1}, head) of the work tree, or None outside git or on any error."""
    try:
        st = subprocess.run(["git", "-C", str(root), "status", "--porcelain=v1", "-z", "--untracked-files=all"],
                            capture_output=True, timeout=GIT_TIMEOUT)
        head = subprocess.run(["git", "-C", str(root), "rev-parse", "-q", "--verify", "HEAD"],
                              capture_output=True, timeout=GIT_TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return None
    if st.returncode:
        return None
    toks = st.stdout.decode("utf-8", "replace").split("\0")
    files, i = {}, 0
    while i < len(toks) and len(files) < GIT_MAX_FILES:
        tok = toks[i]
        i += 1
        if len(tok) < 4:
            continue
        if tok[0] in "RC":  # a rename or copy: the original path follows
            i += 1
        path = tok[3:]
        try:
            files[path] = os.stat(os.path.join(str(root), path)).st_mtime_ns
        except OSError:
            files[path] = -1
    return files, head.stdout.decode().strip() if head.returncode == 0 else ""


def _git_snapshot_path(project):
    return Path(project.data_dir) / "turn_git.json"


def _snapshot_git(project):
    state = _git_state(project.root)
    try:
        if state is None:
            _git_snapshot_path(project).unlink()
        else:
            write_json(_git_snapshot_path(project), {"files": state[0], "head": state[1]})
    except OSError:
        pass


def _git_committed(root, old, new):
    try:
        r = subprocess.run(["git", "-C", str(root), "diff", "--name-only", old, new],
                           capture_output=True, timeout=GIT_TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return []
    return r.stdout.decode("utf-8", "replace").splitlines() if r.returncode == 0 else []


def _track_git_changes(project):
    """Files changed this turn by any means; adds them to the task. Returns how many were added."""
    snap = read_json(_git_snapshot_path(project), None)
    if not isinstance(snap, dict) or _is_quick(project):
        return 0
    state = _git_state(project.root)
    if state is None:
        return 0
    files, head = state
    before = snap.get("files") or {}
    changed = {p for p, m in files.items() if before.get(p) != m}
    if snap.get("head") and head and snap["head"] != head:  # Claude committed during the turn
        changed.update(_git_committed(project.root, snap["head"], head))
    changed = sorted(p for p in changed if p and not p.startswith(FRAMEWORK_DIRS))
    write_json(_git_snapshot_path(project), {"files": files, "head": head})
    if not changed:
        return 0
    if not _edited_path(project).exists():
        try:
            prompt = _prompt_path(project).read_text(encoding="utf-8")
        except OSError:
            prompt = ""
        try:
            task.on_first_edit(project, prompt)
            _touch(_edited_path(project))
        except task.TaskError:
            return 0
    return sum(1 for p in changed if task.add_modified(project, p))


def on_stop(data, project):
    if data.get("stop_hook_active"):
        return None, {"decision": "skip", "rule": "rerun"}
    git_files = _track_git_changes(project)
    # structural changes made by Bash, by the user, or by git pull/checkout this turn
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
    if not s and data.get("_host", "claude") != "claude":
        return None, {"rule": "token-n/a"}  # transcript format not read for this host yet
    line = "🔢 " + usage.token_line(s)
    if s:
        total = s["session"]["in"] + s["session"]["output_tokens"]
        if not open_task and cur and s["ctx"] >= cfg["clear_hint_tokens"]:
            line += "\n   💡 /clear recommended (task saved)"
        elif open_task and s["ctx"] >= cfg["checkpoint_tokens"]:
            line += "\n   💡 checkpoint, then /clear"
        elif total >= cfg["long_session_tokens"]:
            line += "\n   💡 long session"
    return {"systemMessage": line}, {"rule": "token-line", "git_files": git_files or None}


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
    if data.get("memory_type") != "Project" or _rel(project, path) not in ("CLAUDE.md", "AGENTS.md"):
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


def run(event, stdin=None, stdout=None, host="claude"):
    """Entry for `uccif hook [--host H] <event>`. Always returns 0. `event` is the host's own
    name (BeforeTool) or the internal one (pre-tool-use); hosts.py translates both ways."""
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    t0 = time.time()
    fields, out, project = {}, None, None
    try:
        raw = stdin.read()
        data = json.loads(raw) if raw.strip() else {}
        hosts.check(host)
        event, data = hosts.normalize(host, event, data)
        data["_host"] = host
        handler = HANDLERS.get(event)
        if handler is None:
            raise ValueError("unknown hook event: %s" % event)
        project = resolve_project(data.get("cwd"))
        out, fields = handler(data, project)
        out = hosts.format_output(host, event, out)
        fields.setdefault("decision", "nudge" if out and event != "stop" else "allow")
        fields.update(session=data.get("session_id"), tool=data.get("tool_name"),
                      task=(task.load_current(project) or {}).get("id"))
        if data.get("agent_id") and "agent_id" not in fields:
            fields["agent_id"] = data.get("agent_id")
    except Exception as e:  # never break the session
        fields = {"decision": "error", "error": "%s: %s" % (type(e).__name__, str(e)[:200])}
        out = None
        event = hosts.event_name(host, event) if host in hosts.HOSTS else event
    ms = int((time.time() - t0) * 1000)
    fields.update(event=event, ms=ms)
    if host != "claude":
        fields["host"] = host
    if ms > SLOW_MS.get(event, 1000):
        fields["slow"] = True
    quiet = ((event == "pre-tool-use" and fields.get("decision") == "skip") or
             fields.get("rule") == "same-turn") and not fields.get("slow")
    try:
        if project is None:
            project = resolve_project()
        if not quiet:
            log.hook(project, **fields)
    except Exception:
        pass
    if out is None and host in hosts.HOSTS:
        out = hosts.default_output(host, event)
    if out is not None:
        try:
            # ASCII-escaped JSON: valid for Claude Code whatever the stream encoding is
            stdout.write(json.dumps(out, ensure_ascii=True))
        except Exception:
            pass
    return 0
