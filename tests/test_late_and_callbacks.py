"""Callbacks (C2), late resolution when an import target appears later (C3), built-in methods (C1)."""
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


def test_callbacks(project, repo, monkeypatch):
    _ts(monkeypatch)
    write(repo, "h.ts", "export function onSave() {}\nexport const KEY = 1\n")
    write(repo, "a.ts", "import { onSave, KEY } from './h'\nfunction init() {}\n"
          "class C {\n  fmt() {}\n  run(xs: number[]) { xs.map(this.fmt) }\n}\n"
          "export function setup(src: any) {\n  watch(src, onSave)\n  onMounted(init)\n  use(KEY, src)\n}\n")
    write(repo, "w.py", "import threading\n\ndef worker():\n    pass\n\ndef go(xs):\n"
          "    threading.Thread(target=worker)\n    return sorted(xs, key=worker)\n")
    commit(repo)
    index.update(project)
    cb = {(e[6], e[0], e[1]) for e in edges(project, kind="passes_callback")}
    assert ("a.ts", "a.ts#setup", "h.ts#onSave") in cb  # imported function
    assert ("a.ts", "a.ts#setup", "a.ts#init") in cb  # local function
    assert ("a.ts", "a.ts#C.run", "a.ts#C.fmt") in cb  # this.fmt
    assert not [c for c in cb if c[2] in ("h.ts#KEY",) or "src" in c[2]]  # data, not functions
    assert ("w.py", "w.py#go", "w.py#worker") in cb
    out = "\n".join(index.query_symbol(project, "onSave"))
    assert "Used by (1):" in out and "a.ts:8 in setup  (passes callback)" in out


def test_builtin_methods_are_external_unless_defined(project, repo, monkeypatch):
    _ts(monkeypatch)
    write(repo, "a.ts", "export function f(xs: number[], s: string) {\n  xs.map(x => x).filter(Boolean)\n"
          "  s.toFixed(2)\n  q.flush()\n}\n")
    write(repo, "b.py", "def g(cur, d):\n    cur.execute('x')\n    d.items()\n")
    commit(repo)
    index.update(project)
    got = {(e[6], e[5]): (e[2], e[4]) for e in edges(project, via="~builtin")}
    assert got[("a.ts", "map")] == ("calls_ext", "extracted")
    assert got[("a.ts", "toFixed")] == ("calls_ext", "extracted")
    assert got[("b.py", "execute")] == ("calls_ext", "extracted")
    # the repo now defines a `flush` method: the same call becomes an unresolved lead again
    write(repo, "c.ts", "export class Buf {\n  flush() {}\n}\n")
    commit(repo)
    index.update(project)
    got = {(e[6], e[5]): (e[2], e[4]) for e in edges(project, via="~builtin")}
    assert got[("a.ts", "flush")] == ("calls", "unresolved")
    assert got[("a.ts", "map")] == ("calls_ext", "extracted")


def test_import_target_created_later(project, repo, monkeypatch):
    _ts(monkeypatch)
    write(repo, "src/app.ts", "import { helper } from './later'\nexport function main() { helper() }\n")
    commit(repo)
    index.update(project)
    imp = edges(project, kind="imports", src_path="src/app.ts")
    assert imp[0][4] == "unresolved"  # './later' does not exist yet
    write(repo, "src/later.ts", "export function helper() {}\n")  # created after (untracked is fine)
    st = index.update(project)
    assert st["parsed"] == 2  # the new file, then the importer re-parsed once
    imp = edges(project, kind="imports", src_path="src/app.ts")
    assert imp[0][1] == "src/later.ts" and imp[0][4] == "extracted"
    call = [e for e in edges(project, kind="calls", src_path="src/app.ts") if e[5] == "helper"]
    assert call and call[0][1] == "src/later.ts#helper" and call[0][4] == "extracted"
    # nothing to rescue: an unrelated new file does not re-parse importers
    write(repo, "src/other.ts", "export const z = 1\n")
    assert index.update(project)["parsed"] == 1


def test_hopeless_imports_are_not_reparsed(project, repo, monkeypatch):
    _ts(monkeypatch)
    write(repo, "a.ts", "import x from './missing'\n")
    commit(repo)
    index.update(project)
    write(repo, "b.ts", "export const y = 1\n")
    assert index.update(project)["parsed"] == 1
