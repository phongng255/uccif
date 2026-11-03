"""extends / implements (A1), contains (A3), tests at function level (A4)."""
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


def make_ts(repo):
    write(repo, "src/base.ts", "export interface Shape { area(): number }\n"
          "export class Base {\n  run() { return 1 }\n}\n")
    write(repo, "src/index.ts", "export * from './base'\n")
    write(repo, "src/circle.ts",
          "import { Base, Shape } from './base'\nimport { Vue } from 'vue'\n"
          "export class Circle extends Base implements Shape {\n  area() { return 3 }\n}\n"
          "export class Oops extends Missing {}\nexport class Err extends Error {}\n"
          "export class Cmp extends Vue {}\nexport interface Round extends Shape {}\n")
    write(repo, "src/square.ts", "import { Base } from '@/index'\nexport class Square extends Base<number> {}\n")
    write(repo, "src/base.test.ts", "import { Base } from './base'\ntest('run', () => new Base().run())\n"
          "test('again', () => { const b = new Base(); b.run() })\n")
    commit(repo)


def test_ts_heritage_edges(project, repo, monkeypatch):
    _ts(monkeypatch)
    make_ts(repo)
    index.update(project)
    got = {(e[0].split("#")[-1], e[2], e[5]): e for e in edges(project, src_path="src/circle.ts")
           if e[2] in ("extends", "implements", "extends_ext", "implements_ext")}
    base = got[("Circle", "extends", "Base")]
    assert base[1] == "src/base.ts#Base" and base[4] == "extracted" and base[7] == "src/base.ts" and base[3] == 3
    assert got[("Circle", "implements", "Shape")][1] == "src/base.ts#Shape"
    assert got[("Round", "extends", "Shape")][1] == "src/base.ts#Shape"  # interface extends
    assert got[("Err", "extends_ext", "Error")][4] == "extracted"  # built-in
    assert got[("Cmp", "extends_ext", "Vue")][1] is None  # package
    miss = got[("Oops", "extends", "Missing")]
    assert miss[4] == "unresolved" and miss[1] is None


def test_heritage_through_barrel_and_generics(project, repo, monkeypatch):
    _ts(monkeypatch)
    make_ts(repo)
    index.update(project)
    direct = [e for e in edges(project, src_path="src/square.ts", kind="extends") if e[8] is None]
    derived = [e for e in edges(project, src_path="src/square.ts", kind="extends") if e[8]]
    assert direct and direct[0][7] == "src/index.ts"  # alias @/ + generic arguments dropped
    assert derived and derived[0][1] == "src/base.ts#Base" and derived[0][8] == "src/index.ts"


def test_symbol_query_shows_subclasses_and_tests(project, repo, monkeypatch):
    _ts(monkeypatch)
    make_ts(repo)
    index.update(project)
    out = index.query_symbol(project, "Base")
    text = "\n".join(out)
    assert "Subclasses / implementations (2):" in text  # Circle, Square (via the barrel)
    assert "src/circle.ts:3  Circle (extends)" in text and "Square (extends)" in text
    assert "Tested by (" in text and "src/base.test.ts:2" in text
    assert len(out) <= index.QUERY_LINES
    circle = "\n".join(index.query_symbol(project, "Circle"))
    assert "Extends / implements:" in circle and "extends Base  (src/base.ts)" in circle
    assert "implements Shape" in circle


def test_contains_edges(project, repo, monkeypatch):
    _ts(monkeypatch)
    make_ts(repo)
    index.update(project)
    c = {(e[0], e[1]) for e in edges(project, kind="contains", src_path="src/base.ts")}
    assert ("src/base.ts", "src/base.ts#Base") in c and ("src/base.ts#Base", "src/base.ts#Base.run") in c
    assert ("src/base.ts", "src/base.ts#Shape") in c
    assert all(e[4] == "extracted" and e[6] == e[7] for e in edges(project, kind="contains"))
    # impact and graph walk only imports/calls: containment never makes a file "depend" on itself
    assert index.dependents(index.connect(project, write=False), "src/base.ts") == [
        "src/base.test.ts", "src/circle.ts", "src/index.ts", "src/square.ts"]  # square.ts: through the barrel


def test_tests_edges_and_tests_for(project, repo, monkeypatch):
    _ts(monkeypatch)
    make_ts(repo)
    index.update(project)
    t = edges(project, kind="tests")
    assert {(e[6], e[5]) for e in t} >= {("src/base.test.ts", "Base")}  # `new Base().run()`: receiver is an expression (roadmap C1)
    assert all(e[6].endswith(".test.ts") for e in t)
    con = index.connect(project, write=False)
    assert index.tests_for(con, "src/base.ts") == ["src/base.test.ts"]
    assert index.tests_for(con, "src/circle.ts") == []


def test_removed_base_file_leaves_unresolved_lead(project, repo, monkeypatch):
    _ts(monkeypatch)
    make_ts(repo)
    index.update(project)
    (repo / "src" / "base.ts").unlink()
    index.update(project)
    rows = [e for e in edges(project, src_path="src/circle.ts", kind="extends") if e[5] == "Base"]
    assert rows and rows[0][4] == "unresolved" and rows[0][1] is None and rows[0][7] is None


def test_python_heritage(project, repo, monkeypatch):
    _ts(monkeypatch)
    write(repo, "shop/__init__.py", "")
    write(repo, "shop/base.py", "class Base:\n    pass\n")
    write(repo, "shop/models.py",
          "import shop.base as sb\nfrom typing import Generic\nfrom .base import Base\n\n"
          "class Order(Base):\n    pass\n\nclass Item(sb.Base):\n    pass\n\nclass Boom(ValueError):\n    pass\n\n"
          "class Box(Generic[int]):\n    pass\n\nclass Sub(Order):\n    def total(self):\n        pass\n")
    commit(repo)
    index.update(project)
    got = {(e[0].split("#")[-1], e[5]): e for e in edges(project, src_path="shop/models.py")
           if e[2] in ("extends", "extends_ext")}
    assert got[("Order", "Base")][1] == "shop/base.py#Base"
    assert got[("Item", "Base")][1] == "shop/base.py#Base"  # module.Class through a namespace import
    assert got[("Boom", "ValueError")][2] == "extends_ext"
    assert got[("Box", "Generic")][2] == "extends_ext"
    assert got[("Sub", "Order")][1] == "shop/models.py#Order"  # same file
    contains = {(e[0], e[1]) for e in edges(project, kind="contains", src_path="shop/models.py")}
    assert ("shop/models.py#Sub", "shop/models.py#Sub.total") in contains


def test_no_tree_sitter_has_contains_but_no_heritage(project, repo):
    make_ts(repo)
    index.update(project)
    kinds = {e[2] for e in edges(project)}
    assert "contains" in kinds and not kinds & {"extends", "implements", "tests", "calls"}
