"""Type references (D1) and reads / writes of module variables (D2)."""
import os
import time

import pytest

from conftest import git
from uccif_lib import index, ts_parse


def _ts(monkeypatch):
    monkeypatch.delenv("UCCIF_NO_TREE_SITTER", raising=False)
    if not any(ts_parse.availability().values()):
        pytest.skip("tree-sitter not installed")


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
    assert all(e[4] == "extracted" for e in edges(project, via="~var") if e[2] in ("reads", "writes"))
    # a parameter that shadows the imported name is told apart
    assert ("src/use.ts#shadow", "src/state.ts#count", "reads") not in got
    sym = "\n".join(index.query_symbol(project, "count"))
    assert "(reads)" in sym


def test_script_variables_of_vue_files(project, vue_app, monkeypatch):
    """Only the <script> of a .vue file is read: its module variables, like any other file's."""
    _ts(monkeypatch)
    index.update(project)
    got = {(e[0], e[1], e[2], e[3]) for e in edges(project, via="~var", src_path="src/components/ExpenseForm.vue")}
    f = "src/components/ExpenseForm.vue#"
    assert (f + "submit", f + "title", "writes", 20) in got  # title.value = ''
    assert not [g for g in got if g[3] < 10]  # nothing from the template
    app = {(e[1], e[2]) for e in edges(project, via="~var", src_path="src/App.vue")}
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


def test_shadowing_forms(project, repo, monkeypatch):
    _ts(monkeypatch)
    write(repo, "m.ts", "export let total = 0\nexport let count = 0\n"
          "export function p(total: number) { return total }\n"
          "export function d({ total }: any) { return total }\n"
          "export function l(xs: number[]) { for (const total of xs) {} try {} catch (count) { count } return 1 }\n"
          "export function q() { const total = 1; return total }\n"
          "export const dflt = (n = total) => n\n"
          "export function real() { count++; return total }\n")
    commit(repo)
    index.update(project)
    got = {(e[0].split("#")[1], e[5], e[2]) for e in edges(project, via="~var")}
    assert ("real", "count", "writes") in got and ("real", "total", "reads") in got
    assert ("dflt", "total", "reads") in got  # a default value reads the module variable
    for fn in ("p", "d", "l", "q"):
        assert not [g for g in got if g[0] == fn], fn  # parameter, destructuring, for-of, catch, local
