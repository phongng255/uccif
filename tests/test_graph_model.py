"""Unified nodes/edges model (code-graph roadmap, step 2)."""
import os
import time

import pytest

from conftest import git
from uccif_lib import index, ts_parse


def _ts(monkeypatch):
    monkeypatch.delenv("UCCIF_NO_TREE_SITTER", raising=False)
    if not any(ts_parse.availability().values()):
        pytest.skip("tree-sitter not installed")


def _edges(con, **where):
    sql = "SELECT src_id, dst_id, kind, line, confidence, detail, src_path, dst_path FROM edges"
    if where:
        sql += " WHERE " + " AND ".join("%s=?" % k for k in where)
    return con.execute(sql, tuple(where.values())).fetchall()


def _touch(path, text):
    path.write_text(text, encoding="utf-8")
    os.utime(str(path), (time.time() + 10, time.time() + 10))


def test_nodes_and_import_edges_without_tree_sitter(project, vue_app):
    index.update(project)
    con = index.connect(project, write=False)
    kinds = {k for (k,) in con.execute("SELECT DISTINCT kind FROM nodes")}
    assert {"file", "store", "component", "interface", "css_var"} <= kinds  # '-' becomes '_' in node kinds
    node = con.execute("SELECT kind, path, line FROM nodes WHERE id='src/stores/trip.ts#useTripStore'").fetchone()
    assert node[0] == "store" and node[1] == "src/stores/trip.ts"
    assert con.execute("SELECT count(*) FROM nodes WHERE kind='file'").fetchone()[0] == 24
    ok = [e for e in _edges(con, kind="imports", src_path="src/App.vue", dst_path="src/stores/trip.ts")]
    assert len(ok) == 1 and ok[0][4] == "extracted" and ok[0][1] == "src/stores/trip.ts" and ok[0][5] == "@/stores/trip"
    assert ok[0][3] > 0  # line recorded
    # packages are known exactly (not "unresolved"); repo-looking paths we cannot place are
    ext = _edges(con, kind="imports_ext", src_path="src/App.vue")
    assert {e[5] for e in ext} == {"vue"} and all(e[4] == "extracted" and e[1] is None for e in ext)
    assert not _edges(con, kind="calls")  # no call edges without tree-sitter


def test_dependents_come_from_edges(project, vue_app):
    index.update(project)
    con = index.connect(project, write=False)
    assert "src/App.vue" in index.dependents(con, "src/stores/trip.ts")
    assert index._users_of(con, "src/stores/trip.ts", kinds=("calls",)) == []  # no tree-sitter: no calls


def test_call_edges_point_at_symbol_nodes(project, vue_app, monkeypatch):
    _ts(monkeypatch)
    index.update(project)
    con = index.connect(project, write=False)
    e = [x for x in _edges(con, kind="calls", src_path="src/composables/useSync.ts") if x[5] == "saveTrip"]
    assert e and e[0][4] == "extracted" and e[0][1] == "src/utils/firebase.ts#saveTrip"
    assert e[0][0] == "src/composables/useSync.ts#sync"  # caller is the enclosing function's node
    unres = _edges(con, kind="calls", src_path="src/components/ExpenseList.vue", confidence="unresolved")
    assert {x[5] for x in unres} >= {"addExpense", "removeExpense"} and all(x[1] is None for x in unres)


def test_confidence_filter(project, vue_app, monkeypatch):
    _ts(monkeypatch)
    index.update(project)
    con = index.connect(project, write=False)
    assert "src/composables/useSync.ts" in index._users_of(con, "src/utils/firebase.ts", kinds=("calls",))
    con.execute  # read-only connection: promote nothing, just ask for a stricter floor
    assert index._conf_ok("extracted") == ["extracted"]
    assert index._conf_ok(None) == ["extracted", "inferred"]
    assert "unresolved" not in index._conf_ok("unresolved")  # an edge without a target is never a "user"
    lines = index.impact(project, "src/utils/firebase.ts", kinds=("calls",), min_confidence="extracted")
    assert any("useSync.ts" in ln for ln in lines)
    only_imports = index.impact(project, "src/utils/firebase.ts", kinds=("imports",))
    assert any("useSync.ts" in ln and "imports" in ln for ln in only_imports)


