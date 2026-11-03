"""Props and emits of Vue components (roadmap B2): nodes, `emits`, `passes_prop`, `listens`."""
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


def test_all_declaration_forms(monkeypatch):
    _ts(monkeypatch)
    code = '''interface Props { title: string; count?: number }
const p = withDefaults(defineProps<Props>(), { count: 1 })
defineProps<{ a: string }>()
defineProps({ b: String, c: { type: Number } })
defineProps(['d', 'e'])
const emit = defineEmits<{ (e: 'toggle-theme'): void; (e: 'save', x: number): void; 'plain': [v: string] }>()
defineEmits(['f'])
function go() { emit('save', 1); t('not-an-emit') }
export default { props: { z: String }, emits: ['y'] }
'''
    r = ts_parse.parse(code, "a.ts", "typescript")
    got = sorted((s[1], s[0]) for s in r[0] if s[1] in ("prop", "emit"))
    assert got == sorted([("prop", n) for n in "title count a b c d e z".split()]
                         + [("emit", n) for n in ("toggle-theme", "save", "plain", "f", "y")])
    assert r[9] == [("go", "save", 8)]


def test_nodes_ids_and_scope(project, vue_app, monkeypatch):
    _ts(monkeypatch)
    index.update(project)
    con = index.connect(project, write=False)
    rows = {r[0]: r[1:] for r in con.execute("SELECT id, kind, name, scope FROM nodes WHERE kind IN ('prop','emit')")}
    a = "src/components/AppHeader.vue#AppHeader."
    assert rows[a + "prop:title"] == ("prop", "title", "AppHeader")
    assert rows[a + "emit:toggle-theme"] == ("emit", "toggle-theme", "AppHeader")
    c = {(e[0], e[1]) for e in edges(project, kind="contains", src_path="src/components/AppHeader.vue")}
    assert ("src/components/AppHeader.vue#AppHeader", a + "prop:title") in c
    assert "prop title in AppHeader" in "\n".join(index.query_symbol(project, "title"))


def test_emit_calls_script_and_template(project, vue_app, monkeypatch):
    _html(monkeypatch)
    index.update(project)
    e = {(x[6], x[5]): x for x in edges(project, kind="emits")}
    sc = e[("src/components/ExpenseForm.vue", "save")]  # emit('save', ...) in submit()
    assert sc[0] == "src/components/ExpenseForm.vue#submit" and sc[1].endswith("ExpenseForm.emit:save")
    assert sc[4] == "extracted" and sc[3] == 19
    tp = e[("src/components/ExpenseItem.vue", "remove")]  # $emit('remove', id) in the template
    assert tp[0] == "src/components/ExpenseItem.vue#ExpenseItem" and tp[3] == 5
    assert e[("src/components/AppHeader.vue", "toggle-theme")][4] == "extracted"
    assert not [x for x in edges(project, kind="calls", confidence="unresolved") if x[5] == "emit"]


def test_parent_passes_props_and_listens(project, vue_app, monkeypatch):
    _html(monkeypatch)
    index.update(project)
    got = {(x[6], x[2], x[5]): x for x in edges(project, via="~link")}
    p = got[("src/components/ExpenseList.vue", "passes_prop", "expense")]
    assert p[0] == "src/components/ExpenseList.vue#ExpenseList" and p[3] == 3
    assert p[1] == "src/components/ExpenseItem.vue#ExpenseItem.prop:expense" and p[4] == "extracted"
    assert got[("src/components/ExpenseList.vue", "listens", "remove")][1].endswith("ExpenseItem.emit:remove")
    assert got[("src/components/ExpenseList.vue", "listens", "save")][1].endswith("ExpenseForm.emit:save")
    assert got[("src/App.vue", "passes_prop", "title")][1].endswith("AppHeader.prop:title")
    assert got[("src/App.vue", "listens", "toggle-theme")][1].endswith("AppHeader.emit:toggle-theme")
    # through the global BaseButton registration too
    assert got[("src/App.vue", "passes_prop", "label")][1].endswith("BaseButton.prop:label")
    # `:key=` / `class=` / `v-for` are not props
    assert not [k for k in got if k[2] in ("key", "class", "v-for")]


def test_name_styles_and_undeclared(project, repo, monkeypatch):
    _html(monkeypatch)
    write(repo, "src/Card.vue", "<template><div /></template>\n<script setup lang=\"ts\">\n"
          "defineProps<{ cardTitle: string; modelValue: string }>()\n"
          "defineEmits<{ (e: 'item-click'): void; (e: 'update:modelValue', v: string): void }>()\n</script>\n")
    write(repo, "src/Page.vue", "<template>\n  <Card card-title=\"x\" :extra=\"1\" class=\"c\" @item-click=\"a\" @native=\"b\""
          " v-model=\"v\" />\n</template>\n<script setup lang=\"ts\">\nimport Card from './Card.vue'\n</script>\n")
    commit(repo)
    index.update(project)
    got = {(x[2], x[5]): x for x in edges(project, via="~link")}
    assert got[("passes_prop", "card-title")][1].endswith("Card.prop:cardTitle")  # kebab-case -> camelCase
    assert got[("listens", "item-click")][1].endswith("Card.emit:item-click")
    assert got[("passes_prop", "modelValue")][1].endswith("Card.prop:modelValue")  # v-model
    assert got[("listens", "update:modelValue")][1].endswith("Card.emit:update:modelValue")
    assert ("passes_prop", "extra") not in got and ("listens", "native") not in got  # not declared by Card


def test_symbol_query_shows_users(project, vue_app, monkeypatch):
    _html(monkeypatch)
    index.update(project)
    out = index.query_symbol(project, "title")
    text = "\n".join(out)
    assert "Used by (1):" in text and "src/App.vue:3 in App  (passes prop)" in text
    ev = "\n".join(index.query_symbol(project, "toggle-theme"))
    assert "Used by (2):" in ev and "(listens)" in ev and "(emits)" in ev
    assert all(len(index.query_symbol(project, n)) <= index.QUERY_LINES for n in ("title", "remove", "save"))


def test_links_follow_updates(project, vue_app, monkeypatch):
    _html(monkeypatch)
    index.update(project)
    f = vue_app / "src" / "components" / "AppHeader.vue"
    f.write_text(f.read_text().replace("title: string", "heading: string"), encoding="utf-8")
    os.utime(str(f), (time.time() + 10, time.time() + 10))
    index.update(project)
    got = {(x[6], x[2], x[5]) for x in edges(project, via="~link")}
    assert ("src/App.vue", "passes_prop", "title") not in got  # prop renamed: no stale link
    (vue_app / "src" / "components" / "ExpenseItem.vue").unlink()
    index.update(project)
    con = index.connect(project, write=False)
    ids = {r[0] for r in con.execute("SELECT id FROM nodes")}
    assert all(e[1] in ids for e in edges(project) if e[1])


def test_without_html_grammar_no_links(project, vue_app, monkeypatch):
    _ts(monkeypatch)
    monkeypatch.setattr(ts_parse, "html_available", lambda: False)
    index.update(project)
    assert not edges(project, via="~link")
    assert {x[6] for x in edges(project, kind="emits")} == {"src/components/ExpenseForm.vue"}  # script emit still seen
