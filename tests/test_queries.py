"""New graph queries (step 12): symbol impact, --kinds / --min-confidence, component, store, route,
css var, cochange. All read-only and within QUERY_LINES."""
import pytest

from conftest import git
from uccif_lib import cli, index, queries, ts_parse


def _html(monkeypatch):
    monkeypatch.delenv("UCCIF_NO_TREE_SITTER", raising=False)
    if not (any(ts_parse.availability().values()) and ts_parse.html_available()):
        pytest.skip("tree-sitter / tree-sitter-html not installed")


def run(capsys, *args):
    assert cli.main(["index", "query"] + list(args)) == 0
    return capsys.readouterr().out


def test_parse_kinds():
    assert queries.parse_kinds("calls,store") == ("calls", "calls_action", "reads_state", "uses_store")
    assert queries.parse_kinds("") is None
    with pytest.raises(ValueError) as e:
        queries.parse_kinds("calls,nope")
    assert "nope" in str(e.value) and "groups:" in str(e.value)


def test_impact_of_a_symbol(project, vue_app, monkeypatch, capsys):
    _html(monkeypatch)
    out = run(capsys, "--impact", "addExpense")
    assert "Impact of addExpense" in out and "defined at src/stores/trip.ts:11 (store_member)" in out
    assert "src/components/ExpenseList.vue:19  calls store action addExpense in add" in out
    assert "src/components/ExpenseList.vue:6  calls add in ExpenseList" in out  # template @save="add"
    assert "Tests to run (1):" in out and "tests/trip.spec.ts:7" in out
    narrow = run(capsys, "--impact", "formatMoney", "--kinds", "calls", "--depth", "1")
    assert "Level 2" not in narrow and "src/components/ExpenseItem.vue:4  calls formatMoney" in narrow
    assert "nothing uses it" in run(capsys, "--impact", "BaseButton", "--kinds", "types")
    assert "neither an indexed file nor a symbol" in run(capsys, "--impact", "NoSuchThing")
    assert "unknown kind(s): bogus" in run(capsys, "--impact", "src/utils/math.ts", "--kinds", "bogus")


def test_inferred_hidden_by_default(project, repo, monkeypatch, capsys):
    _html(monkeypatch)
    (repo / "src").mkdir()
    (repo / "src" / "MyCard.vue").write_text("<template><b /></template>\n", encoding="utf-8")
    (repo / "src" / "Page.vue").write_text("<template><MyCard /></template>\n<script setup>\n"
                                           "import MyCard from './MyCard.vue'\n</script>\n", encoding="utf-8")
    (repo / "src" / "Other.vue").write_text("<template><my-card /></template>\n", encoding="utf-8")  # name only
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "x")
    out = run(capsys, "--impact", "src/MyCard.vue")
    assert "src/Page.vue" in out and "src/Other.vue" not in out
    assert "+1 more files through inferred edges" in out
    full = run(capsys, "--impact", "src/MyCard.vue", "--min-confidence", "inferred")
    assert "src/Other.vue" in full


def test_component_store_route_cssvar(project, vue_app, monkeypatch, capsys):
    _html(monkeypatch)
    c = run(capsys, "--component", "ExpenseItem")
    assert "Component ExpenseItem  src/components/ExpenseItem.vue:1" in c
    assert "Rendered by (1):" in c and "src/components/ExpenseList.vue:3  ExpenseList" in c
    assert "expense  :13  passed by 1: src/components/ExpenseList.vue:3" in c
    assert "remove  :14  emitted 1: src/components/ExpenseItem.vue:5; listened by 1:" in c
    assert "<BaseButton> :5  src/components/BaseButton.vue" in c
    assert "Component ExpenseItem" in run(capsys, "--component", "expense-item")
    s = run(capsys, "--store", "trip")  # `trip` -> useTripStore
    assert "Store useTripStore  src/stores/trip.ts:5" in s and "Actions:" in s
    assert "addExpense  :11  2 uses: src/components/ExpenseList.vue:19, tests/trip.spec.ts:7" in s
    assert "Getters:" in s and "total" in s
    r = run(capsys, "--route", "expenses")  # by name
    assert "Route /expenses (name: expenses)" in r and "shows src/views/ExpensesView.vue" in r
    assert "src/views/ItineraryView.vue:3 in ItineraryView  -> /expenses" in r
    v = run(capsys, "--css-var=--border")
    assert "CSS variable --border: 1 definitions" in v and "src/components/ExpenseForm.vue:26  uses it" in v
    assert run(capsys, "--css-var", "border") == v  # leading -- optional
    assert "No component named Nope" in run(capsys, "--component", "Nope")
    for args in (("--component", "App"), ("--store", "useUiStore"), ("--route", "/")):
        assert len(run(capsys, *args).strip().splitlines()) <= index.QUERY_LINES


def test_cochange_query(project, repo, capsys):
    for i in range(2):
        (repo / "a.ts").write_text("export const a = %d\n" % i)
        (repo / "b.ts").write_text("export const b = %d\n" % i)
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "x")
    out = run(capsys, "--cochange", "a.ts")
    assert "b.ts  [2 commits (100%)]" in out
    assert "not in the index" in run(capsys, "--cochange", "zzz.ts")


def test_line_limit_on_dense_graph(project, repo, monkeypatch, capsys):
    _html(monkeypatch)
    (repo / "src").mkdir()
    (repo / "src" / "Btn.vue").write_text("<template><b /></template>\n<script setup>\ndefineProps(['label'])\n"
                                          "</script>\n", encoding="utf-8")
    for i in range(60):
        (repo / "src" / ("P%d.vue" % i)).write_text(
            "<template><Btn label=\"x\" /></template>\n<script setup>\nimport Btn from './Btn.vue'\n</script>\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "x")
    for args in (("--component", "Btn"), ("--impact", "Btn"), ("--impact", "src/Btn.vue"), ("--symbol", "label")):
        out = run(capsys, *args).strip().splitlines()
        assert len(out) <= index.QUERY_LINES and any("more" in ln for ln in out), args