def test_reparse_keeps_incoming_edges(project, vue_app, monkeypatch):
    """Other files' edges to a symbol survive that file being re-parsed; if the symbol is gone
    they fall back to the file node instead of dangling."""
    _ts(monkeypatch)
    index.update(project)
    f = vue_app / "src" / "utils" / "firebase.ts"
    _touch(f, f.read_text() + "\nexport const extra = 1\n")
    assert index.update(project)["parsed"] == 1
    con = index.connect(project, write=False)
    e = [x for x in _edges(con, kind="calls", dst_path="src/utils/firebase.ts") if x[5] == "saveTrip"]
    assert e and e[0][1] == "src/utils/firebase.ts#saveTrip"
    con.close()
    _touch(f, "export async function other() {}\n")  # saveTrip removed
    index.update(project)
    con = index.connect(project, write=False)
    e = [x for x in _edges(con, kind="calls", dst_path="src/utils/firebase.ts") if x[5] == "saveTrip"]
    assert e and e[0][1] == "src/utils/firebase.ts"
    ids = {r[0] for r in con.execute("SELECT id FROM nodes")}
    assert all(x[1] in ids for x in _edges(con) if x[1])  # no dangling destination


def test_deleted_file_leaves_no_orphans(project, vue_app):
    index.update(project)
    (vue_app / "src" / "utils" / "math.ts").unlink()
    st = index.update(project)
    assert st["removed"] == 1
    con = index.connect(project, write=False)
    assert not con.execute("SELECT 1 FROM nodes WHERE path='src/utils/math.ts'").fetchone()
    assert not _edges(con, src_path="src/utils/math.ts")
    assert not _edges(con, dst_path="src/utils/math.ts")
    gone = [e for e in _edges(con, src_path="src/stores/trip.ts", kind="imports") if e[5] == "@/utils/math"]
    assert gone and gone[0][4] == "unresolved" and gone[0][1] is None  # kept as a lead, no dangling id
    assert "src/stores/trip.ts" not in index.dependents(con, "src/utils/math.ts")


def test_schema_3_index_is_rebuilt(project, vue_app):
    index.update(project)
    con = index.connect(project)
    con.execute("UPDATE meta SET value='3' WHERE key='schema'")
    con.commit()
    con.close()
    with pytest.raises(index.IndexUnavailable):  # a reader never serves the old layout
        index.connect(project, write=False)
    assert index.update(project)["parsed"] == 24  # writer upgrades and reparses everything
    con = index.connect(project, write=False)
    assert con.execute("SELECT count(*) FROM edges").fetchone()[0] > 0


def test_status_reports_confidence(project, vue_app):
    index.update(project)
    out = "\n".join(index.status(project))
    assert "Graph:" in out and "extracted" in out and "unresolved" in out


def test_package_calls_are_external_not_unresolved(project, vue_app, monkeypatch):
    _ts(monkeypatch)
    index.update(project)
    con = index.connect(project, write=False)
    ext = {e[5] for e in _edges(con, kind="calls_ext", src_path="src/App.vue")}
    assert {"ref", "onMounted"} <= ext  # imported from 'vue'
    assert all(e[4] == "extracted" and e[1] is None for e in _edges(con, kind="calls_ext"))
    unres = {e[5] for e in _edges(con, confidence="unresolved")}
    assert "ref" not in unres and "addExpense" in unres
    # package calls never show up as "possibly called by"
    assert "Possibly called by" not in "\n".join(index.query_symbol(project, "ref"))


def test_python_repo_import_we_cannot_place_stays_unresolved(project, repo):
    from conftest import git
    (repo / "plugins" / "x" / "pkg").mkdir(parents=True)
    (repo / "plugins" / "x" / "pkg" / "__init__.py").write_text("")
    (repo / "plugins" / "x" / "pkg" / "core.py").write_text("def f():\n    pass\n")
    (repo / "plugins" / "x" / "pkg" / "cli.py").write_text("from pkg.core import f\nimport os\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "py")
    index.update(project)
    con = index.connect(project, write=False)
    e = {(x[2], x[4], x[5]) for x in _edges(con, src_path="plugins/x/pkg/cli.py")}
    assert ("imports", "unresolved", "pkg.core") in e  # known limit C4: shown as a lead, not hidden
    assert ("imports_ext", "extracted", "os") in e


def test_builtin_calls_are_external(project, repo, monkeypatch):
    _ts(monkeypatch)
    from conftest import git
    (repo / "a.py").write_text("def len(x):\n    return 0\n\ndef g():\n    print(str(1))\n    len([])\n")
    (repo / "b.ts").write_text("export function h() { console.log(1); Math.max(1, 2); setTimeout(h) }\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "b")
    index.update(project)
    con = index.connect(project, write=False)
    got = {(e[6], e[5]): (e[2], e[4]) for e in _edges(con)}
    assert got[("a.py", "print")] == ("calls_ext", "extracted")
    assert got[("a.py", "str")] == ("calls_ext", "extracted")
    assert got[("a.py", "len")] == ("calls", "extracted")  # shadowed by a repo definition
    assert got[("b.ts", "log")] == ("calls_ext", "extracted")
    assert got[("b.ts", "setTimeout")] == ("calls_ext", "extracted")
