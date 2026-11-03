"""Graph view modes and edge-kind filters (step 13)."""
import pytest

from uccif_lib import cli, graph, index, ts_parse


def _html(monkeypatch):
    monkeypatch.delenv("UCCIF_NO_TREE_SITTER", raising=False)
    if not (any(ts_parse.availability().values()) and ts_parse.html_available()):
        pytest.skip("tree-sitter / tree-sitter-html not installed")


def test_files_mode_families(project, vue_app, monkeypatch):
    _html(monkeypatch)
    index.update(project)
    d = graph.graph_data(project)
    fams = {name: n for _, name, n in d["families"]}
    assert {"imports", "calls", "components", "stores", "routes", "css", "types"} <= set(fams)
    by = {n["id"]: i for i, n in enumerate(d["nodes"])}
    e = {(a, b): f for a, b, f in d["edges"]}
    f = e[(by["src/components/ExpenseList.vue"], by["src/stores/trip.ts"])]
    assert f & 1 and f & 2 and f & 8  # imports + calls + store
    css = e[(by["src/components/BaseButton.vue"], by["src/styles/tokens.css"])]
    assert css == 32  # only through a CSS variable
    assert d["mode"] == "files" and all(n["q"] == n["id"] for n in d["nodes"])


def test_components_mode(project, vue_app, monkeypatch):
    _html(monkeypatch)
    index.update(project)
    d = graph.graph_data(project, mode="components")
    assert all(n["lang"] == "vue" for n in d["nodes"])
    ids = {n["id"] for n in d["nodes"]}
    assert "src/components/BaseButton.vue" in ids and "src/stores/trip.ts" not in ids
    assert all(f & 4 for _, _, f in d["edges"]) and d["total_files"] == 8


def test_symbols_mode_and_inferred_flag(project, vue_app, monkeypatch):
    _html(monkeypatch)
    index.update(project)
    d = graph.graph_data(project, mode="symbols", file="src/components/ExpenseList.vue")
    labels = {n["label"] for n in d["nodes"]}
    assert {"ExpenseList", "add", "remove", "addExpense", "formatMoney"} <= labels
    n = next(x for x in d["nodes"] if x["label"] == "add" and x["g"] == "src/components/ExpenseList.vue")
    assert n["at"].startswith("src/components/ExpenseList.vue:") and n["q"] == "add"
    assert any(f & graph.INFERRED for _, _, f in d["edges"])  # uses_class is inferred
    with pytest.raises(index.IndexUnavailable):
        graph.graph_data(project, mode="symbols", file="nope.ts")


def test_cli_modes(project, vue_app, monkeypatch, capsys, tmp_path):
    _html(monkeypatch)
    index.update(project)
    assert cli.main(["index", "graph", "--mode", "components", "--out", str(tmp_path / "c.html")]) == 0
    assert "of 8 components" in capsys.readouterr().out
    assert cli.main(["index", "graph", "--file", "src/App.vue", "--out", str(tmp_path / "s.html")]) == 0
    out = capsys.readouterr().out
    assert "symbols" in out and (tmp_path / "s.html").read_text(encoding="utf-8").count("</script>") == 1
    assert cli.main(["index", "graph", "--file", "zzz.ts", "--out", str(tmp_path / "z.html")]) == 0
    assert "not in the index" in capsys.readouterr().out
