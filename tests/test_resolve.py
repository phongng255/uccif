"""Import resolution: config-driven JS aliases (C5), barrels (A2), Python package roots (C4)."""
import os
import time

import pytest

from conftest import git
from uccif_lib import index, ts_parse
from uccif_lib.resolve import Resolver, _loose_json


def write(root, rel, text):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def commit(repo):
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "x")


def _ts(monkeypatch):
    monkeypatch.delenv("UCCIF_NO_TREE_SITTER", raising=False)
    if not any(ts_parse.availability().values()):
        pytest.skip("tree-sitter not installed")


def test_loose_json_accepts_comments_and_trailing_commas():
    d = _loose_json('{\n // c\n "a": "http://x", /* b */ "p": {"@/*": ["src/*",],},\n}')
    assert d == {"a": "http://x", "p": {"@/*": ["src/*"]}}


def test_tsconfig_paths_and_extends(tmp_path):
    write(tmp_path, "tsconfig.base.json", '{"compilerOptions": {"baseUrl": ".", "paths": {"#lib/*": ["packages/lib/*"]}}}')
    write(tmp_path, "tsconfig.json", '{ "extends": "./tsconfig.base.json", // base\n'
          ' "compilerOptions": {"paths": {"@app/*": ["web/src/*"], "cfg": ["config/index.ts"]}} }')
    files = ["packages/lib/a.ts", "web/src/b.vue", "config/index.ts", "main.ts"]
    r = Resolver(files, tmp_path)
    assert r.resolve("main.ts", "#lib/a", "typescript") == "packages/lib/a.ts"
    assert r.resolve("main.ts", "@app/b.vue", "typescript") == "web/src/b.vue"
    assert r.resolve("main.ts", "cfg", "typescript") == "config/index.ts"
    assert r.resolve("main.ts", "cfgx", "typescript") is None
    assert r.resolve("main.ts", "vue", "typescript") is None
    assert r.internal("#lib/zzz", "typescript", "main.ts") and not r.internal("vue", "typescript", "main.ts")


def test_vite_alias_forms(tmp_path):
    write(tmp_path, "app/package.json", "{}")
    write(tmp_path, "app/vite.config.ts", "import path from 'path'\nexport default {\n resolve: { alias: {\n"
          "  '@': fileURLToPath(new URL('./client', import.meta.url)),\n"
          "  '~shared': path.resolve(__dirname, 'shared'),\n }}}\n")
    write(tmp_path, "b/vite.config.js", "export default { resolve: { alias: [{ find: '@', replacement: '/web' }] } }")
    files = ["app/client/x.ts", "app/shared/y.ts", "app/main.ts", "b/web/z.ts", "b/main.ts", "src/q.ts", "root.ts"]
    r = Resolver(files, tmp_path)
    assert r.resolve("app/main.ts", "@/x", "typescript") == "app/client/x.ts"
    assert r.resolve("app/main.ts", "~shared/y", "typescript") == "app/shared/y.ts"
    assert r.resolve("b/main.ts", "@/z", "typescript") == "b/web/z.ts"
    assert r.resolve("root.ts", "@/q", "typescript") == "src/q.ts"  # default @/ -> src/ without config


def test_nested_project_keeps_own_alias(tmp_path):
    write(tmp_path, "package.json", "{}")
    write(tmp_path, "fixtures/app/package.json", "{}")
    files = ["src/a.ts", "fixtures/app/src/a.ts", "fixtures/app/src/main.ts", "main.ts"]
    r = Resolver(files, tmp_path)
    assert r.resolve("fixtures/app/src/main.ts", "@/a", "typescript") == "fixtures/app/src/a.ts"
    assert r.resolve("main.ts", "@/a", "typescript") == "src/a.ts"


def test_python_roots(tmp_path):
    write(tmp_path, "pyproject.toml", '[tool.setuptools]\npackage-dir = {"" = "code"}\n')
    files = ["code/mod.py", "plugins/x/pkg/__init__.py", "plugins/x/pkg/core.py", "tests/conftest.py",
             "tests/test_a.py"]
    r = Resolver(files, tmp_path)
    assert r.resolve("tests/test_a.py", "mod", "python") == "code/mod.py"  # pyproject package-dir
    assert r.resolve("tests/test_a.py", "pkg.core", "python") == "plugins/x/pkg/core.py"  # top-level package
    assert r.resolve("tests/test_a.py", "conftest", "python") == "tests/conftest.py"  # sibling module
    assert r.resolve("tests/test_a.py", "os", "python") is None


def test_impact_through_barrel_shows_via(project, vue_app):
    index.update(project)
    out = "\n".join(index.impact(project, "src/utils/id.ts"))
    assert "src/components/ExpenseForm.vue:" in out and "via src/utils/index.ts" in out


def test_barrel_edges_follow_updates(project, vue_app):
    index.update(project)
    barrel = vue_app / "src" / "utils" / "index.ts"
    barrel.write_text("export * from './format'\nexport { sumAmounts } from './math'\n", encoding="utf-8")
    os.utime(str(barrel), (time.time() + 10, time.time() + 10))
    index.update(project, paths=["src/utils/index.ts"])  # what the post-Edit hook does
    con = index.connect(project, write=False)
    assert "src/components/ExpenseForm.vue" not in index.dependents(con, "src/utils/id.ts")
    assert "src/components/ExpenseList.vue" in index.dependents(con, "src/utils/format.ts")
    con.close()
    (vue_app / "src" / "utils" / "format.ts").unlink()
    index.update(project)
    con = index.connect(project, write=False)
    assert not con.execute("SELECT 1 FROM edges WHERE dst_path='src/utils/format.ts'").fetchone()


def test_barrel_calls_point_at_definition(project, vue_app, monkeypatch):
    _ts(monkeypatch)
    index.update(project)
    con = index.connect(project, write=False)
    rows = con.execute("SELECT dst_id, via FROM edges WHERE kind='calls' AND src_path='src/composables/useMoney.ts' "
                       "AND detail='formatMoney'").fetchall()
    assert ("src/utils/format.ts#formatMoney", "src/utils/index.ts") in rows
    out = "\n".join(index.query_symbol(project, "formatMoney"))
    assert "Called by" in out and "src/composables/useMoney.ts" in out


def test_python_package_init_reexports(project, repo):
    write(repo, "shop/__init__.py", "from .models import Order\nfrom .util import *\n")
    write(repo, "shop/models.py", "class Order:\n    pass\n")
    write(repo, "shop/util.py", "def money():\n    pass\n")
    write(repo, "main.py", "from shop import Order, money\n")
    commit(repo)
    index.update(project)
    con = index.connect(project, write=False)
    assert "main.py" in index.dependents(con, "shop/models.py")
    assert "main.py" in index.dependents(con, "shop/util.py")
