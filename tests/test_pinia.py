"""Pinia stores, composables and variables of known origin (roadmap B3, B4, part of C1)."""
import os
import time

import pytest

from conftest import git
from uccif_lib import index, ts_parse


def _ts(monkeypatch):
    monkeypatch.delenv("UCCIF_NO_TREE_SITTER", raising=False)
    if not any(ts_parse.availability().values()):
        pytest.skip("tree-sitter not installed")


def _html(monkeypatch):
    _ts(monkeypatch)
    if not ts_parse.html_available():
        pytest.skip("tree-sitter-html not installed")


def write(root, rel, text):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def commit(repo):
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "x")


def edges(project, **where):
    con = index.connect(project, write=False)
    sql = "SELECT src_id, dst_id, kind, line, confidence, detail, src_path, dst_path, via FROM edges"
    if where:
        sql += " WHERE " + " AND ".join("%s=?" % k for k in where)
    rows = con.execute(sql, tuple(where.values())).fetchall()
    con.close()
    return rows


def touch(path, text):
    path.write_text(text, encoding="utf-8")
    os.utime(str(path), (time.time() + 10, time.time() + 10))


def test_store_members_options_and_setup(project, vue_app, monkeypatch):
    _ts(monkeypatch)
    index.update(project)
    con = index.connect(project, write=False)
    got = {r[0]: (r[1], r[2]) for r in con.execute(
        "SELECT id, kind, detail FROM nodes WHERE kind='store_member'")}
    t, u = "src/stores/trip.ts#useTripStore.", "src/stores/ui.ts#useUiStore."
    assert got[t + "expenses"] == ("store_member", "state") and got[t + "total"][1] == "getter"
    assert got[t + "addExpense"][1] == "action" and got[t + "removeExpense"][1] == "action"
    assert got[u + "dark"][1] == "state" and got[u + "toggle"][1] == "action"  # setup store
    c = {(e[0], e[1]) for e in edges(project, kind="contains", src_path="src/stores/trip.ts")}
    assert ("src/stores/trip.ts#useTripStore", t + "addExpense") in c
    sym = "\n".join(index.query_symbol(project, "addExpense"))
    assert "store_member addExpense in useTripStore" in sym


def test_store_variable_calls_and_reads(project, vue_app, monkeypatch):
    _ts(monkeypatch)
    index.update(project)
    act = [e for e in edges(project, kind="calls_action") if e[6] == "src/components/ExpenseList.vue"]
    assert {(e[0], e[1]) for e in act} == {
        ("src/components/ExpenseList.vue#add", "src/stores/trip.ts#useTripStore.addExpense"),
        ("src/components/ExpenseList.vue#remove", "src/stores/trip.ts#useTripStore.removeExpense")}
    assert all(e[4] == "extracted" and e[7] == "src/stores/trip.ts" and e[8] == "~member" for e in act)
    reads = {(e[6], e[5]) for e in edges(project, kind="reads_state")}
    assert ("src/composables/useMoney.ts", "total") in reads and ("src/composables/useSync.ts", "expenses") in reads
    uses = {(e[6], e[1]) for e in edges(project, kind="uses_store")}
    assert ("src/App.vue", "src/stores/ui.ts#useUiStore") in uses
    assert ("src/composables/useSync.ts", "src/stores/trip.ts#useTripStore") in uses


def test_template_store_access(project, vue_app, monkeypatch):
    _html(monkeypatch)
    index.update(project)
    reads = {(e[0], e[1]) for e in edges(project, kind="reads_state", src_path="src/components/ExpenseList.vue")}
    assert ("src/components/ExpenseList.vue#ExpenseList", "src/stores/trip.ts#useTripStore.expenses") in reads
    assert ("src/components/ExpenseList.vue#ExpenseList", "src/stores/trip.ts#useTripStore.total") in reads
    app = {(e[1], e[2]) for e in edges(project, src_path="src/App.vue") if e[8] == "~member"}
    assert ("src/stores/ui.ts#useUiStore.toggle", "calls_action") in app  # @toggle-theme="ui.toggle()"
    assert ("src/stores/trip.ts#useTripStore.name", "reads_state") in app  # :title="trip.name"


def test_composable_destructuring_is_inferred(project, vue_app, monkeypatch):
    _html(monkeypatch)
    index.update(project)
    e = [x for x in edges(project, kind="calls", src_path="src/App.vue") if x[5] == "sync"]
    assert e and e[0][1] == "src/composables/useSync.ts#sync" and e[0][4] == "inferred"  # `const { sync } = useSync()`
    comp = [x for x in edges(project, kind="uses_composable")]
    assert {(x[6], x[1]) for x in comp} >= {("src/App.vue", "src/composables/useSync.ts#useSync"),
                                           ("src/views/ItineraryView.vue", "src/composables/useMoney.ts#useMoney")}


