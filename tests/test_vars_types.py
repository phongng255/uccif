"""Type references (D1) and reads / writes of module variables and refs (D2)."""
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


def test_type_references_ts(project, repo, monkeypatch):
    _ts(monkeypatch)
    write(repo, "src/types/trip.ts", "export interface Expense { id: string }\nexport type Currency = 'THB'\n")
    write(repo, "src/types/index.ts", "export * from './trip'\n")
    write(repo, "src/a.ts", "import type { Expense } from './types/trip'\nimport { Currency } from './types'\n"
          "interface Box<T> { v: T }\nexport function f(e: Expense, c: Currency): Box<Expense> {\n"
          "  return { v: e }\n}\nconst list: Expense[] = []\n")
    commit(repo)
    index.update(project)
    got = {(e[0], e[1]) for e in edges(project, kind="references_type")}
    assert ("src/a.ts#f", "src/types/trip.ts#Expense") in got
    assert ("src/a.ts#f", "src/types/trip.ts#Currency") in got  # through the barrel
    assert ("src/a.ts#f", "src/a.ts#Box") in got  # same-file type
    assert ("src/a.ts", "src/types/trip.ts#Expense") in got  # top-level annotation
    assert all(e[4] == "extracted" for e in edges(project, kind="references_type"))
    assert not [g for g in got if g[1].endswith("#T")]  # generic parameter, not a type of the repo
    out = "\n".join(index.impact(project, "src/types/trip.ts"))
    assert "src/a.ts" in out


def test_type_references_python(project, repo, monkeypatch):
    _ts(monkeypatch)
    write(repo, "m.py", "class Order:\n    pass\n\nclass Item:\n    pass\n")
    write(repo, "v.py", "from m import Order, Item\n\ndef f(o: Order, xs: list[Item] = None) -> Order:\n"
          "    return o\n")
    commit(repo)
    index.update(project)
    got = {(e[0], e[1]) for e in edges(project, kind="references_type")}
    assert got == {("v.py#f", "m.py#Order"), ("v.py#f", "m.py#Item")}  # list is a built-in: nothing


def test_reads_and_writes(project, repo, monkeypatch):
    _ts(monkeypatch)
    write(repo, "src/state.ts", "export let count = 0\nexport const tab = ref('a')\n")
    write(repo, "src/use.ts", "import { count, tab } from './state'\nlet local = 1\n"
          "export function bump(n: number) {\n  local += n\n  tab.value = 'b'\n  return count + local\n}\n"
          "export function shadow(count: number) {\n  return count\n}\n")
    commit(repo)
    index.update(project)
    got = {(e[0], e[1], e[2]) for e in edges(project, via="~var") if e[2] in ("reads", "writes")}
    assert ("src/use.ts#bump", "src/use.ts#local", "writes") in got
    assert ("src/use.ts#bump", "src/use.ts#local", "reads") in got
    assert ("src/use.ts#bump", "src/state.ts#tab", "writes") in got  # tab.value = ...
    assert ("src/use.ts#bump", "src/state.ts#count", "reads") in got
    assert all(e[4] == "inferred" for e in edges(project, via="~var") if e[2] in ("reads", "writes"))
    # known limit, documented: a parameter that shadows an imported name is not told apart
    assert ("src/use.ts#shadow", "src/state.ts#count", "reads") in got
    sym = "\n".join(index.query_symbol(project, "count"))
    assert "(reads)" in sym


def test_template_refs(project, vue_app, monkeypatch):
    _html(monkeypatch)
    index.update(project)
    got = {(e[0], e[1], e[2], e[3]) for e in edges(project, via="~var", src_path="src/components/ExpenseForm.vue")}
    f = "src/components/ExpenseForm.vue#"
    assert (f + "ExpenseForm", f + "title", "writes", 3) in got  # v-model="title"
    assert (f + "ExpenseForm", f + "amount", "writes", 4) in got  # v-model.number="amount"
    assert (f + "submit", f + "title", "writes", 20) in got  # title.value = ''
    app = {(e[1], e[2]) for e in edges(project, via="~var", src_path="src/App.vue")}
    assert ("src/App.vue#tab", "reads") in app and ("src/App.vue#tabs", "reads") in app
    assert ("src/App.vue#tab", "writes") in app  # tab.value = t in select()


def test_var_edges_follow_updates(project, repo, monkeypatch):
    _ts(monkeypatch)
    write(repo, "s.ts", "export const LIMIT = 5\n")
    write(repo, "u.ts", "import { LIMIT } from './s'\nexport function ok(n: number) { return n < LIMIT }\n")
    commit(repo)
    index.update(project)
    assert [e for e in edges(project, kind="reads") if e[1] == "s.ts#LIMIT"]
    f = repo / "s.ts"
    f.write_text("export const MAX = 5\n", encoding="utf-8")
    os.utime(str(f), (time.time() + 10, time.time() + 10))
    index.update(project)
    assert not [e for e in edges(project, kind="reads") if e[7] == "s.ts"]  # renamed: no stale edge
