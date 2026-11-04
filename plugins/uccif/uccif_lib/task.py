"""Current-task memory: start / show / checkpoint / close.

Canonical state is tasks/current.json in <project>/.claude/uccif/.local/ (git-ignored;
inside the working dir so `uccif task …` works in Claude Code's Bash sandbox, which
denies writes under ~/.claude); current-task.md is rendered from it. Decisions and issues are also
appended to the committed docs in <project>/.claude/uccif/.
"""

import functools
import json
from datetime import date

import shutil

from uccif_lib.paths import (LockTimeout, ensure_local, file_lock, now_iso, read_json, write_json,
                             write_text_atomic)

TYPES = ("bug", "feature", "refactor", "review", "test", "explore", "ui")
LIST_FIELDS = ("files", "decisions", "tests", "issues")
SCALAR_FIELDS = ("goal", "modules", "next")
HISTORY_KEEP = 20
LOCK_TIMEOUT = 3.0  # seconds a CLI call waits for another session's write


class TaskError(Exception):
    pass


def _paths(project):
    tdir = project.local_dir / "tasks"
    return {
        "dir": tdir,
        "lock": tdir / ".lock",
        "state": tdir / "state.json",
        "current": tdir / "current.json",
        "md": project.local_dir / "current-task.md",
        "history": tdir / "history",
    }


def migrate_from_data_dir(project):
    """Move task state written by 3.0.0-dev.1..3 (plugin data dir) into .local/ once."""
    old = project.data_dir / "tasks"
    if not old.is_dir() or _paths(project)["dir"].exists():
        return False
    ensure_local(project)
    shutil.copytree(str(old), str(_paths(project)["dir"]))
    md = project.data_dir / "current-task.md"
    if md.exists():
        shutil.copy2(str(md), str(_paths(project)["md"]))
    shutil.rmtree(str(old), ignore_errors=True)
    return True


def load_current(project):
    return read_json(_paths(project)["current"])


def render(task):
    def items(key):
        vals = task.get(key) or []
        return "".join("\n- %s" % v for v in vals)

    lines = [
        "Task: %s — %s" % (task["id"], task["title"]),
        "Type: %s    Status: %s%s"
        % (task["type"], task["status"], "    (rewrite allowed)" if task.get("rewrite") else ""),
        "Goal: %s" % task.get("goal", ""),
        "Related modules: %s" % task.get("modules", ""),
        "Files modified:%s" % items("files"),
        "Key decisions:%s" % items("decisions"),
        "Tests run / results:%s" % items("tests"),
        "Open issues:%s" % items("issues"),
        "Next step: %s" % task.get("next", ""),
        "Last updated: %s" % task.get("updated", ""),
    ]
    return "\n".join(lines) + "\n"


def _locked(fn):
    """Serialize task-state changes across sessions on the same project."""
    @functools.wraps(fn)
    def wrapper(project, *args, **kwargs):
        ensure_local(project)
        try:
            with file_lock(_paths(project)["lock"], timeout=LOCK_TIMEOUT):
                return fn(project, *args, **kwargs)
        except LockTimeout:
            raise TaskError("Task state is busy (another Claude session on this project is "
                            "writing it). Retry in a moment.")
    return wrapper


def _save(project, task):
    p = _paths(project)
    task["updated"] = now_iso()
    write_json(p["current"], task)
    write_text_atomic(p["md"], render(task))


def _append_doc(project, filename, title, task_id, text):
    path = project.docs_dir / filename
    head = "" if path.exists() else "# %s\n\n" % title
    line = "- %s [%s] %s\n" % (date.today().isoformat(), task_id, text)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(str(path), "a", encoding="utf-8") as f:
        f.write(head + line)


def _record_findings(project, task, decisions, issues):
    for d in decisions or []:
        task.setdefault("decisions", []).append(d)
        _append_doc(project, "decisions.md", "Decisions", task["id"], d)
    for i in issues or []:
        task.setdefault("issues", []).append(i)
        _append_doc(project, "known-issues.md", "Known issues", task["id"], i)


