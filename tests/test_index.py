import os
import time

from conftest import git
from uccif_lib import index


def write(repo, rel, text):
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def make_app(repo):
    write(repo, "package.json", '{"dependencies": {"vue": "3"}}')
    write(repo, "src/utils/math.ts",
          "export function add(a: number, b: number) {\n  return a + b;\n}\n"
          "export const double = (x: number) => x * 2;\n"
          "export interface Point { x: number }\n")
    write(repo, "src/components/Cart.vue",
          "<template><div>{{ total }}</div></template>\n"
          "<script setup lang=\"ts\">\nimport { add } from '@/utils/math'\n"
          "const total = add(1, 2)\nfunction refresh() { return total }\n</script>\n")
    write(repo, "src/stores/cart.ts",
          "import { defineStore } from 'pinia'\nimport { add } from '../utils/math'\n"
          "export const useCart = defineStore('cart', {})\n")
    write(repo, "src/utils/math.spec.ts", "import { add } from './math'\ntest('add', () => add(1, 1))\n")
    write(repo, "app/models.py",
          "class Order:\n    def total(self):\n        return 1\n\nMAX_ITEMS = 5\n\ndef helper():\n    pass\n")
    write(repo, "app/views.py", "from .models import Order\nimport app.models\n")
    write(repo, "src/styles/tokens.css", ":root {\n  --brand-color: #fff;\n}\n")
    write(repo, "src/main.min.js", "function x(){}")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "app")


def test_build_extracts_symbols_imports_and_tests(project, repo):
    make_app(repo)
    stats = index.update(project)
    assert stats["files"] == 7 and stats["parsed"] == 7  # .min.js skipped, package.json not source
    con = index.connect(project)
    syms = {(n, k) for n, k in con.execute("SELECT name, kind FROM symbols")}
    for expected in [("add", "function"), ("double", "function"), ("Point", "interface"),
                     ("useCart", "store"), ("refresh", "function"), ("Cart", "component"),
                     ("Order", "class"), ("total", "method"), ("MAX_ITEMS", "constant"),
                     ("helper", "function"), ("--brand-color", "css-var")]:
        assert expected in syms, expected
    assert set(index.dependents(con, "src/utils/math.ts")) == {
        "src/components/Cart.vue", "src/stores/cart.ts", "src/utils/math.spec.ts"}
    assert index.dependents(con, "app/models.py") == ["app/views.py"]
    assert index.tests_for(con, "src/utils/math.ts") == ["src/utils/math.spec.ts"]
    con.close()


def test_query_symbol_and_file(project, repo):
    make_app(repo)
    index.update(project)
    out = "\n".join(index.query_symbol(project, "add"))
    assert "src/utils/math.ts:1  function add" in out and "[3 dependents]" in out
    assert "Referenced (whole word) in" in out and "src/components/Cart.vue" in out
    fuzzy = "\n".join(index.query_symbol(project, "usecar"))
    assert "useCart" in fuzzy and "no exact match" in fuzzy
    out = "\n".join(index.query_file(project, "src/utils/math.ts"))
    assert "Imported by 3 files" in out and "Tests: src/utils/math.spec.ts" in out
    assert "not in the index" in index.query_file(project, "nope.ts")[0]
    assert len(index.query_symbol(project, "add")) <= index.QUERY_LINES


def test_incremental_update_parses_only_changes(project, repo):
    make_app(repo)
    index.update(project)
    assert index.update(project)["parsed"] == 0
    f = repo / "src" / "utils" / "math.ts"
    f.write_text(f.read_text() + "export function sub(a: number, b: number) { return a - b }\n")
    os.utime(str(f), (time.time() + 5, time.time() + 5))
    (repo / "app" / "views.py").unlink()
    write(repo, "src/new.ts", "export class Fresh {}\n")  # untracked files count too
    st = index.update(project)
    assert st["parsed"] == 2 and st["removed"] == 1
    assert "function sub" in "\n".join(index.query_symbol(project, "sub"))
    assert "class Fresh" in "\n".join(index.query_symbol(project, "Fresh"))
    con = index.connect(project)
    assert index.dependents(con, "app/models.py") == []
    con.close()


