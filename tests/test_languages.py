"""Roadmap layer E: Go, Rust, Java (optional grammars tree-sitter-go / -rust / -java)."""
import pytest

from conftest import git
from uccif_lib import index, ts_parse


def _lang(monkeypatch, grammar):
    monkeypatch.delenv("UCCIF_NO_TREE_SITTER", raising=False)
    if not ts_parse._parser(grammar):
        pytest.skip("tree-sitter-%s not installed" % grammar)


def write(root, rel, text):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def commit(repo):
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "x")


def calls(project, src):
    con = index.connect(project, write=False)
    rows = con.execute("SELECT src_id, dst_id, kind, confidence, detail FROM edges WHERE src_path=? AND kind IN "
                       "('calls','calls_ext')", (src,)).fetchall()
    con.close()
    out = {}
    for r in rows:  # several calls can share (caller, name): keep every target
        out.setdefault((r[0].split("#")[-1], r[4]), set()).add((r[1], r[2], r[3]))
    return out


def hit(found, target):
    return any(t[0] == target for t in found)


def test_go(project, repo, monkeypatch):
    _lang(monkeypatch, "go")
    write(repo, "go.mod", "module example.com/app\n\ngo 1.22\n")
    write(repo, "pkg/store/store.go", "package store\n\ntype Store struct{}\n\nfunc New() *Store { return &Store{} }\n")
    write(repo, "pkg/store/save.go", "package store\n\nfunc (s *Store) Save(k string) { s.log(k) }\n")
    write(repo, "pkg/store/log.go", "package store\n\nimport \"fmt\"\n\nfunc (s *Store) log(k string) { fmt.Println(k) }\n")
    write(repo, "cmd/main.go", "package main\n\nimport (\n\t\"fmt\"\n\tst \"example.com/app/pkg/store\"\n)\n\n"
          "func main() {\n\ts := st.New()\n\trun(s)\n\tfmt.Println(len(\"x\"))\n}\n")
    write(repo, "cmd/run.go", "package main\n\nimport \"example.com/app/pkg/store\"\n\n"
          "func run(s *store.Store) { s.Save(\"k\") }\n")
    write(repo, "pkg/store/store_test.go", "package store\n\nfunc TestSave(t *testing.T) { New().Save(\"x\") }\n")
    commit(repo)
    index.update(project)
    con = index.connect(project, write=False)
    syms = {(n, k, sc) for n, k, sc in con.execute("SELECT name, kind, scope FROM symbols WHERE path LIKE 'pkg/%'")}
    assert ("Store", "class", None) in syms and ("Save", "method", "Store") in syms and ("New", "function", None) in syms
    imp = {r[0] for r in con.execute("SELECT dst_path FROM edges WHERE kind='imports' AND src_path='cmd/main.go'")}
    assert imp == {"pkg/store/log.go", "pkg/store/save.go", "pkg/store/store.go"}  # a package is its files
    assert "cmd/main.go" in index.dependents(con, "pkg/store/save.go")
    con.close()
    m = calls(project, "cmd/main.go")
    assert hit(m[("main", "New")], "pkg/store/store.go#New")  # pkg.Func()
    assert hit(m[("main", "run")], "cmd/run.go#run")  # same package, another file, no import
    assert {k for _, k, _ in m[("main", "Println")] | m[("main", "len")]} == {"calls_ext"}
    r = calls(project, "cmd/run.go")
    assert hit(r[("run", "Save")], "pkg/store/save.go#Store.Save")  # typed parameter *store.Store
    s = calls(project, "pkg/store/save.go")
    assert hit(s[("Store.Save", "log")], "pkg/store/log.go#Store.log")  # receiver method in a sibling file
    assert "pkg/store/store_test.go" in index.tests_for(index.connect(project, write=False), "pkg/store/store.go")


