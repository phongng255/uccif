import json
from datetime import datetime, timedelta

from uccif_lib import log


def test_redact_masks_secrets_and_truncates():
    assert "sk-abcdef" not in log.redact("curl -H token=sk-abcdef1234567890 x")
    assert "ghp_" not in log.redact("ghp_" + "a" * 30)
    assert "hunter2" not in log.redact("password=hunter2")
    assert len(log.redact("x" * 500)) == log.TARGET_MAX


def test_hook_log_one_line_per_call(project):
    log.hook(project, event="stop", decision="allow", target="sk-abcdefghijk123")
    log.hook(project, event="stop", decision="allow")
    rows = log.read(project, "hooks.jsonl")
    assert len(rows) == 2 and rows[0]["target"] == "***" and "ts" in rows[0]


def test_unclean_session_detection(project):
    log.session(project, session="a", type="start")
    log.session(project, session="a", type="end")
    assert log.last_session_unclosed(project) is None
    log.session(project, session="b", type="start")
    assert log.last_session_unclosed(project) == "b"


def test_prune_drops_old_lines(project):
    old = (datetime.now().astimezone() - timedelta(days=40)).isoformat()
    path = project.data_dir / "metrics" / "hooks.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"ts": old, "event": "x"}) + "\n")
    log.hook(project, event="y")
    assert log.prune(project) == 1
    assert [r["event"] for r in log.read(project, "hooks.jsonl")] == ["y"]


def test_viewers(project):
    log.hook(project, event="stop", decision="would_block", rule="agent-bash", ms=3)
    log.hook(project, event="stop", decision="allow", ms=3)
    assert len(log.show_hooks(project, only_blocks=True)) == 1
    assert log.show_hooks(project, only_errors=True) == ["(no hook log entries)"]
    log.session(project, session="abc", type="start")
    log.session(project, session="abc", type="compact")
    log.session(project, session="abc", type="end", reason="other", turns=3, tokens=10)
    lines = log.show_sessions(project)
    assert len(lines) == 2 and "other" in lines[1]