def test_touch_without_change_is_cheap(project, repo):
    make_app(repo)
    index.update(project)
    f = repo / "app" / "models.py"
    os.utime(str(f), (time.time() + 10, time.time() + 10))
    assert index.update(project)["parsed"] == 0  # same hash: only mtime refreshed


def test_status_and_languages(project, repo):
    assert "not built yet" in index.status(project)[0]
    make_app(repo)
    index.update(project)
    s = "\n".join(index.status(project))
    assert "7 files" in s and "regex" in s
    assert index.languages(project)["typescript"] == 3


def test_lock_held_returns_none(project, repo):
    from uccif_lib.paths import file_lock
    make_app(repo)
    with file_lock(index.db_path(project).with_name("index.lock")):
        assert index.update(project, wait=0.1) is None


def test_non_git_dir_is_indexed(tmp_path, monkeypatch):
    from uccif_lib import paths
    d = tmp_path / "plain"
    write(d, "main.py", "def run():\n    pass\n")
    monkeypatch.chdir(d)
    p = paths.resolve_project()
    assert index.update(p)["parsed"] == 1
    assert "main.py:1  function run" in "\n".join(index.query_symbol(p, "run"))


def test_targeted_update_only_touches_given_files(project, repo):
    make_app(repo)
    index.update(project)
    f = repo / "app" / "models.py"
    f.write_text(f.read_text() + "def extra():\n    pass\n")
    os.utime(str(f), (time.time() + 5, time.time() + 5))
    write(repo, "src/other.ts", "export function other() {}\n")  # not passed: not indexed yet
    st = index.update(project, paths=["app/models.py", "README.md"])
    assert st["parsed"] == 1 and st["removed"] == 0
    assert "function extra" in "\n".join(index.query_symbol(project, "extra"))
    assert "none in index" in "\n".join(index.query_symbol(project, "other"))
    (repo / "app" / "models.py").unlink()
    assert index.update(project, paths=["app/models.py"])["removed"] == 1


def test_queries_work_when_data_dir_is_read_only(project, repo, monkeypatch, capsys):
    """Claude Code's Bash sandbox denies writes under ~/.claude: queries must still answer."""
    import stat
    from uccif_lib import cli
    make_app(repo)
    index.update(project)
    dirs = [project.data_dir, index.db_path(project).parent]
    files = list(index.db_path(project).parent.iterdir())
    try:
        for f in files:
            os.chmod(str(f), stat.S_IRUSR)
        for d in dirs:
            os.chmod(str(d), stat.S_IRUSR | stat.S_IXUSR)
        if os.access(str(index.db_path(project).parent), os.W_OK):
            import pytest
            pytest.skip("running as a user that ignores file permissions")
        assert cli.main(["index", "query", "--symbol", "add"]) == 0
        assert "src/utils/math.ts:1  function add" in capsys.readouterr().out
        assert cli.main(["index", "status"]) == 0
        assert cli.main(["index", "update"]) == 0
        assert "sandbox" in capsys.readouterr().out
        assert cli.main(["task", "start", "x", "--type", "ui"]) == 0  # task state lives in the repo
    finally:
        for d in dirs:
            os.chmod(str(d), stat.S_IRWXU)
        for f in files:
            os.chmod(str(f), stat.S_IRUSR | stat.S_IWUSR)


def test_query_before_build_says_so(project, repo, capsys):
    from uccif_lib import index as I
    assert "not built yet" in "\n".join(I.status(project))


# ---- tree-sitter (optional) ------------------------------------------------------

def _ts_or_skip(monkeypatch):
    import pytest
    monkeypatch.delenv("UCCIF_NO_TREE_SITTER", raising=False)
    from uccif_lib import ts_parse
    if not all(ts_parse.availability().values()):
        pytest.skip("tree-sitter packages not installed")


