"""CSS variables (D3) and classes (D4)."""
import os
import time

import pytest

from conftest import git
from uccif_lib import index, styles, ts_parse


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


def _html(monkeypatch):
    monkeypatch.delenv("UCCIF_NO_TREE_SITTER", raising=False)
    if not (any(ts_parse.availability().values()) and ts_parse.html_available()):
        pytest.skip("tree-sitter / tree-sitter-html not installed")


def test_selector_and_var_parsing():
    css = (":root { --a: 1; }\n/* .no {} */\n.btn, .card:hover > .title[data-x='.y'] { color: var(--a); }\n"
           "@media (max-width: 10px) { .m { x: 1 } }\n.a { .b { c: d } }\n.n { w: 0.5s; u: url(a.png) }\n")
    syms, scoped = styles.symbols(css, "scss")
    assert [(n, ln) for n, k, ln, _ in syms] == [("btn", 3), ("card", 3), ("title", 3), ("m", 4), ("a", 5),
                                                 ("b", 5), ("n", 6)]
    assert scoped == set()
    assert styles.uses(css, "scss") == [("var", "--a", 3)]
    vue = "<template><b /></template>\n<style scoped>\n.x { --local: 1; color: var(--local) }\n</style>\n"
    syms, scoped = styles.symbols(vue, "vue")
    assert ("--local", "css-var", 3, None) in syms and ("x", "css-class", 3, None) in syms and scoped == {"x"}
    js = "el.style.setProperty('--x', c)\ngetComputedStyle(d).getPropertyValue('--y')\n"
    assert styles.uses(js, "typescript") == [("define", "--x", 1), ("read", "--y", 2)]


def test_css_var_edges_without_tree_sitter(project, vue_app):
    index.update(project)  # regex only: CSS variables still work
    got = {(e[6], e[5]): e for e in edges(project, kind="uses_css_var")}
    e = got[("src/components/BaseButton.vue", "--brand-color")]
    assert e[1] == "src/styles/tokens.css#--brand-color" and e[4] == "extracted" and e[3] == 11
    assert e[0] == "src/components/BaseButton.vue#BaseButton"
    assert ("src/components/ExpenseList.vue", "--text") in got
    out = "\n".join(index.impact(project, "src/styles/tokens.css"))
    assert "src/components/BaseButton.vue:11  uses CSS variable --brand-color at :11" in out
    sym = "\n".join(index.query_symbol(project, "--brand-color"))
    assert "Used by (3):" in sym


def test_runtime_and_unknown_vars(project, repo):
    write(repo, "theme.css", ":root {\n  --brand: red;\n}\n.dark {\n  --brand: blue;\n}\n")
    write(repo, "a.ts", "export function t(el: HTMLElement) {\n  el.style.setProperty('--brand', 'x')\n"
          "  return 'color: var(--lib-color)'\n}\n")
    commit(repo)
    index.update(project)
    d = edges(project, kind="defines_css_var")
    assert {e[1] for e in d} == {"theme.css#--brand"} and d[0][3] == 2  # one node per file (first definition)
    u = [e for e in edges(project, kind="uses_css_var") if e[5] == "--lib-color"]
    assert u and u[0][4] == "unresolved" and u[0][1] is None  # a library's variable: a lead


def test_template_classes(project, repo, monkeypatch):
    _html(monkeypatch)
    write(repo, "src/global.css", ".card { a: b }\n.btn { c: d }\n")
    write(repo, "src/A.vue", "<template>\n  <div class=\"card mx-4\" :class=\"{ active: on, 'is-big': big }, ['btn']\">"
          "</div>\n</template>\n<style scoped>\n.active { x: y }\n.card { z: w }\n</style>\n")
    write(repo, "src/B.vue", "<template>\n  <p class=\"active\" />\n</template>\n<style scoped>\n.only-b { q: r }\n"
          "</style>\n")
    commit(repo)
    index.update(project)
    a = {(e[5], e[7]) for e in edges(project, kind="uses_class", src_path="src/A.vue")}
    assert ("card", "src/A.vue") in a and ("card", "src/global.css") not in a  # own <style> wins
    assert ("active", "src/A.vue") in a and ("btn", "src/global.css") in a
    assert not [x for x in a if x[0] in ("mx-4", "is-big")]  # no selector: nothing
    b = edges(project, kind="uses_class", src_path="src/B.vue")
    assert not b  # `.active` exists only in A's scoped style, which cannot style B
    assert all(e[4] == "inferred" for e in edges(project, kind="uses_class"))
    con = index.connect(project, write=False)
    assert con.execute("SELECT detail FROM nodes WHERE id='src/A.vue#css-class:active'").fetchone()[0] == "scoped"


def test_css_edges_follow_updates(project, vue_app):
    index.update(project)
    f = vue_app / "src" / "styles" / "tokens.css"
    f.write_text(f.read_text().replace("--brand-color", "--brand"), encoding="utf-8")
    os.utime(str(f), (time.time() + 10, time.time() + 10))
    index.update(project)
    e = [x for x in edges(project, kind="uses_css_var") if x[5] == "--brand-color"]
    assert e and all(x[4] == "unresolved" and x[1] is None for x in e)  # renamed variable: users become leads
