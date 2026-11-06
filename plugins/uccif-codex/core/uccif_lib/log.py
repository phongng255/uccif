"""JSONL logs in <project data>/metrics/: hooks.jsonl, sessions.jsonl, usage.jsonl.

Logs are written to files only, never printed into Claude's context. Targets
are truncated and secret-looking strings are masked.
"""

import json
import re
from datetime import datetime, timedelta

from uccif_lib.paths import now_iso

TARGET_MAX = 120
PRUNE_DAYS = 30
_SECRET = re.compile(
    r"(sk-[A-Za-z0-9_\-]{8,}|gh[pousr]_[A-Za-z0-9]{16,}|xox[abpr]-[A-Za-z0-9\-]{10,}"
    r"|AKIA[0-9A-Z]{16}|eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]+"
    r"|(?i:(?:password|passwd|secret|token|api[_-]?key)\s*[=:]\s*)\S+)"
)


def redact(text):
    if text is None:
        return None
    text = _SECRET.sub("***", str(text))
    return text if len(text) <= TARGET_MAX else text[: TARGET_MAX - 1] + "…"


def _metrics(project):
    d = project.data_dir / "metrics"
    d.mkdir(parents=True, exist_ok=True)
    return d


def append(project, name, record):
    record = dict(record)
    record.setdefault("ts", now_iso())
    with open(str(_metrics(project) / name), "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def hook(project, **fields):
    if "target" in fields:
        fields["target"] = redact(fields["target"])
    append(project, "hooks.jsonl", fields)


def session(project, **fields):
    append(project, "sessions.jsonl", fields)


def usage(project, **fields):
    append(project, "usage.jsonl", fields)


def read(project, name):
    path = project.data_dir / "metrics" / name
    out = []
    try:
        with open(str(path), encoding="utf-8") as f:
            for line in f:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    pass
    except OSError:
        pass
    return out


def _parse_ts(ts):
    try:
        return datetime.fromisoformat(ts)
    except (TypeError, ValueError):
        return None


def prune(project, days=PRUNE_DAYS):
    cutoff = datetime.now().astimezone() - timedelta(days=days)
    removed = 0
    for path in (project.data_dir / "metrics").glob("*.jsonl"):
        keep = []
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                ts = _parse_ts(json.loads(line).get("ts"))
            except ValueError:
                continue
            if ts is None or ts >= cutoff:
                keep.append(line)
            else:
                removed += 1
        path.write_text("".join(l + "\n" for l in keep), encoding="utf-8")
    return removed


def last_session_unclosed(project):
    """Session id of the latest `start` that has no matching `end`, if any."""
    started, ended = [], set()
    for r in read(project, "sessions.jsonl"):
        if r.get("type") == "start":
            started.append(r.get("session"))
        elif r.get("type") == "end":
            ended.add(r.get("session"))
    if not started or started[-1] in ended:
        return None
    return started[-1]


# ---- viewers (≤ 40 lines by default) ---------------------------------------

def _hhmm(ts):
    t = _parse_ts(ts)
    return t.strftime("%H:%M:%S") if t else "--:--:--"


def show_hooks(project, last=40, today=False, only_blocks=False, only_errors=False, event=None):
    rows = read(project, "hooks.jsonl")
    if today:
        d = datetime.now().astimezone().date()
        rows = [r for r in rows if (_parse_ts(r.get("ts")) or datetime.min).date() == d]
    if event:
        rows = [r for r in rows if r.get("event") == event]
    if only_blocks:
        rows = [r for r in rows if r.get("decision") in ("block", "would_block")]
    if only_errors:
        rows = [r for r in rows if r.get("decision") == "error" or r.get("error")]
    lines = []
    for r in rows[-last:]:
        lines.append("%s  %-18s %-6s %-11s %-14s %5sms%s%s" % (
            _hhmm(r.get("ts")), r.get("event", "?"), r.get("tool") or "-",
            r.get("decision", "?"), r.get("rule") or "-", r.get("ms", "?"),
            "  slow" if r.get("slow") else "",
            ('  "%s"' % r["target"]) if r.get("target") else "",
        ))
    return lines or ["(no hook log entries)"]


def show_sessions(project, days=1):
    cutoff = datetime.now().astimezone() - timedelta(days=days)
    sessions = {}
    for r in read(project, "sessions.jsonl"):
        sid = r.get("session")
        s = sessions.setdefault(sid, {"compacts": 0})
        if r.get("type") == "start" and "start" not in s:
            s["start"] = r.get("ts")
        elif r.get("type") == "compact":
            s["compacts"] += 1
        elif r.get("type") == "end":
            s.update(end=r.get("ts"), reason=r.get("reason"), tokens=r.get("tokens"),
                     turns=r.get("turns"), task=r.get("task"))
    lines = ["SESSION   START     END       COMPACT  TURNS  TOKENS    TASK    END"]
    for sid, s in sessions.items():
        st = _parse_ts(s.get("start"))
        if not st or st < cutoff:
            continue
        lines.append("%-9s %-9s %-9s %-8s %-6s %-9s %-7s %s" % (
            (sid or "?")[:8], _hhmm(s.get("start"))[:5],
            _hhmm(s["end"])[:5] if s.get("end") else "…", s["compacts"],
            s.get("turns") or "-", s.get("tokens") or "-", s.get("task") or "-",
            s.get("reason") or "running",
        ))
    return lines
