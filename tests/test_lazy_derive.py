"""Big repos: a post-Edit update defers the derived edges; the next full-scan update catches up."""
import os
import time

import pytest

from uccif_lib import index, ts_parse


def _ts(monkeypatch):
    monkeypatch.delenv("UCCIF_NO_TREE_SITTER", raising=False)
    if not any(ts_parse.availability().values()):
        pytest.skip("tree-sitter not installed")


def derived(project):
    con = index.connect(project, write=False)
    rows = con.execute("SELECT src_path, kind, detail FROM edges WHERE kind='references_type'").fetchall()
    stale = index._meta(con, "derived_stale")
    con.close()
    return set(rows), stale


def test_defer_and_catch_up(project, vue_app, monkeypatch):
    _ts(monkeypatch)
    index.update(project)
    before, stale = derived(project)
    assert ("src/components/ExpenseList.vue", "references_type", "Expense") in before and stale == "0"
    monkeypatch.setattr(index, "DERIVE_BUDGET_MS", -1)  # pretend the repo is big
    f = vue_app / "src" / "components" / "ExpenseList.vue"
    f.write_text(f.read_text().replace("add(e: Expense)", "add(e: unknown)"), encoding="utf-8")
    os.utime(str(f), (time.time() + 10, time.time() + 10))
    st = index.update(project, paths=["src/components/ExpenseList.vue"])  # the post-Edit path
    assert st["derived_stale"] is True
    _, stale = derived(project)
    assert stale == "1" and "pending" in "\n".join(index.status(project))
    st = index.update(project)  # what a query (or the background maintain) runs first
    assert not st["derived_stale"]
    after, stale = derived(project)
    assert stale == "0"
    assert ("src/components/ExpenseList.vue", "references_type", "Expense") not in after  # caught up


def test_small_repo_stays_immediate(project, vue_app, monkeypatch):
    _ts(monkeypatch)
    index.update(project)
    f = vue_app / "src" / "components" / "ExpenseList.vue"
    f.write_text(f.read_text().replace("add(e: Expense)", "add(e: unknown)"), encoding="utf-8")
    os.utime(str(f), (time.time() + 10, time.time() + 10))
    st = index.update(project, paths=["src/components/ExpenseList.vue"])
    assert not st["derived_stale"]
    after, stale = derived(project)
    assert ("src/components/ExpenseList.vue", "references_type", "Expense") not in after and stale == "0"


def test_post_edit_hook_spawns_catch_up(project, vue_app, monkeypatch):
    _ts(monkeypatch)
    from uccif_lib import hooks
    index.update(project)
    monkeypatch.setattr(index, "DERIVE_BUDGET_MS", -1)
    spawned = []
    monkeypatch.setattr(hooks, "spawn", lambda args, proj: spawned.append(args))
    f = vue_app / "src" / "utils" / "math.ts"
    f.write_text(f.read_text() + "\nexport const z = 1\n", encoding="utf-8")
    os.utime(str(f), (time.time() + 10, time.time() + 10))
    hooks.on_post_tool_use({"tool_input": {"file_path": str(f)}}, project)
    assert spawned == [["maintain"]]
