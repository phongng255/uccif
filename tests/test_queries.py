"""Graph queries: symbol impact, --kinds / --min-confidence, cochange. All read-only and within
QUERY_LINES."""
import pytest

from conftest import git
from uccif_lib import cli, index, queries, ts_parse


def _ts(monkeypatch):
    monkeypatch.delenv("UCCIF_NO_TREE_SITTER", raising=False)
    if not ts_parse.availability()["typescript"]:
        pytest.skip("tree-sitter not installed")


def run(capsys, *args):
    assert cli.main(["index", "query"] + list(args)) == 0
    return capsys.readouterr().out


def test_parse_kinds():
    assert queries.parse_kinds("calls,vars") == ("calls", "reads", "writes")
    assert queries.parse_kinds("code") == ("imports", "calls", "passes_callback")
    assert queries.parse_kinds("") is None
    for gone in ("store", "vue", "css", "route", "renders", "calls_action"):  # no framework layer
        with pytest.raises(ValueError):
            queries.parse_kinds(gone)
    with pytest.raises(ValueError) as e:
        queries.parse_kinds("calls,nope")
    assert "nope" in str(e.value) and "groups:" in str(e.value)


def test_impact_of_a_symbol(project, vue_app, monkeypatch, capsys):
    _ts(monkeypatch)
    out = run(capsys, "--impact", "saveTrip")
    assert "Impact of saveTrip" in out and "defined at src/utils/firebase.ts" in out
    assert "src/composables/useSync.ts:9  calls saveTrip in sync" in out
    assert "src/composables/useSync.ts:13  passes callback sync in start" in out  # level 2
    narrow = run(capsys, "--impact", "formatMoney", "--kinds", "calls", "--depth", "1")
    assert "Level 2" not in narrow and "tests/math.spec.ts:7  calls formatMoney" in narrow
    assert "Tests to run (1):" in narrow
    assert "nothing uses it" in run(capsys, "--impact", "sumAmounts", "--kinds", "types")
    assert "neither an indexed file nor a symbol" in run(capsys, "--impact", "NoSuchThing")
    assert "unknown kind(s): bogus" in run(capsys, "--impact", "src/utils/math.ts", "--kinds", "bogus")


def test_inferred_hidden_by_default(project, repo, monkeypatch, capsys):
    _ts(monkeypatch)
    (repo / "src").mkdir()
    (repo / "src" / "a.ts").write_text("export function make() { return { go } }\nexport function go() {}\n",
                                       encoding="utf-8")
    (repo / "src" / "b.ts").write_text("import { go } from './a'\ngo()\n", encoding="utf-8")
    # `s.go()` on what make() returned: tied to a.ts#go by name only (inferred)
    (repo / "src" / "c.ts").write_text("import { make } from './a'\nconst s = make()\ns.go()\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "x")
    out = run(capsys, "--impact", "go")
    assert "src/b.ts" in out and "src/c.ts" not in out
    assert "+1 more files through inferred edges" in out
    full = run(capsys, "--impact", "go", "--min-confidence", "inferred")
    assert "src/c.ts:3  calls go" in full and "~inferred" in full


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
    _ts(monkeypatch)
    (repo / "src").mkdir()
    (repo / "src" / "btn.ts").write_text("export function label() {}\n", encoding="utf-8")
    for i in range(60):
        (repo / "src" / ("p%d.ts" % i)).write_text("import { label } from './btn'\nlabel()\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "x")
    for args in (("--impact", "label"), ("--impact", "src/btn.ts"), ("--symbol", "label")):
        out = run(capsys, *args).strip().splitlines()
        assert len(out) <= index.QUERY_LINES and any("more" in ln for ln in out), args
