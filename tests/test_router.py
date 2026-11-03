"""vue-router: route nodes, routes_to (route -> component), navigates_to (code -> route) (roadmap B5)."""
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


ROUTER = """import Home from '@/views/Home.vue'
export const routes = [
  { path: '/', name: 'home', component: Home,
    children: [ { path: 'kid', name: 'kid', component: () => import('@/views/Kid.vue') } ] },
  { path: '/trip/:id', name: 'trip', component: () => import('@/views/Trip.vue') },
  { path: '/old', redirect: '/' },
  { path: '/:pathMatch(.*)*', component: () => import('@/views/NotFound.vue') },
  { label: 'not a route', path: 'just-data' },
]
"""


def make(repo):
    write(repo, "package.json", "{}")
    write(repo, "src/router/index.ts", ROUTER)
    for v in ("Home", "Kid", "Trip", "NotFound"):
        write(repo, "src/views/%s.vue" % v, "<template><div /></template>\n")
    commit(repo)


def test_routes_nodes_and_routes_to(project, repo, monkeypatch):
    _ts(monkeypatch)
    make(repo)
    index.update(project)
    con = index.connect(project, write=False)
    got = {r[0].split("#route:")[1]: r[1] for r in con.execute("SELECT id, detail FROM nodes WHERE kind='route'")}
    assert got == {"/": "home", "/kid": "kid", "/trip/:id": "trip", "/old": None, "/:pathMatch(.*)*": None}
    rt = {e[5]: e for e in edges(project, kind="routes_to")}
    assert rt["/"][1] == "src/views/Home.vue#Home" and rt["/"][4] == "extracted"  # imported identifier
    assert rt["/kid"][1] == "src/views/Kid.vue#Kid"  # nested child, lazy import
    assert rt["/trip/:id"][3] == 5
    assert "/old" not in rt  # redirect only
    sym = "\n".join(index.query_symbol(project, "/trip/:id"))
    assert "route /trip/:id" in sym and "Routes to:" in sym
    comp = "\n".join(index.query_symbol(project, "Kid"))
    assert "Routed from (1):" in comp and "/kid  (src/router/index.ts:4)" in comp


def test_navigation_matching(project, repo, monkeypatch):
    _ts(monkeypatch)
    make(repo)
    write(repo, "src/nav.ts", "import { useRouter } from 'vue-router'\nconst r = useRouter()\n"
          "export function go(id: string) {\n  r.push('/')\n  r.push('/kid')\n  r.push('/trip/42')\n"
          "  r.push(`/trip/${id}`)\n  router.push({ name: 'kid' })\n  router.push({ name: 'nope' })\n"
          "  router.replace('/nowhere?x=1#h')\n  router.push('https://example.com')\n  other.push('/kid')\n"
          "  router.push('/trip/' + id)\n}\n")
    commit(repo)
    index.update(project)
    nav = [e for e in edges(project, kind="navigates_to") if e[6] == "src/nav.ts"]
    by = {(e[3]): e for e in nav}
    assert by[4][1].endswith("route:/") and by[4][4] == "extracted"
    assert by[5][1].endswith("route:/kid") and by[5][4] == "extracted"
    assert by[6][1].endswith("route:/trip/:id") and by[6][4] == "inferred"  # literal id fits the pattern
    assert by[7][1].endswith("route:/trip/:id") and by[7][4] == "inferred"  # template literal
    assert by[8][1].endswith("route:/kid") and by[8][4] == "extracted"  # by name
    assert by[9][1] is None and by[9][4] == "unresolved"  # unknown route name
    assert by[10][1] is None and by[10][4] == "unresolved"  # query/hash stripped, still no route
    assert 11 not in by and 12 not in by  # external URL; `other.push` is not a router
    assert by[13][1].endswith("route:/trip/:id") and by[13][4] == "inferred"  # 'prefix' + id
    assert by[4][0] == "src/nav.ts#go" and by[4][7] == "src/router/index.ts"


def test_template_links_and_router_calls(project, repo, monkeypatch):
    _html(monkeypatch)
    make(repo)
    write(repo, "src/App.vue", "<template>\n  <RouterLink to=\"/kid\">k</RouterLink>\n"
          "  <router-link :to=\"{ name: 'trip', params: { id: 1 } }\">t</router-link>\n"
          "  <RouterLink :to=\"`/trip/${n}`\">d</RouterLink>\n  <a @click=\"$router.push('/')\">h</a>\n</template>\n"
          "<script setup lang=\"ts\">\nconst n = 1\n</script>\n")
    commit(repo)
    index.update(project)
    by = {e[3]: e for e in edges(project, kind="navigates_to", src_path="src/App.vue")}
    assert by[2][1].endswith("route:/kid") and by[2][0] == "src/App.vue#App"
    assert by[3][1].endswith("route:/trip/:id") and by[3][4] == "extracted"
    assert by[4][4] == "inferred" and by[5][1].endswith("route:/")


def test_impact_follows_routes(project, repo, monkeypatch):
    _ts(monkeypatch)
    make(repo)
    write(repo, "src/nav.ts", "export function go() { router.push('/kid') }\n")
    commit(repo)
    out = "\n".join(index.impact(project, "src/views/Kid.vue")) if index.update(project) else ""
    assert "src/router/index.ts" in out  # the router imports it and routes to it
    assert "src/nav.ts" in out and "navigates to" in out  # level 2: code that opens the route


def test_navigation_edges_follow_updates(project, repo, monkeypatch):
    _ts(monkeypatch)
    make(repo)
    write(repo, "src/nav.ts", "export function go() { router.push('/kid') }\n")
    commit(repo)
    index.update(project)
    f = repo / "src" / "router" / "index.ts"
    f.write_text(ROUTER.replace("path: 'kid'", "path: 'child'"), encoding="utf-8")
    os.utime(str(f), (time.time() + 10, time.time() + 10))
    index.update(project)
    e = edges(project, kind="navigates_to", src_path="src/nav.ts")[0]
    assert e[4] == "unresolved" and e[1] is None  # route renamed: the navigation becomes a lead
    f.unlink()
    index.update(project)
    con = index.connect(project, write=False)
    ids = {r[0] for r in con.execute("SELECT id FROM nodes")}
    assert all(x[1] in ids for x in edges(project) if x[1])
    assert not con.execute("SELECT 1 FROM nodes WHERE kind='route'").fetchone()


def test_route_regex_and_non_router_objects(project, repo, monkeypatch):
    _ts(monkeypatch)
    write(repo, "data.ts", "export const menu = [{ path: 'x', label: 'X' }, { path: '/y', icon: 'i' }]\n")
    commit(repo)
    index.update(project)
    con = index.connect(project, write=False)
    assert not con.execute("SELECT 1 FROM nodes WHERE kind='route'").fetchone()  # no component/redirect/children
    rx = index._route_regex("/a/:id/b/:opt?")
    assert rx.match("/a/1/b/") and rx.match("/a/1/b/x") and not rx.match("/a/1")
    assert index._route_regex("/:pathMatch(.*)*").match("/anything/at/all")


def test_without_tree_sitter_no_routes(project, repo):
    make(repo)
    index.update(project)
    con = index.connect(project, write=False)
    assert not con.execute("SELECT 1 FROM nodes WHERE kind='route'").fetchone()
    assert not edges(project, kind="routes_to")
