import pytest

from uccif_lib import task
from uccif_lib.task import TaskError


def test_start_show_checkpoint_close(project):
    t = task.start(project, "Fix login", "bug", goal="login works")
    assert t["id"] == "T-001"
    task.checkpoint(project, next="write repro", tests=["npm test: fail"], decisions=["use cookie"])
    md = (project.local_dir / "current-task.md").read_text()
    assert "Task: T-001 — Fix login" in md
    assert "- use cookie" in md and "Next step: write repro" in md
    task.close(project, issues=["safari drops cookie"])
    assert task.load_current(project)["status"] == "done"
    assert "[T-001] use cookie" in (project.docs_dir / "decisions.md").read_text()
    assert "[T-001] safari drops cookie" in (project.docs_dir / "known-issues.md").read_text()
    assert len(list((project.local_dir / "tasks" / "history").glob("*T-001.md"))) == 1


def test_ids_increment(project):
    task.start(project, "a", "ui")
    task.close(project, no_findings=True)
    assert task.start(project, "b", "ui")["id"] == "T-002"


def test_cannot_start_while_open(project):
    task.start(project, "a", "ui")
    with pytest.raises(TaskError, match="still open"):
        task.start(project, "b", "ui")


def test_close_requires_findings_flag(project):
    task.start(project, "a", "ui")
    with pytest.raises(TaskError):
        task.close(project)


def test_status_cannot_be_set_by_checkpoint(project):
    task.start(project, "a", "ui")
    with pytest.raises(TaskError, match="task close"):
        task.checkpoint(project, sets=["Status=done"])
    task.checkpoint(project, sets=["next=do it"])
    assert task.load_current(project)["next"] == "do it"


def test_bad_type_and_no_open_task(project):
    with pytest.raises(TaskError):
        task.start(project, "a", "nope")
    with pytest.raises(TaskError, match="No open task"):
        task.checkpoint(project, next="x")


def test_add_modified_dedupes_and_ignores_without_task(project):
    assert task.add_modified(project, "src/a.ts") is False
    task.start(project, "a", "ui")
    assert task.add_modified(project, "src/a.ts") is True
    assert task.add_modified(project, "src/a.ts") is False
    assert task.load_current(project)["files"] == ["src/a.ts"]


def test_history_keeps_last_20(project):
    task.start(project, "a", "ui")
    for i in range(25):
        task.snapshot(project, label="s%02d" % i)
    assert len(list((project.local_dir / "tasks" / "history").glob("*.md"))) == task.HISTORY_KEEP


def test_summary_lines(project):
    assert task.summary_lines(project) == []
    task.start(project, "Fix login", "bug")
    task.checkpoint(project, next="repro")
    assert task.summary_lines(project) == ["Open task T-001 (bug): Fix login", "Next step: repro"]


def test_concurrent_starts_get_distinct_ids(project):
    import threading
    from uccif_lib import paths as P
    ids, errors = [], []

    def worker(i):
        try:
            t = task.start(project, "t%d" % i, "ui")
            ids.append(t["id"])
            task.close(project, no_findings=True)
        except task.TaskError as e:
            errors.append(str(e))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(ids) == len(set(ids))  # never two tasks with one id
    state = P.read_json(project.local_dir / "tasks" / "state.json")
    assert state["next_id"] == len(ids) + 1


def test_busy_lock_gives_clear_error_and_hook_stays_silent(project, monkeypatch):
    from uccif_lib import paths as P
    monkeypatch.setattr(task, "LOCK_TIMEOUT", 0.2)
    task.start(project, "a", "ui")
    lock = project.local_dir / "tasks" / ".lock"
    with P.file_lock(lock):
        with pytest.raises(task.TaskError, match="busy"):
            task.checkpoint(project, next="x")
        assert task.add_modified(project, "src/a.ts") is False
    assert task.add_modified(project, "src/a.ts") is True
    assert not lock.exists()


def test_stale_lock_is_taken_over(project):
    import os
    lock = project.local_dir / "tasks" / ".lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text("12345")
    os.utime(str(lock), (1, 1))  # left behind by a crashed process
    assert task.start(project, "a", "ui")["id"] == "T-001"


def test_task_state_is_local_and_git_ignored(project, repo):
    import subprocess
    task.start(project, "a", "ui")
    assert (repo / ".claude" / "uccif" / ".local" / "tasks" / "current.json").exists()
    gi = (repo / ".claude" / "uccif" / ".gitignore").read_text()
    assert ".local/" in gi
    out = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all"], cwd=str(repo),
                         capture_output=True, text=True).stdout
    assert ".local" not in out and ".claude/uccif/.gitignore" in out
    task.close(project, no_findings=True)
    task.start(project, "b", "ui")
    assert (repo / ".claude" / "uccif" / ".gitignore").read_text().count(".local/") == 1


def test_migrates_tasks_from_plugin_data_dir(project):
    from uccif_lib.paths import write_json
    old = project.data_dir / "tasks"
    write_json(old / "state.json", {"next_id": 7})
    write_json(old / "current.json", {"id": "T-006", "title": "old", "type": "ui",
                                      "status": "in_progress", "files": [], "decisions": [],
                                      "tests": [], "issues": []})
    (project.data_dir / "current-task.md").write_text("Task: T-006 — old\n")
    assert task.migrate_from_data_dir(project) is True
    assert task.load_current(project)["id"] == "T-006" and not old.exists()
    assert task.migrate_from_data_dir(project) is False
    task.close(project, no_findings=True)
    assert task.start(project, "new", "ui")["id"] == "T-007"