def test_without_tree_sitter_status_says_regex(project, repo):
    make_app(repo)
    index.update(project)
    con = index.connect(project)
    assert {r[0] for r in con.execute("SELECT DISTINCT precision FROM symbols")} <= {"approx", "ctags"}
    con.close()
    assert "from: regex" in "\n".join(index.status(project)) or "ctags" in "\n".join(index.status(project))


def test_tree_sitter_extracts_same_symbols_as_regex(project, repo, monkeypatch):
    _ts_or_skip(monkeypatch)
    make_app(repo)
    index.update(project)
    con = index.connect(project)
    syms = {(n, k) for n, k in con.execute("SELECT name, kind FROM symbols")}
    for expected in [("add", "function"), ("double", "function"), ("Point", "interface"),
                     ("useCart", "store"), ("refresh", "function"), ("Cart", "component"),
                     ("Order", "class"), ("total", "method"), ("MAX_ITEMS", "constant"),
                     ("helper", "function")]:
        assert expected in syms, expected
    assert {r[0] for r in con.execute("SELECT precision FROM symbols WHERE path='src/utils/math.ts'")} == {"ast"}
    assert {r[0] for r in con.execute("SELECT precision FROM symbols WHERE path='src/styles/tokens.css'")} == {"approx"}
    assert set(index.dependents(con, "src/utils/math.ts")) == {
        "src/components/Cart.vue", "src/stores/cart.ts", "src/utils/math.spec.ts"}
    assert index.dependents(con, "app/models.py") == ["app/views.py"]
    line = con.execute("SELECT line FROM symbols WHERE name='refresh'").fetchone()[0]
    assert line == 5  # Vue script keeps real file line numbers
    con.close()
    assert "tree-sitter" in "\n".join(index.status(project))


def test_tree_sitter_finer_cases(project, repo, monkeypatch):
    _ts_or_skip(monkeypatch)
    write(repo, "a.ts",
          "import x, { y as z } from './b'\nexport * from './c'\nconst m = require('./d')\n"
          "const lazy = () => import('./e')\n"
          "export abstract class Svc<T> {\n  private count = 0\n  async run(): Promise<void> {}\n"
          "  handler = () => 1\n}\nexport enum Mode { A }\nexport type Id = string\n")
    write(repo, "b.ts", "export const y = 1\n")
    write(repo, "c.ts", "")
    write(repo, "d.ts", "")
    write(repo, "e.ts", "")
    write(repo, "p.py", "import os, sys as s\nfrom . import q\nclass A:\n    async def m(self):\n        def inner(): pass\n")
    write(repo, "q.py", "")
    index.update(project)
    con = index.connect(project)
    got = {(n, k, sc) for n, k, sc in con.execute("SELECT name, kind, scope FROM symbols WHERE path='a.ts'")}
    for e in [("Svc", "class", None), ("run", "method", "Svc"), ("handler", "method", "Svc"),
              ("Mode", "enum", None), ("Id", "type", None), ("lazy", "function", None)]:
        assert e in got, e
    assert {t for (t,) in con.execute("SELECT target FROM imports WHERE src='a.ts'")} == {
        "b.ts", "c.ts", "d.ts", "e.ts"}
    py = {(n, k, sc) for n, k, sc in con.execute("SELECT name, kind, scope FROM symbols WHERE path='p.py'")}
    assert ("m", "method", "A") in py and ("inner", "function", None) in py
    assert {r for (r,) in con.execute("SELECT raw FROM imports WHERE src='p.py'")} == {"os", "sys", "."}
    con.close()


def test_broken_source_still_indexes(project, repo, monkeypatch):
    _ts_or_skip(monkeypatch)
    write(repo, "bad.ts", "export function ok() {}\nfunction (((\n")
    index.update(project)
    assert "function ok" in "\n".join(index.query_symbol(project, "ok"))


# ---- call graph (needs tree-sitter) ---------------------------------------------

