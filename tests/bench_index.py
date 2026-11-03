"""Index benchmark (not collected by pytest, not run in CI).

    python tests/bench_index.py [--repeat N] [--json] [--target PATH ...]

For each target (default: the vue-app fixture and this repo) it reports
  - full build time (cold index),
  - incremental update after touching ONE file (what the post-Edit hook pays; budget 300 ms),
  - no-op update (stat pass only),
  - index.db size, files, symbols, imports, calls.
Run with and without tree-sitter (UCCIF_NO_TREE_SITTER=1) and paste the table into the PR.
The fixture is tiny, so also pass --target <a real app> to see the budget on a real repo.
Everything runs in a temp data dir; targets are copied/read, never modified.
"""
import argparse
import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO / "plugins" / "uccif"))

BUDGET_MS = 300


def _git(cwd, *args):
    subprocess.run(["git", "-c", "user.email=b@b", "-c", "user.name=b"] + list(args),
                   cwd=str(cwd), check=True, capture_output=True)


def _prepare(target, work):
    """Copy the target into a temp git repo so touching files never dirties the original."""
    dst = work / "repo"
    ignore = shutil.ignore_patterns(".git", "node_modules", "__pycache__", ".pytest_cache")
    shutil.copytree(str(target), str(dst), ignore=ignore)
    _git(dst, "init", "-q")
    _git(dst, "add", "-A")
    _git(dst, "commit", "-q", "-m", "bench")
    return dst


def _ms(fn):
    t = time.perf_counter()
    out = fn()
    return (time.perf_counter() - t) * 1000, out


