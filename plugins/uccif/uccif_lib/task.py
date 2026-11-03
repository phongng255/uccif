"""Current-task memory: start / show / checkpoint / close.

Canonical state is tasks/current.json in the project data dir; current-task.md
is rendered from it for Claude and humans. Decisions and issues are also
appended to the committed docs in <project>/.claude/uccif/.
"""

import functools
import json
from datetime import date

from uccif_lib.paths import LockTimeout, file_lock, now_iso, read_json, write_json, write_text_atomic

TYPES = ("bug", "feature", "refactor", "review", "test", "explore", "ui")
LIST_FIELDS = ("files", "decisions", "tests", "issues")
SCALAR_FIELDS = ("goal", "modules", "next")
HISTORY_KEEP = 20
LOCK_TIMEOUT = 3.0  # seconds a CLI call waits for another session's write


class TaskError(Exception):
    pass


def _paths(project):
    tdir = project.data_dir / "tasks"
    return {
        "dir": tdir,
        "lock": tdir / ".lock",
        "state": tdir / "state.json",
        "current": tdir / "current.json",
        "md": project.data_dir / "current-task.md",
        "history": tdir / "history",
    }


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
    if not task or task.get("status") == "done" or path in task["files"]:
        return False
    task["files"].append(path)
    _save(project, task)
    return True


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
    lines = ["Open task %s (%s): %s" % (task["id"], task["type"], task["title"])]
    if task.get("next"):
        lines.append("Next step: %s" % task["next"])
    return lines[:limit]


def to_json(task):
    return json.dumps(task, ensure_ascii=False, indent=2)