def make_calls(repo):
    write(repo, "src/math.ts", "export function add(a: number, b: number) { return a + b }\n"
                               "export function twice(x: number) { return add(x, x) }\n")
    write(repo, "src/use.ts",
          "import { add as plus } from './math'\nimport * as m from './math'\n"
          "export function total() { return plus(1, 2) }\n"
          "export class Cart {\n  sum() { return m.add(1, 1) + this.helper() }\n  helper() { return store.add(3) }\n}\n")
    write(repo, "svc.py", "from .lib import work as w\nimport lib\n\n"
                           "class S:\n    def run(self):\n        w()\n        self.step()\n        lib.work()\n"
                           "    def step(self):\n        pass\n")
    write(repo, "lib.py", "def work():\n    pass\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "calls")


def test_calls_are_resolved_through_imports(project, repo, monkeypatch):
    _ts_or_skip(monkeypatch)
    make_calls(repo)
    index.update(project)
    con = index.connect(project)
    got = set(con.execute("SELECT src_path, src_symbol, callee_name, callee_path, line FROM calls"))
    con.close()
    assert ("src/math.ts", "twice", "add", "src/math.ts", 2) in got        # same-file call
    assert ("src/use.ts", "total", "add", "src/math.ts", 3) in got         # alias: plus -> add
    assert ("src/use.ts", "Cart.sum", "add", "src/math.ts", 5) in got      # namespace m.add
    assert ("src/use.ts", "Cart.sum", "helper", "src/use.ts", 5) in got    # this.helper()
    assert ("src/use.ts", "Cart.helper", "add", None, 6) in got            # store.add: unresolved
    assert ("svc.py", "S.run", "work", "lib.py", 6) in got                 # from .lib import work as w
    assert ("svc.py", "S.run", "step", "svc.py", 7) in got                 # self.step()
    assert ("svc.py", "S.run", "work", "lib.py", 8) in got                 # lib.work()


def test_query_symbol_shows_callers_within_limit(project, repo, monkeypatch):
    _ts_or_skip(monkeypatch)
    make_calls(repo)
    index.update(project)
    out = index.query_symbol(project, "add")
    text = "\n".join(out)
    assert "Called by (3):" in text and "src/use.ts:3 in total" in text and "src/math.ts:2 in twice" in text
    assert "Possibly called by (receiver unresolved) (1):" in text and "src/use.ts:6 in Cart.helper" in text
    assert len(out) <= index.QUERY_LINES
    assert "8 call edges (7 resolved)" in "\n".join(index.status(project))
    assert "Called by" not in "\n".join(index.query_symbol(project, "total"))  # nobody calls it


def test_many_callers_are_capped(project, repo, monkeypatch):
    _ts_or_skip(monkeypatch)
    write(repo, "core.ts", "export function hot() {}\n")
    for i in range(20):
        write(repo, "u%d.ts" % i, "import { hot } from './core'\nexport function f%d() { hot() }\n" % i)
    index.update(project)
    out = index.query_symbol(project, "hot")
    assert len(out) <= index.QUERY_LINES
    assert any("Called by (20):" in l for l in out) and any("+12 more" in l for l in out)


def test_no_tree_sitter_means_no_call_edges(project, repo):
    make_calls(repo)
    index.update(project)
    con = index.connect(project)
    assert con.execute("SELECT count(*) FROM calls").fetchone()[0] == 0
    con.close()
    out = "\n".join(index.query_symbol(project, "add"))
    assert "Called by" not in out and "Referenced (whole word)" in out


def test_calls_dropped_with_file_and_schema_upgrade(project, repo, monkeypatch):
    _ts_or_skip(monkeypatch)
    make_calls(repo)
    index.update(project)
    (repo / "src" / "use.ts").unlink()
    index.update(project)
    con = index.connect(project)
    assert con.execute("SELECT count(*) FROM calls WHERE src_path='src/use.ts'").fetchone()[0] == 0
    con.execute("UPDATE meta SET value='1' WHERE key='schema'")  # pretend an old index
    con.commit()
    con.close()
    con = index.connect(project)  # writer notices the schema change and clears everything
    assert con.execute("SELECT count(*) FROM files").fetchone()[0] == 0
    con.close()
    assert index.update(project)["parsed"] > 0