def synthetic_app(dest, n):
    """Write a Vue 3 + Pinia + router app with `n` components (about n * 1.3 files) to `dest`.
    Each component imports two others, renders them with props and listens to an emit, uses a store
    action and state, a composable, a util through a barrel, CSS variables and classes; views are
    routed and navigate to each other. Shaped like a real app, only bigger."""
    dest = Path(dest)
    stores = max(3, n // 25)
    views = max(3, n // 10)

    def w(rel, text):
        p = dest / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")

    w("package.json", '{"name": "big", "dependencies": {"vue": "^3", "pinia": "^2", "vue-router": "^4"}}')
    w("tsconfig.json", '{"compilerOptions": {"baseUrl": ".", "paths": {"@/*": ["src/*"]}}}')
    w("src/styles/tokens.css", ":root {\n" + "".join("  --c%d: #%06x;\n" % (i, i * 997) for i in range(40)) + "}\n")
    w("src/utils/format.ts", "".join("export function fmt%d(x: number): string { return String(x + %d) }\n" % (i, i)
                                     for i in range(30)))
    w("src/utils/index.ts", "export * from './format'\n")
    w("src/types/index.ts", "".join("export interface T%d { id: string; v: number }\n" % i for i in range(30)))
    for s_ in range(stores):
        w("src/stores/s%d.ts" % s_, "import { defineStore } from 'pinia'\nimport type { T%d } from '@/types'\n"
          "export const useS%dStore = defineStore('s%d', {\n  state: () => ({ items: [] as T%d[], n: 0 }),\n"
          "  getters: { total: (st) => st.items.length },\n"
          "  actions: { add(x: T%d) { this.items.push(x) }, reset() { this.n = 0 } },\n})\n"
          % (s_ % 30, s_, s_, s_ % 30, s_ % 30))
    for c in range(n // 20 + 1):
        w("src/composables/useC%d.ts" % c, "import { computed } from 'vue'\nimport { useS%dStore } from '@/stores/s%d'\n"
          "export function useC%d() {\n  const st = useS%dStore()\n  const label = computed(() => st.total)\n"
          "  function bump() { st.add({ id: 'x', v: 1 }) }\n  return { label, bump }\n}\n"
          % (c % stores, c % stores, c, c % stores))
    for i in range(n):
        a, b = (i + 1) % n, (i + 7) % n
        s_ = i % stores
        w("src/components/C%d.vue" % i, """<template>
  <div class="card c%(i)d" :class="{ active: on }" @click="toggle()">
    <h3>{{ fmt%(f)d(store.total) }} {{ label }}</h3>
    <C%(a)d v-if="depth > 0" :depth="depth - 1" title="t" @picked="onPick" />
    <C%(b)d v-if="depth > 1" :depth="depth - 2" @picked="onPick" />
    <button @click="store.add({ id: 'i', v: %(i)d })">add</button>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import C%(a)d from './C%(a)d.vue'
import C%(b)d from './C%(b)d.vue'
import { fmt%(f)d } from '@/utils'
import { useS%(s)dStore } from '@/stores/s%(s)d'
import { useC%(c)d } from '@/composables/useC%(c)d'
import type { T%(t)d } from '@/types'

const props = defineProps<{ depth: number; title?: string }>()
const emit = defineEmits<{ (e: 'picked', v: T%(t)d): void }>()
const store = useS%(s)dStore()
const { label, bump } = useC%(c)d()
const on = ref(false)

function toggle() {
  on.value = !on.value
  bump()
}

function onPick(v: T%(t)d) {
  emit('picked', v)
}
</script>

<style scoped>
.card { color: var(--c%(v)d); border: 1px solid var(--c%(v2)d); }
.active { background: var(--c%(v3)d); }
</style>
""" % {"i": i, "a": a, "b": b, "f": i % 30, "s": s_, "c": i % (n // 20 + 1), "t": i % 30, "v": i % 40,
            "v2": (i + 3) % 40, "v3": (i + 9) % 40})
    routes = "".join("    { path: '/v%d', name: 'v%d', component: () => import('@/views/V%d.vue') },\n" % (v, v, v)
                     for v in range(views))
    w("src/router/index.ts", "import { createRouter, createWebHistory } from 'vue-router'\n"
      "export default createRouter({ history: createWebHistory(), routes: [\n%s] })\n" % routes)
    for v in range(views):
        w("src/views/V%d.vue" % v, "<template>\n  <RouterLink to=\"/v%d\">next</RouterLink>\n  <C%d :depth=\"2\" />\n"
          "</template>\n<script setup lang=\"ts\">\nimport C%d from '@/components/C%d.vue'\n</script>\n"
          % ((v + 1) % views, v % n, v % n, v % n))
    w("src/App.vue", "<template><RouterView /></template>\n")
    w("src/main.ts", "import { createApp } from 'vue'\nimport App from './App.vue'\nimport router from './router'\n"
      "import '@/styles/tokens.css'\ncreateApp(App).use(router).mount('#app')\n")
    return dest


def bench(target, repeat):
    from uccif_lib import index, ts_parse
    from uccif_lib.paths import resolve_project
    work = Path(tempfile.mkdtemp(prefix="uccif-bench-"))
    os.environ["UCCIF_DATA_DIR"] = str(work / "data")
    os.environ["UCCIF_SYNC"] = "1"
    try:
        repo = _prepare(target, work)
        os.chdir(str(repo))
        project = resolve_project()
        build_ms, stats = _ms(lambda: index.update(project, full=True))
        con = index.connect(project, write=False)
        counts = {t: con.execute("SELECT count(*) FROM %s" % t).fetchone()[0] for t in ("files", "symbols")}
        counts["imports"] = con.execute("SELECT count(*) FROM edges WHERE kind IN ('imports','imports_ext') "
                                        "AND via IS NULL").fetchone()[0]
        counts["calls"] = con.execute("SELECT count(*) FROM edges WHERE kind IN ('calls','calls_ext','calls_action') "
                                      "AND (via IS NULL OR via LIKE '~%')").fetchone()[0]
        try:  # schema >= 4
            counts["nodes"] = con.execute("SELECT count(*) FROM nodes").fetchone()[0]
            counts["edges"] = con.execute("SELECT count(*) FROM edges").fetchone()[0]
            # edges that point at the repo or at a package are fully known; "unresolved" are leads
            un = con.execute("SELECT count(*) FROM edges WHERE confidence='unresolved'").fetchone()[0]
            ours = con.execute("SELECT count(*) FROM edges WHERE kind NOT IN ('imports_ext', 'calls_ext', 'extends_ext', 'implements_ext', 'renders_ext', 'contains', 'tests', 'uses_store', 'uses_composable', 'reads_state', 'calls_action')").fetchone()[0]
            counts["unresolved_pct"] = round(100.0 * un / ours) if ours else 0
        except Exception:
            counts.update(nodes=0, edges=0, unresolved_pct=0)
        con.close()
        db_kb = index.db_path(project).stat().st_size / 1024

        sources = sorted(r for r in index.list_source_files(repo))
        # the slowest path is a .vue file (script + template + derived passes), so prefer one
        pick = next((s for s in sources if s.endswith(".vue")), None) or \
            next((s for s in sources if not index.is_test(s)), None)
        touch, noop, catch = [], [], []
        for i in range(repeat):
            noop.append(_ms(lambda: index.update(project))[0])
            if pick:
                path = repo / pick
                path.write_text(path.read_text(encoding="utf-8", errors="replace") + "\n// touch %d\n" % i,
                                encoding="utf-8")
                ms, st = _ms(lambda: index.update(project, paths=[pick]))
                touch.append(ms)
                if st and st.get("derived_stale"):  # big repo: derived edges were deferred
                    catch.append(_ms(lambda: index.update(project))[0])
        return {
            "target": str(target), "tool": stats["tool"],
            "tree_sitter": any(ts_parse.availability().values()),
            "full_build_ms": round(build_ms), "touch_one_ms": round(statistics.median(touch)) if touch else None,
            "noop_ms": round(statistics.median(noop)), "db_kb": round(db_kb), **counts,
            "catch_up_ms": round(statistics.median(catch)) if catch else None,
            "touched": pick,
        }
    finally:
        os.chdir(str(HERE))
        shutil.rmtree(str(work), ignore_errors=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--target", action="append", help="directory to index (repeatable)")
    ap.add_argument("--repeat", type=int, default=5)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--synthetic", type=int, action="append", metavar="N",
                    help="also bench a generated Vue app with N components (repeatable, e.g. 200, 800)")
    a = ap.parse_args()
    targets = [Path(t).resolve() for t in a.target] if a.target else [HERE / "fixtures" / "vue-app", REPO]
    for n in a.synthetic or ():
        targets.append(synthetic_app(Path(tempfile.mkdtemp(prefix="uccif-synth-")) / ("vue-%d" % n), n))
    rows = [bench(t, a.repeat) for t in targets]
    if a.json:
        print(json.dumps(rows, indent=2))
        return 0
    hdr = ("target", "tool", "files", "symbols", "imports", "calls", "nodes", "edges", "unres %", "build ms", "touch-1 ms", "catch-up ms", "no-op ms", "db KB")
    print(" | ".join(hdr))
    print(" | ".join("---" for _ in hdr))
    over = False
    for r in rows:
        name = os.path.relpath(r["target"], str(REPO)) if r["target"].startswith(str(REPO)) else r["target"]
        print(" | ".join(str(x) for x in (name if name != "." else "(uccif repo)", r["tool"], r["files"],
                                            r["symbols"], r["imports"], r["calls"], r["nodes"], r["edges"],
                                            r["unresolved_pct"], r["full_build_ms"],
                                            r["touch_one_ms"], r["catch_up_ms"] if r["catch_up_ms"] is not None else "-", r["noop_ms"], r["db_kb"])))
        over = over or (r["touch_one_ms"] or 0) > BUDGET_MS
        if r["unresolved_pct"] > 30:
            print("WARNING: %d%% of edges are unresolved in %s (limit 30%%): report it." % (r["unresolved_pct"], name))
    if over:
        print("\nOVER BUDGET: touch-1 > %d ms. Report it and propose lazy evaluation for the new layer." % BUDGET_MS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
