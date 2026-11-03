"""Vue templates: `renders` edges (B1) and functions called from the template (B6)."""
import os
import time

import pytest

from conftest import git
from uccif_lib import index, ts_parse, vue_template


def _html(monkeypatch):
    monkeypatch.delenv("UCCIF_NO_TREE_SITTER", raising=False)
    if not (any(ts_parse.availability().values()) and ts_parse.html_available()):
        pytest.skip("tree-sitter / tree-sitter-html not installed")


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


def touch(path, text):
    path.write_text(text, encoding="utf-8")
    os.utime(str(path), (time.time() + 10, time.time() + 10))


def test_parse_tags_and_calls(monkeypatch):
    _html(monkeypatch)
    t = vue_template.parse(
        '<template>\n  <div @click="a(); b.c()" :x="{ k: f(1) }">\n    <ExpenseItem v-for="(e, i) in items()" '
        '@remove="rm" />\n    <my-widget v-if="ok(z)">{{ fmt(n) }}\n and {{ $t("k") }}</my-widget>\n'
        '    <router-link to="/">go</router-link><span>x</span><component :is="d" />\n  </div>\n</template>\n')
    assert [x[0] for x in t.tags] == ["ExpenseItem", "my-widget", "router-link", "component"]
    got = {(n, o, ln) for n, o, ln in t.calls}
    assert got == {("a", None, 2), ("c", "b", 2), ("f", None, 2), ("items", None, 3), ("rm", None, 3),
                   ("ok", None, 4), ("fmt", None, 4)}  # $t is Vue's own; second {{ }} is on the next line


def test_pug_and_missing_template_are_skipped(monkeypatch):
    _html(monkeypatch)
    assert vue_template.parse("<script setup>\nconst a = 1\n</script>\n") is None
    assert vue_template.parse('<template lang="pug">\ndiv\n</template>\n') is None


def test_renders_edges_on_fixture(project, vue_app, monkeypatch):
    _html(monkeypatch)
    index.update(project)
    got = {(e[6], e[5]): e for e in edges(project) if e[2] in ("renders", "renders_ext")}
    local = got[("src/components/ExpenseList.vue", "ExpenseItem")]
    assert (local[0], local[1], local[4], local[3], local[8]) == (
        "src/components/ExpenseList.vue#ExpenseList", "src/components/ExpenseItem.vue#ExpenseItem",
        "extracted", 3, None)  # imported in <script setup>
    glob = got[("src/components/ExpenseItem.vue", "BaseButton")]
    assert glob[1] == "src/components/BaseButton.vue#BaseButton" and glob[4] == "extracted"
    assert glob[8] == "~global" and glob[7] == "src/components/BaseButton.vue"  # app.component in main.ts
    assert got[("src/App.vue", "RouterView")][2] == "renders_ext"  # vue-router built-in
    assert not [e for e in edges(project, kind="renders") if e[4] == "unresolved"]


def test_template_calls_use_script_bindings(project, vue_app, monkeypatch):
    _html(monkeypatch)
    index.update(project)
    calls = {(e[6], e[5], e[3]): e for e in edges(project, kind="calls") if e[6].endswith(".vue")}
    fmt = calls[("src/components/ExpenseItem.vue", "formatMoney", 4)]
    assert fmt[0] == "src/components/ExpenseItem.vue#ExpenseItem"  # the template belongs to the component
    assert fmt[1] == "src/utils/format.ts#formatMoney" and fmt[4] == "extracted"
    sel = calls[("src/App.vue", "select", 5)]
    assert sel[1] == "src/App.vue#select"  # function declared in <script setup>
    rm = calls[("src/components/ExpenseList.vue", "remove", 3)]  # @remove="remove": bare handler is a call
    assert rm[1] == "src/components/ExpenseList.vue#remove"
    assert ("src/App.vue", "toggle", 3) not in calls  # `ui.toggle()` is a store action now (see test_pinia)


def test_impact_sees_global_components_and_barrel_users(project, vue_app, monkeypatch):
    _html(monkeypatch)
    index.update(project)
    out = "\n".join(index.impact(project, "src/components/BaseButton.vue"))
    assert "src/components/ExpenseForm.vue:5" in out and "renders <BaseButton> at :5, global registration" in out
    sym = "\n".join(index.query_symbol(project, "BaseButton"))
    assert "Rendered by (" in sym and "src/components/AppHeader.vue:4  AppHeader" in sym
    comp = "\n".join(index.query_symbol(project, "ExpenseList"))
    assert "Renders (2):" in comp and "<ExpenseItem>  src/components/ExpenseItem.vue" in comp
    assert len(index.query_symbol(project, "ExpenseList")) <= index.QUERY_LINES


def test_name_match_is_inferred_and_unknown_is_unresolved(project, repo, monkeypatch):
    _html(monkeypatch)
    write(repo, "src/Page.vue", "<template><my-card /><GhostThing /><Page /></template>\n"
          "<script setup lang=\"ts\">\n</script>\n")
    write(repo, "src/ui/MyCard.vue", "<template><b /></template>\n")
    commit(repo)
    index.update(project)
    rows = {e[5]: e for e in edges(project, kind="renders")}
    assert rows["my-card"][4] == "inferred" and rows["my-card"][7] == "src/ui/MyCard.vue"
    assert rows["my-card"][8] == "~name"
    assert rows["GhostThing"][4] == "unresolved" and rows["GhostThing"][1] is None
    assert rows["Page"][4] == "unresolved"  # a component never "renders" itself by file name
    # ambiguity is not guessed
    write(repo, "src/other/MyCard.vue", "<template><i /></template>\n")
    index.update(project)
    assert {e[5]: e for e in edges(project, kind="renders")}["my-card"][4] == "unresolved"


def test_derived_renders_follow_updates(project, vue_app, monkeypatch):
    _html(monkeypatch)
    index.update(project)
    main = vue_app / "src" / "main.ts"
    touch(main, main.read_text().replace("app.component('BaseButton', BaseButton)\n", ""))
    index.update(project)
    row = [e for e in edges(project, kind="renders", src_path="src/components/ExpenseItem.vue")
           if e[5] == "BaseButton"][0]
    assert row[4] == "inferred" and row[8] == "~name"  # registration gone: falls back to the file name
    (vue_app / "src" / "components" / "BaseButton.vue").unlink()
    index.update(project)
    rows = [e for e in edges(project, kind="renders", src_path="src/components/ExpenseItem.vue")
            if e[5] == "BaseButton"]
    assert len(rows) == 1 and rows[0][4] == "unresolved" and rows[0][1] is None  # no dangling target
    con = index.connect(project, write=False)
    ids = {r[0] for r in con.execute("SELECT id FROM nodes")}
    assert all(e[1] in ids for e in edges(project) if e[1])


def test_without_html_grammar_nothing_changes(project, vue_app, monkeypatch):
    monkeypatch.delenv("UCCIF_NO_TREE_SITTER", raising=False)
    if not any(ts_parse.availability().values()):
        pytest.skip("tree-sitter not installed")
    monkeypatch.setattr(ts_parse, "html_available", lambda: False)
    index.update(project)
    assert not edges(project, kind="renders")
    assert not [e for e in edges(project, kind="calls") if e[6].endswith(".vue") and e[3] and e[5] == "remove"]
    con = index.connect(project, write=False)
    assert con.execute("SELECT count(*) FROM tags").fetchone()[0] == 0