@_locked
def start(project, title, ttype, goal="", rewrite=False):
    if ttype not in TYPES:
        raise TaskError("type must be one of: %s" % ", ".join(TYPES))
    cur = load_current(project)
    if cur and cur.get("status") != "done":
        raise TaskError(
            "Task %s is still open (%s). Close it first: uccif task close --no-findings|--decision ...|--issue ..."
            % (cur["id"], cur["title"])
        )
    p = _paths(project)
    state = read_json(p["state"], {"next_id": 1})
    tid = "T-%03d" % state["next_id"]
    state["next_id"] += 1
    write_json(p["state"], state)
    task = {
        "id": tid, "title": title, "type": ttype, "status": "in_progress",
        "goal": goal, "modules": "", "next": "", "rewrite": bool(rewrite),
        "files": [], "decisions": [], "tests": [], "issues": [],
        "started": now_iso(),
    }
    _save(project, task)
    return task


def _require_open(project):
    task = load_current(project)
    if not task or task.get("status") == "done":
        raise TaskError("No open task. Start one: uccif task start \"<title>\" --type <type>")
    return task


@_locked
def checkpoint(project, decisions=None, issues=None, tests=None, files=None,
               sets=None, **scalars):
    task = _require_open(project)
    for raw in sets or []:
        key, _, val = raw.partition("=")
        key = key.strip().lower()
        if key == "status":
            raise TaskError("Status cannot be set by checkpoint; use `uccif task close`.")
        if key not in SCALAR_FIELDS:
            raise TaskError("--set accepts: %s" % ", ".join(SCALAR_FIELDS))
        scalars[key] = val.strip()
    for key in SCALAR_FIELDS:
        if scalars.get(key):
            task[key] = scalars[key]
    for t in tests or []:
        task["tests"].append(t)
    for f in files or []:
        if f not in task["files"]:
            task["files"].append(f)
    _record_findings(project, task, decisions, issues)
    _save(project, task)
    return task


def add_modified(project, path):
    """Called by hooks after Edit/Write; silent no-op without an open task or
    when another session holds the lock (hooks must never fail or wait long)."""
    try:
        return _add_modified(project, path)
    except TaskError:
        return False


@_locked
def _add_modified(project, path):
    task = load_current(project)
    if not task or task.get("status") == "done":
        return False
    task["last_edit"] = now_iso()
    added = path not in task["files"]
    if added:
        task["files"].append(path)
    _save(project, task)
    return added


@_locked
def close(project, decisions=None, issues=None, no_findings=False):
    task = _require_open(project)
    if not (decisions or issues or no_findings):
        raise TaskError("close needs --decision, --issue or --no-findings.")
    _record_findings(project, task, decisions, issues)
    task["status"] = "done"
    task["closed"] = now_iso()
    _save(project, task)
    snapshot(project, label=task["id"])
    return task


def guess_type(prompt):
    import re
    p = (prompt or "").lower()
    for ttype, pat in (("bug", r"fix|bug|error|crash|broken|fail|lỗi|sửa"), ("refactor", r"refactor|rename|clean"),
                       ("test", r"\btests?\b|kiểm thử"), ("ui", r"\bui\b|css|style|giao diện")):
        if re.search(pat, p):
            return ttype
    return "feature"


def auto_title(prompt):
    line = " ".join((prompt or "").split())
    return (line[:77] + "...") if len(line) > 80 else (line or "Code change")


# Matching runs on lowercased, accent-free words ("sửa lỗi" == "sua loi"). Action verbs and fillers
# are not topic words; continuation words mean "the same work".
STOP_WORDS = set("""
the and for with this that from into then also please can you make add use not but are was
fix fixed change update new now let lets code file files bug error issue work
mot nhung cac cho cua va voi nay khi thi duoc khong co lam hay can nhu vao trong de la o
sua them xem thu giup minh toi ban nhe di roi chut cai kia bi loi phan
""".split())
CONTINUE_WORDS = {"luon", "tiep", "nua", "vay", "do", "van", "lai", "con", "cung", "again", "still",
                  "too", "also", "same", "continue", "it", "that", "those"}  # not "them": accent-free "thêm"
SWITCH_WORDS = {"gio", "now", "next", "instead"}
STALE_HOURS = 24


def _words(text):
    import re
    import unicodedata
    text = unicodedata.normalize("NFD", (text or "").lower().replace("đ", "d"))
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return re.findall(r"[a-z0-9_]+", text)