def test_impact_and_symbol_show_store_usage(project, vue_app, monkeypatch):
    _ts(monkeypatch)
    index.update(project)
    out = "\n".join(index.impact(project, "src/stores/trip.ts"))
    assert "uses store useTripStore" in out or "calls store action addExpense" in out
    sym = "\n".join(index.query_symbol(project, "addExpense"))
    assert "Called by (2):" in sym and "src/components/ExpenseList.vue:19 in add" in sym
    assert "Tested by (1):" in sym and "tests/trip.spec.ts:7" in sym
    store = "\n".join(index.query_symbol(project, "total"))
    assert "Used by (" in store and "src/composables/useMoney.ts" in store
    assert len(index.query_symbol(project, "useTripStore")) <= index.QUERY_LINES
    tests = index.tests_for(index.connect(project, write=False), "src/stores/trip.ts")
    assert "tests/trip.spec.ts" in tests


def test_unknown_member_and_pinia_builtins(project, repo, monkeypatch):
    _ts(monkeypatch)
    write(repo, "s.ts", "export const useS = defineStore('s', { state: () => ({ a: 1 }), actions: { go() {} } })\n")
    write(repo, "u.ts", "import { useS } from './s'\nexport function f() {\n  const s = useS()\n"
          "  s.go(); s.$patch({ a: 2 }); s.nope(); return s.a + s.ghost\n}\n")
    commit(repo)
    index.update(project)
    got = {(e[5], e[2], e[4]) for e in edges(project, src_path="u.ts") if e[8] == "~member"}
    assert ("go", "calls_action", "extracted") in got and ("a", "reads_state", "extracted") in got
    assert ("$patch", "calls_ext", "extracted") in got  # Pinia's own API
    assert ("nope", "calls", "unresolved") in got
    assert not [g for g in got if g[0] == "ghost"]  # an unknown property read is not a lead


def test_class_instances_and_inheritance(project, repo, monkeypatch):
    _ts(monkeypatch)
    write(repo, "base.ts", "export class Base {\n  run() {}\n}\n")
    write(repo, "svc.ts", "import { Base } from './base'\nexport class Svc extends Base {\n  own() {}\n}\n")
    write(repo, "use.ts", "import { Svc } from './svc'\nexport function g() {\n  const s = new Svc()\n"
          "  s.own(); s.run(); s.missing()\n}\n")
    write(repo, "svc.test.ts", "import { Svc } from './svc'\ntest('x', () => { const s = new Svc(); s.own() })\n")
    commit(repo)
    index.update(project)
    got = {e[5]: e for e in edges(project, src_path="use.ts") if e[8] == "~member"}
    assert got["own"][1] == "svc.ts#Svc.own" and got["own"][4] == "extracted"
    assert got["run"][1] == "base.ts#Base.run"  # found through `extends`
    assert got["missing"][4] == "unresolved"
    t = [e for e in edges(project, kind="tests") if e[6] == "svc.test.ts"]
    assert {e[1] for e in t} >= {"svc.ts#Svc.own"}


def test_python_instances(project, repo, monkeypatch):
    _ts(monkeypatch)
    write(repo, "m.py", "class Order:\n    def total(self):\n        return 1\n")
    write(repo, "v.py", "from m import Order\n\ndef view():\n    o = Order()\n    return o.total()\n")
    commit(repo)
    index.update(project)
    e = [x for x in edges(project, src_path="v.py") if x[5] == "total"]
    assert e and e[0][1] == "m.py#Order.total" and e[0][4] == "extracted"


def test_derived_member_edges_follow_updates(project, vue_app, monkeypatch):
    _ts(monkeypatch)
    index.update(project)
    f = vue_app / "src" / "stores" / "trip.ts"
    touch(f, f.read_text().replace("addExpense(e: Expense) {", "addItem(e: Expense) {"))
    index.update(project)
    names = {e[5]: e for e in edges(project, src_path="src/components/ExpenseList.vue", via="~member")}
    assert names["addExpense"][2] == "calls" and names["addExpense"][4] == "unresolved"  # renamed: a lead now
    assert names["removeExpense"][2] == "calls_action"
    (vue_app / "src" / "stores" / "trip.ts").unlink()
    index.update(project)
    con = index.connect(project, write=False)
    ids = {r[0] for r in con.execute("SELECT id FROM nodes")}
    assert all(e[1] in ids for e in edges(project) if e[1])  # nothing dangling
    assert not [e for e in edges(project) if e[7] == "src/stores/trip.ts"]


def test_without_tree_sitter_no_member_edges(project, vue_app):
    index.update(project)
    kinds = {e[2] for e in edges(project)}
    assert not kinds & {"calls_action", "reads_state", "uses_store", "uses_composable"}
    con = index.connect(project, write=False)
    assert con.execute("SELECT count(*) FROM nodes WHERE kind='store_member'").fetchone()[0] == 0
