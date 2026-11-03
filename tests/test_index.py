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
