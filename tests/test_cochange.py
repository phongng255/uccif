"""Files that change together, from git history (roadmap D5)."""
from conftest import git
from uccif_lib import index


def write(root, rel, text):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def commit(repo, msg="x"):
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", msg)


def edges(project):
    con = index.connect(project, write=False)
    rows = con.execute("SELECT src_path, dst_path, confidence, detail, via FROM edges WHERE kind='co_changes'"
                       ).fetchall()
    con.close()
    return rows


def history(repo):
    for i in range(3):  # api.ts and view.ts always move together; util.ts once with them
        write(repo, "api.ts", "export const v = %d\n" % i)
        write(repo, "view.ts", "export const w = %d\n" % i)
        if i == 0:
            write(repo, "util.ts", "export const u = 0\n")
        commit(repo)
    for i in range(3):
        write(repo, "util.ts", "export const u = %d\n" % (i + 1))
        commit(repo)


def test_pairs_from_history(project, repo):
    history(repo)
    index.update(project)
    got = {(a, b): (c, d, v) for a, b, c, d, v in edges(project)}
    assert got[("api.ts", "view.ts")] == ("inferred", "3 commits (100%)", "~git")
    assert ("view.ts", "api.ts") in got  # both directions
    assert ("api.ts", "util.ts") not in got  # once is not a pattern
    out = "\n".join(index.query_file(project, "api.ts"))
    assert "Often changed with (git): view.ts [3 commits (100%)]" in out
    assert "src/" not in out


def test_big_commits_ignored_and_cache_by_head(project, repo, monkeypatch):
    for i in range(2):
        for k in range(index.COCHANGE_MAX_FILES + 1):  # a "format everything" commit
            write(repo, "f%d.ts" % k, "export const x = %d\n" % i)
        commit(repo)
    index.update(project)
    assert edges(project) == []
    calls = []
    real = index._refresh_cochanges

    def spy(*a):
        calls.append(1)
        return real(*a)
    monkeypatch.setattr(index, "_refresh_cochanges", spy)
    index.update(project)
    con = index.connect(project, write=False)
    head = index._meta(con, "cochange_head")
    con.close()
    assert head  # cached: the second update ran git rev-parse only
    write(repo, "a.ts", "1\n")
    write(repo, "b.ts", "1\n")
    commit(repo)
    write(repo, "a.ts", "2\n")
    write(repo, "b.ts", "2\n")
    commit(repo)
    index.update(project)
    assert ("a.ts", "b.ts") in {(a, b) for a, b, _, _, _ in edges(project)}


def test_post_edit_update_skips_git(project, repo, monkeypatch):
    history(repo)
    index.update(project)
    monkeypatch.setattr(index, "_refresh_cochanges", lambda *a: (_ for _ in ()).throw(AssertionError("git ran")))
    write(repo, "api.ts", "export const v = 9\n")
    index.update(project, paths=["api.ts"])  # what the post-Edit hook does
    assert ("api.ts", "view.ts") in {(a, b) for a, b, _, _, _ in edges(project)}  # kept from the table


def test_deleted_file_drops_its_pairs(project, repo):
    history(repo)
    index.update(project)
    (repo / "view.ts").unlink()
    index.update(project)
    assert not [e for e in edges(project) if "view.ts" in (e[0], e[1])]
