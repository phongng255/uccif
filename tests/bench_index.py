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
    """Write a plain TypeScript + Python app with `n` TS modules (plus n // 4 Python modules) to `dest`.
    Each TS module imports two others, calls their functions, extends a base class, reads and writes
    module state, references shared types and uses utils through a barrel; each Python module imports
    and subclasses another. No framework: shaped like a real app, only bigger."""
    dest = Path(dest)
    py = max(4, n // 4)

    def w(rel, text):
        p = dest / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")

    w("package.json", '{"name": "big", "dependencies": {"lodash": "^4"}}')
    w("tsconfig.json", '{"compilerOptions": {"baseUrl": ".", "paths": {"@/*": ["src/*"]}}}')
    w("src/utils/format.ts", "".join("export function fmt%d(x: number): string { return String(x + %d) }\n" % (i, i)
                                     for i in range(30)))
    w("src/utils/index.ts", "export * from './format'\n")
    w("src/types/index.ts", "".join("export interface T%d { id: string; v: number }\n" % i for i in range(30)))
    w("src/base.ts", "export class Base {\n  save(): void {}\n  load(id: string): string { return id }\n}\n")
    for i in range(n):
        a, b = (i + 1) % n, (i + 7) % n
        w("src/mod/m%d.ts" % i, """import { Base } from '@/base'
import { fmt%(f)d } from '@/utils'
import { run%(a)d, State%(a)d } from './m%(a)d'
import { run%(b)d } from './m%(b)d'
import type { T%(t)d } from '@/types'
import { debounce } from 'lodash'

export let count%(i)d = 0
const cache = new Map<string, T%(t)d>()

export class State%(i)d extends Base {
  items: T%(t)d[] = []
  add(x: T%(t)d): void {
    this.items.push(x)
    this.save()
  }
}

export function run%(i)d(depth: number, item: T%(t)d): string {
  count%(i)d += 1
  cache.set(item.id, item)
  const s = new State%(a)d()
  s.add(item)
  if (depth > 0) {
    run%(a)d(depth - 1, item)
    run%(b)d(depth - 2, item)
  }
  return fmt%(f)d(count%(i)d)
}

export const later%(i)d = debounce(() => run%(i)d(1, { id: 'x', v: %(i)d }), 10)
""" % {"i": i, "a": a, "b": b, "f": i % 30, "t": i % 30})
    w("src/main.ts", "import { run0 } from './mod/m0'\nrun0(3, { id: 'a', v: 1 })\n")
    w("app/__init__.py", "")
    w("app/base.py", "class Model:\n    def save(self):\n        return True\n")
    for i in range(py):
        a = (i + 1) % py
        w("app/p%d.py" % i, "from app.base import Model\nfrom app import p%d\n\nLIMIT = %d\n\n\n"
          "class Item%d(Model):\n    def run(self, n: int) -> int:\n        self.save()\n"
          "        return helper%d(n)\n\n\ndef helper%d(n: int) -> int:\n"
          "    return n + LIMIT if n > 0 else p%d.helper%d(n + 1)\n" % (a, i, i, i, i, a, a))
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
        counts["calls"] = con.execute("SELECT count(*) FROM edges WHERE kind IN ('calls','calls_ext') "
                                      "AND (via IS NULL OR via LIKE '~%')").fetchone()[0]
        try:  # schema >= 4
            counts["nodes"] = con.execute("SELECT count(*) FROM nodes").fetchone()[0]
            counts["edges"] = con.execute("SELECT count(*) FROM edges").fetchone()[0]
            # edges that point at the repo or at a package are fully known; "unresolved" are leads
            un = con.execute("SELECT count(*) FROM edges WHERE confidence='unresolved'").fetchone()[0]
            ours = con.execute("SELECT count(*) FROM edges WHERE kind NOT IN ('imports_ext', 'calls_ext', 'extends_ext', 'implements_ext', 'contains', 'tests')").fetchone()[0]
            counts["unresolved_pct"] = round(100.0 * un / ours) if ours else 0
        except Exception:
            counts.update(nodes=0, edges=0, unresolved_pct=0)
        con.close()
        db_kb = index.db_path(project).stat().st_size / 1024

        sources = sorted(r for r in index.list_source_files(repo))
        # a module in the middle of the import web: many users, so the derived passes have work to do
        pick = next((s for s in sources if s.endswith("/m1.ts")), None) or \
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
                    help="also bench a generated TS + Python app with N TS modules (repeatable, e.g. 200, 800)")
    a = ap.parse_args()
    targets = [Path(t).resolve() for t in a.target] if a.target else [HERE / "fixtures" / "vue-app", REPO]
    for n in a.synthetic or ():
        targets.append(synthetic_app(Path(tempfile.mkdtemp(prefix="uccif-synth-")) / ("app-%d" % n), n))
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
