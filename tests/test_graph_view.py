"""Graph view modes and edge-kind families."""
import pytest

from uccif_lib import cli, graph, index, ts_parse


def _ts(monkeypatch):
    monkeypatch.delenv("UCCIF_NO_TREE_SITTER", raising=False)
    if not ts_parse.availability()["typescript"]:
        pytest.skip("tree-sitter not installed")


def test_files_mode_families(project, vue_app, monkeypatch):
    _ts(monkeypatch)
    index.update(project)
    d = graph.graph_data(project)
    fams = {name: n for _, name, n in d["families"]}
    assert {"imports", "calls", "types"} <= set(fams)
    assert {name for _, name, _ in graph.FAMILIES} == {"imports", "calls", "types", "variables", "inheritance"}
    by = {n["id"]: i for i, n in enumerate(d["nodes"])}
    e = {(a, b): f for a, b, f in d["edges"]}
    f = e[(by["src/components/ExpenseList.vue"], by["src/stores/trip.ts"])]
    assert f & 1 and f & 2  # imports + calls
    assert d["mode"] == "files" and all(n["q"] == n["id"] for n in d["nodes"])


def test_symbols_mode(project, vue_app, monkeypatch):
    _ts(monkeypatch)
    index.update(project)
    d = graph.graph_data(project, mode="symbols", file="src/components/ExpenseList.vue")
    labels = {n["label"] for n in d["nodes"]}
    assert {"ExpenseList", "add", "remove", "useTripStore", "Expense"} <= labels
    n = next(x for x in d["nodes"] if x["label"] == "add" and x["g"] == "src/components/ExpenseList.vue")
    assert n["at"].startswith("src/components/ExpenseList.vue:") and n["q"] == "add"
    with pytest.raises(index.IndexUnavailable):
        graph.graph_data(project, mode="symbols", file="nope.ts")


def test_inferred_flag(project, repo, monkeypatch):
    _ts(monkeypatch)
    (repo / "a.ts").write_text("export function make() {}\nexport function go() {}\n", encoding="utf-8")
    (repo / "c.ts").write_text("import { make } from './a'\nconst s = make()\ns.go()\n", encoding="utf-8")
    index.update(project)
    d = graph.graph_data(project, mode="symbols", file="c.ts")
    assert any(f & graph.INFERRED for _, _, f in d["edges"])  # s.go() is tied by name only


def test_cli_modes(project, vue_app, monkeypatch, capsys, tmp_path):
    _ts(monkeypatch)
    index.update(project)
    assert cli.main(["index", "graph", "--out", str(tmp_path / "f.html")]) == 0
    assert " files, " in capsys.readouterr().out
    with pytest.raises(SystemExit):  # the component view is gone with the framework layer
        cli.main(["index", "graph", "--mode", "components", "--out", str(tmp_path / "c.html")])
    capsys.readouterr()
    assert cli.main(["index", "graph", "--file", "src/App.vue", "--out", str(tmp_path / "s.html")]) == 0
    out = capsys.readouterr().out
    assert "symbols" in out and (tmp_path / "s.html").read_text(encoding="utf-8").count("</script>") == 1
    assert cli.main(["index", "graph", "--file", "zzz.ts", "--out", str(tmp_path / "z.html")]) == 0
    assert "not in the index" in capsys.readouterr().out
