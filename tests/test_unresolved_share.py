"""Fewer false leads: submodule namespaces, built-in methods on library results, pytest fixtures."""
import pytest

from conftest import git
from uccif_lib import index, ts_parse


def _ts(monkeypatch):
    monkeypatch.delenv("UCCIF_NO_TREE_SITTER", raising=False)
    if not any(ts_parse.availability().values()):
        pytest.skip("tree-sitter not installed")


def write(root, rel, text):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def edges(project, src):
    con = index.connect(project, write=False)
    rows = con.execute("SELECT kind, dst_id, confidence, detail FROM edges WHERE src_path=? AND kind IN "
                       "('calls','calls_ext')", (src,)).fetchall()
    con.close()
    return {(d, k, c, dst) for k, dst, c, d in rows}


def test_submodule_import_is_a_namespace(project, repo, monkeypatch):
    _ts(monkeypatch)
    write(repo, "plugins/x/pkg/__init__.py", "")
    write(repo, "plugins/x/pkg/store.py", "def save():\n    pass\n")
    write(repo, "plugins/x/pkg/rel.py", "from . import store\n\ndef a():\n    store.save()\n")
    write(repo, "plugins/x/use.py", "from pkg import store\n\ndef b():\n    store.save()\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "x")
    index.update(project)
    want = ("save", "calls", "extracted", "plugins/x/pkg/store.py#save")
    assert want in edges(project, "plugins/x/pkg/rel.py")  # from . import store
    assert want in edges(project, "plugins/x/use.py")  # from pkg import store


def test_builtin_methods_on_what_a_repo_function_returns(project, repo, monkeypatch):
    _ts(monkeypatch)
    write(repo, "db.py", "import sqlite3\n\ndef connect():\n    return sqlite3.connect(':memory:')\n")
    write(repo, "q.py", "from db import connect\n\ndef run():\n    con = connect()\n    con.execute('x')\n"
          "    con.frobnicate()\n")
    write(repo, "test_q.py", "def test_x(monkeypatch, capsys):\n    monkeypatch.setattr('a', 1)\n"
          "    capsys.readouterr()\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "x")
    index.update(project)
    q = edges(project, "q.py")
    assert ("execute", "calls_ext", "extracted", None) in q
    assert ("frobnicate", "calls", "unresolved", None) in q  # not a known built-in: still a lead
    t = edges(project, "test_q.py")
    assert ("setattr", "calls_ext", "extracted", None) in t and ("readouterr", "calls_ext", "extracted", None) in t
