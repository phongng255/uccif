"""Baseline for the code-graph roadmap: what the index knows about the fixed Vue fixture today.

Later PRs add edges (renders, store use, routes ...); these assertions pin the current
behaviour so each PR shows exactly what it changed. Where a check is a known gap, the test
says so and is flipped by the PR that closes it.
"""
import os

import pytest

from uccif_lib import index, ts_parse

HAS_TS = bool(os.environ.get("UCCIF_NO_TREE_SITTER") is None and ts_parse.availability()["typescript"])


def _con(project):
    index.update(project)
    return index.connect(project, write=False)


def test_fixture_is_indexed(project, vue_app):
    st = index.update(project)
    assert st["files"] == 24
    con = index.connect(project, write=False)
    langs = dict(con.execute("SELECT lang, count(*) FROM files GROUP BY lang"))
    assert langs["vue"] == 8 and langs["typescript"] >= 12 and langs["css"] == 1


def test_symbols_and_tests(project, vue_app):
    con = _con(project)
    syms = {(n, k) for n, k in con.execute("SELECT name, kind FROM symbols")}
    for expected in [("useTripStore", "store"), ("useUiStore", "store"), ("useSync", "function"),
                     ("formatMoney", "function"), ("Expense", "interface"), ("--brand-color", "css-var"),
                     ("App", "component"), ("ExpenseList", "component")]:
        assert expected in syms, expected
    assert index.tests_for(con, "src/utils/math.ts") == ["tests/math.spec.ts"]
    assert index.tests_for(con, "src/stores/trip.ts") == ["tests/trip.spec.ts"]


def test_alias_imports_resolve(project, vue_app):
    con = _con(project)
    assert "src/components/ExpenseList.vue" in index.dependents(con, "src/stores/trip.ts")
    assert "src/App.vue" in index.dependents(con, "src/stores/trip.ts")
    assert "src/main.ts" in index.dependents(con, "src/App.vue")


def test_barrel_chain(project, vue_app):
    """`@/utils` resolves to the barrel; A2 follows its re-exports to the defining files."""
    con = _con(project)
    assert "src/utils/index.ts" in index.dependents(con, "src/utils/format.ts")
    assert "src/components/ExpenseList.vue" in index.dependents(con, "src/utils/index.ts")
    assert "src/components/ExpenseList.vue" in index.dependents(con, "src/utils/format.ts")  # export *
    assert "src/components/ExpenseForm.vue" in index.dependents(con, "src/utils/id.ts")  # export { newId }
    assert "src/components/ExpenseForm.vue" not in index.dependents(con, "src/utils/format.ts")
    assert "tests/math.spec.ts" in index.tests_for(con, "src/utils/format.ts")


def test_query_limits(project, vue_app):
    index.update(project)
    for lines in (index.query_symbol(project, "useTripStore"), index.impact(project, "src/utils/math.ts")):
        assert len(lines) <= index.QUERY_LINES


@pytest.mark.skipif(not HAS_TS, reason="tree-sitter not installed")
def test_calls_with_tree_sitter(project, vue_app, monkeypatch):
    monkeypatch.delenv("UCCIF_NO_TREE_SITTER")
    con = _con(project)
    rows = con.execute("SELECT callee_name, callee_path FROM calls WHERE src_path='src/composables/useSync.ts'").fetchall()
    # `store.$state` / `saveTrip` come through imports; `sync` is local
    assert ("saveTrip", "src/utils/firebase.ts") in rows
    # known gap (roadmap B4/C1): calls on a store variable stay unresolved
    unresolved = con.execute("SELECT count(*) FROM calls WHERE src_path='src/components/ExpenseList.vue' "
                             "AND callee_path IS NULL").fetchone()[0]
    assert unresolved >= 2  # store.addExpense, store.removeExpense