def topic_words(text):
    return {w for w in _words(text) if len(w) >= 2 and not w.isdigit()
            and w not in STOP_WORDS and w not in CONTINUE_WORDS and w not in SWITCH_WORDS}


def is_new_topic(prompt, task):
    """True only when the prompt clearly starts other work than `task`. Doubt -> same task: closing
    a task by mistake costs more than keeping one open too long.
    - any continuation word ("luôn", "tiếp", "nữa", "đó", "vậy", "also") -> same task
      ("tiếp theo" = next item, a switch);
    - >= 3 topic words, under 20% of them seen in the task's title / earlier prompts -> new;
    - a switch word ("giờ", "now", "next") and >= 2 topic words, none seen -> new."""
    words = _words(prompt)
    text = " ".join(words)
    switch = bool(SWITCH_WORDS & set(words)) or "tiep theo" in text
    if not switch and CONTINUE_WORDS & set(words):
        return False
    content = topic_words(prompt)
    seen = set(task.get("topic") or []) | topic_words(task.get("title"))
    hit = len(content & seen) / float(len(content)) if content else 1.0
    if len(content) >= 3 and hit < 0.2:
        return True
    return switch and len(content) >= 2 and hit == 0


def _new_auto(project, prompt):
    p = _paths(project)
    state = read_json(p["state"], {"next_id": 1})
    tid = "T-%03d" % state["next_id"]
    state["next_id"] += 1
    write_json(p["state"], state)
    task = {"id": tid, "title": auto_title(prompt), "type": guess_type(prompt), "status": "in_progress",
            "goal": "", "modules": "", "next": "", "rewrite": False, "auto": True,
            "topic": sorted(topic_words(prompt))[:40],
            "files": [], "decisions": [], "tests": [], "issues": [], "started": now_iso()}
    _save(project, task)
    return task


def _close_quietly(project, task, reason):
    task["status"] = "done"
    task["closed"] = now_iso()
    task["closed_by"] = reason
    _save(project, task)
    snapshot(project, label=task["id"])


@_locked
def on_first_edit(project, prompt):
    """PostToolUse, first edit of a prompt. No open task -> open one. Open task and the prompt is
    clearly other work -> close it without findings and open a new one. Otherwise the prompt joins
    the open task's topic. Returns (opened, closed) tasks or None."""
    cur = load_current(project)
    if cur and cur.get("status") != "done":
        if not is_new_topic(prompt, cur):
            cur["topic"] = sorted(set(cur.get("topic") or []) | topic_words(prompt))[:80]
            _save(project, cur)
            return None, None
        _close_quietly(project, cur, "new-topic")
        return _new_auto(project, prompt), cur
    return _new_auto(project, prompt), None


def _age_hours(task):
    from datetime import datetime
    try:
        then = datetime.fromisoformat(task.get("last_edit") or task.get("started"))
        return (datetime.now(then.tzinfo) - then).total_seconds() / 3600.0
    except (TypeError, ValueError):
        return 0.0


@_locked
def close_stale(project, hours=STALE_HOURS):
    """SessionStart: close an open task with no edit for `hours`."""
    cur = load_current(project)
    if not cur or cur.get("status") == "done" or _age_hours(cur) < hours:
        return None
    _close_quietly(project, cur, "stale")
    return cur


def snapshot(project, label=None):
    """Copy current-task.md into history/ and keep the newest HISTORY_KEEP files."""
    p = _paths(project)
    if not p["md"].exists():
        return None
    p["history"].mkdir(parents=True, exist_ok=True)
    stamp = now_iso().replace(":", "").replace("+", "p")
    dest = p["history"] / ("%s_%s.md" % (stamp, label or "snapshot"))
    dest.write_text(p["md"].read_text(encoding="utf-8"), encoding="utf-8")
    files = sorted(p["history"].glob("*.md"))
    for old in files[:-HISTORY_KEEP]:
        old.unlink()
    return dest


def summary_lines(project, limit=2):
    task = load_current(project)
    if not task or task.get("status") == "done":
        return []
    n = len(task.get("files") or [])
    lines = ["Open task: %s (%d file%s) [%s]" % (task["title"], n, "" if n == 1 else "s", task["id"])]
    if task.get("next"):
        lines.append("Next step: %s" % task["next"])
    return lines[:limit]


def to_json(task):
    return json.dumps(task, ensure_ascii=False, indent=2)