def test_rust(project, repo, monkeypatch):
    _lang(monkeypatch, "rust")
    write(repo, "Cargo.toml", "[package]\nname = \"app\"\n")
    write(repo, "src/main.rs", "mod util;\nmod model;\nuse crate::util::helper;\nuse crate::model::Order;\n\n"
          "fn main() {\n    helper();\n    util::other();\n    let o = Order::new();\n    show(&o);\n"
          "    let v: Vec<u8> = Vec::new();\n}\n\nfn show(o: &Order) {\n    o.total();\n}\n")
    write(repo, "src/util.rs", "pub fn helper() {}\npub fn other() {}\n")
    write(repo, "src/model/mod.rs", "pub struct Order;\npub trait Priced { fn price(&self) -> u32; }\n"
          "impl Order {\n    pub fn new() -> Self { Order }\n    pub fn total(&self) -> u32 { self.base() }\n"
          "    fn base(&self) -> u32 { 1 }\n}\nimpl Priced for Order { fn price(&self) -> u32 { 2 } }\n")
    commit(repo)
    index.update(project)
    con = index.connect(project, write=False)
    imp = {r[0] for r in con.execute("SELECT dst_path FROM edges WHERE kind='imports' AND src_path='src/main.rs'")}
    assert imp == {"src/util.rs", "src/model/mod.rs"}  # mod x; and use crate::x
    her = con.execute("SELECT src_id, dst_id FROM edges WHERE kind='implements'").fetchall()
    assert ("src/model/mod.rs#Order", "src/model/mod.rs#Priced") in her
    con.close()
    m = calls(project, "src/main.rs")
    assert hit(m[("main", "helper")], "src/util.rs#helper")  # use crate::util::helper
    assert hit(m[("main", "other")], "src/util.rs#other")  # util::other()
    assert hit(m[("main", "new")], "src/model/mod.rs#Order.new")  # Order::new()
    assert hit(m[("show", "total")], "src/model/mod.rs#Order.total")  # typed parameter &Order
    assert ("main", "Vec") not in m  # Vec::new() is std
    mm = calls(project, "src/model/mod.rs")
    assert hit(mm[("Order.total", "base")], "src/model/mod.rs#Order.base")  # self.base()


def test_java(project, repo, monkeypatch):
    _lang(monkeypatch, "java")
    root = "src/main/java/com/acme/"
    write(repo, root + "util/Util.java", "package com.acme.util;\npublic class Util { public static void go() {} }\n")
    write(repo, root + "app/Base.java", "package com.acme.app;\npublic class Base { void hello() {} }\n")
    write(repo, root + "app/Helper.java", "package com.acme.app;\npublic class Helper { static void assist() {} "
          "void help() {} }\n")
    write(repo, root + "app/Service.java", "package com.acme.app;\nimport com.acme.util.Util;\n"
          "public class Service extends Base {\n  private Helper h;\n  void run(Helper p) {\n    Util.go();\n"
          "    Helper.assist();\n    p.help();\n    h.help();\n    this.tidy();\n    Helper x = new Helper();\n"
          "    System.out.println(1);\n  }\n  void tidy() {}\n}\n")
    commit(repo)
    index.update(project)
    s = calls(project, root + "app/Service.java")
    assert hit(s[("Service.run", "go")], root + "util/Util.java#Util.go")  # imported class, static
    assert hit(s[("Service.run", "assist")], root + "app/Helper.java#Helper.assist")  # same package, no import
    assert hit(s[("Service.run", "help")], root + "app/Helper.java#Helper.help")  # typed param / field
    assert hit(s[("Service.run", "tidy")], root + "app/Service.java#Service.tidy")  # this.tidy()
    assert hit(s[("Service.run", "Helper")], root + "app/Helper.java#Helper")  # new Helper()
    con = index.connect(project, write=False)
    assert root + "app/Service.java" in index.dependents(con, root + "util/Util.java")
    assert con.execute("SELECT 1 FROM edges WHERE kind='extends' AND src_id=?", (root + "app/Service.java#Service",)
                       ).fetchone()


def test_without_grammars_nothing_changes(project, repo, monkeypatch):
    monkeypatch.setattr(ts_parse, "_parser", lambda g: None)
    write(repo, "a.go", "package main\nfunc main() {}\n")
    commit(repo)
    index.update(project)
    con = index.connect(project, write=False)
    assert con.execute("SELECT precision FROM symbols WHERE name='main'").fetchone()[0] == "approx"  # regex as before
