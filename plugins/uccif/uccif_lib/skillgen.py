"""Write project skills (.claude/skills/<slug>-*/SKILL.md) from the CodeGraph index.

The same SKILL.md files are also written to `.agents/skills/` (the Agent Skills folder that
Antigravity CLI, Gemini CLI's successor, reads; `.agent/skills/` is its legacy name) when the
project already has `.agents/` or `.agent/`, when the hook came from Antigravity, or on request
(`--target agents|all`).

Any language, any framework: modules come from the directory tree, facts from
CodeGraph's graph (`.codegraph/codegraph.db`, opened read-only): the most-used
symbols and files of each module, which modules depend on which, routes, and
the tests that reach a module. Commands come from the manifests (stack.py).

Skills written:
  <slug>-map      where things live: stack, modules, entry points, routes, commands
  <slug>-bugfix   the shortest path from a symptom to a tested fix in this project
  <slug>-mod-*    one per sizeable module: key files and symbols, neighbours, tests

Each file carries a sha marker. A regeneration rewrites only files it wrote and
nobody edited; text inside the notes block survives every regeneration. A file
without the marker is the user's and is never touched.
"""

import hashlib
import json
import os
import re
import shutil
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath

from uccif_lib import __version__, codegraph, stack
from uccif_lib.paths import ensure_local, now_iso, read_json, write_json, write_text_atomic

SKILLS_DIR = Path(".claude") / "skills"
AGENTS_SKILLS_DIR = Path(".agents") / "skills"
LEGACY_AGENT_SKILLS_DIR = Path(".agent") / "skills"
TARGETS = ("auto", "claude", "agents", "all")
TARGET_MODULES = 10
MAX_MODULES = 24
MAX_MODULE_SKILLS = 10
MIN_MODULE_FILES = 3
USE_EDGES = ("calls", "references", "instantiates", "extends", "implements", "imports", "renders", "decorates")
NOTES_RE = re.compile(r"(<!-- uccif:notes -->\n)(.*?)(<!-- /uccif:notes -->)", re.S)
SHA_RE = re.compile(r"\n?<!-- uccif:sha=([0-9a-f]{12}) -->\n?$")
TEST_DIRS = {"test", "tests", "__tests__", "spec", "specs", "e2e", "testing"}
CONTAINERS = {"src", "lib", "libs", "app", "apps", "packages", "pkg", "internal", "cmd", "source", "sources",
              "main", "java", "kotlin", "scala", "com", "org", "net", "io", "modules", "services", "crates",
              "projects", "code"}
ROLES = {
    "api": "HTTP/API layer", "routes": "routing", "router": "routing", "components": "UI components",
    "views": "views / pages", "pages": "pages", "screens": "screens", "layouts": "layouts",
    "stores": "state", "store": "state", "state": "state", "models": "data models", "entities": "data models",
    "schemas": "schemas", "domain": "domain logic", "core": "core logic", "services": "services / business logic",
    "utils": "shared helpers", "helpers": "shared helpers", "common": "shared code", "shared": "shared code",
    "hooks": "reusable hooks", "composables": "reusable logic", "controllers": "request handlers",
    "handlers": "request handlers", "middleware": "middleware", "db": "persistence", "database": "persistence",
    "migrations": "database migrations", "repositories": "data access", "config": "configuration",
    "settings": "configuration", "cli": "command line", "cmd": "entry points", "commands": "commands",
    "auth": "authentication", "types": "type definitions", "styles": "styles", "workers": "background jobs",
    "jobs": "background jobs", "tasks": "tasks / jobs", "scripts": "scripts / tooling", "tools": "tooling",
    "plugins": "plugins", "infra": "infrastructure", "server": "server side", "backend": "backend",
    "client": "client side", "frontend": "frontend", "web": "web layer", "ui": "UI", "admin": "admin area",
    "i18n": "translations", "locales": "translations", "functions": "serverless functions",
    "graphql": "GraphQL", "alembic": "database migrations", "proto": "protocol definitions", "features": "features",
}
NON_CODE = {"yaml", "json", "toml", "markdown", "xml", "ini", "text", "csv", "html", "css", "scss", "less"}
ENTRY_STEMS = {"main", "index", "app", "server", "cli", "__main__", "manage", "program", "application", "lib", "mod"}


# ---- reading the CodeGraph index -------------------------------------------------

class NoIndex(Exception):
    pass


def db_path(project):
    return Path(project.root) / codegraph.INDEX_DIR / "codegraph.db"


def connect(project):
    path = db_path(project)
    if not path.exists():
        raise NoIndex("no CodeGraph index (.codegraph/codegraph.db); run `codegraph init --yes`")
    uri = "file:%s?mode=ro" % path.as_posix().replace("?", "%3f").replace("#", "%23")
    if os.name == "nt" and not uri.startswith("file:/"):
        uri = "file:/" + uri[5:]
    try:
        con = sqlite3.connect(uri, uri=True, timeout=10)
        con.execute("SELECT 1 FROM nodes LIMIT 1")
        return con
    except sqlite3.Error:
        try:  # WAL database in a read-only dir: read the last checkpoint instead
            con = sqlite3.connect(uri + "&immutable=1", uri=True, timeout=10)
            con.execute("SELECT 1 FROM nodes LIMIT 1")
            return con
        except sqlite3.Error as e:
            raise NoIndex("cannot read %s: %s" % (path, e))


def is_test(path):
    p = PurePosixPath(path)
    name = p.name.lower()
    return (any(part.lower() in TEST_DIRS for part in p.parts[:-1])
            or ".test." in name or ".spec." in name or name.startswith("test_")
            or bool(re.search(r"(_test|Test|Tests|_spec)\.\w+$", p.name)))


def load(con):
    files = {r[0]: {"lang": r[1], "nodes": r[2] or 0} for r in con.execute(
        "SELECT path, language, node_count FROM files")}
    marks = ",".join("?" * len(USE_EDGES))
    uses = con.execute(
        "SELECT s.file_path, t.file_path, t.id, t.kind, t.name, t.start_line, COUNT(*) FROM edges e "
        "JOIN nodes s ON s.id=e.source JOIN nodes t ON t.id=e.target "
        "WHERE e.kind IN (%s) AND s.file_path<>t.file_path GROUP BY s.file_path, t.id" % marks,
        USE_EDGES).fetchall()
    try:
        routes = con.execute("SELECT name, file_path, start_line FROM nodes WHERE kind='route' "
                             "ORDER BY file_path, start_line").fetchall()
    except sqlite3.Error:
        routes = []
    return files, uses, routes


# ---- modules ----------------------------------------------------------------------

def _parts(path):
    return PurePosixPath(path).parts


def choose_modules(paths, target=TARGET_MODULES):
    """Split source files into module dirs: open up pass-through and container dirs (src/,
    packages/, internal/ ...) and dirs larger than total/target, until ~target modules."""
    paths = sorted(paths)
    if not paths:
        return []
    total = len(paths)
    frontier = {"": (paths, False)}

    def split(d, fs):
        depth = len(_parts(d)) if d else 0
        groups, direct = defaultdict(list), []
        for f in fs:
            ps = _parts(f)
            if len(ps) - 1 > depth:
                groups["/".join(ps[:depth + 1])].append(f)
            else:
                direct.append(f)
        return groups, direct

    while True:
        best = None
        for d, (fs, done) in frontier.items():
            if done:
                continue
            groups, direct = split(d, fs)
            if not groups:
                continue
            name = _parts(d)[-1].lower() if d else ""
            passthrough = len(groups) == 1 and not direct
            container = d == "" or name in CONTAINERS
            big = len(fs) > max(8, total / float(target))
            if not (passthrough or container or big):
                continue
            # past the target, only still-large modules open up (hard cap MAX_MODULES)
            if (len(frontier) >= target and not passthrough and d != ""
                    and (len(fs) <= max(12, total * 0.15) or len(frontier) >= MAX_MODULES)):
                continue
            score = (passthrough, d == "", len(fs))
            if best is None or score > best[0]:
                best = (score, d, groups, direct)
        if best is None:
            break
        _, d, groups, direct = best
        del frontier[d]
        for g, fs in groups.items():
            frontier[g] = (fs, False)
        if direct:
            frontier[d] = (direct, True)
    return [{"dir": d or ".", "files": fs} for d, (fs, _) in sorted(frontier.items())]


def role_of(dir_):
    for part in reversed(_parts(dir_) if dir_ != "." else ()):
        if part.lower() in ROLES:
            return ROLES[part.lower()]
    return None


def label_of(dir_):
    if dir_ == ".":
        return "root"
    parts = [p for p in _parts(dir_) if p.lower() not in CONTAINERS]
    return "/".join(parts) if parts else _parts(dir_)[-1]


def slugify(text, cap=40):
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (s[:cap].strip("-") or "project")


def analyse(project):
    con = connect(project)
    try:
        files, uses, routes = load(con)
    finally:
        con.close()
    tests = {f for f in files if is_test(f)}
    code = [f for f in files if f not in tests and files[f]["lang"] not in NON_CODE
            and not any(p.startswith(".") for p in _parts(f)[:-1])]
    mods = choose_modules(code)
    owner = {f: i for i, m in enumerate(mods) for f in m["files"]}
    file_in, sym_in, sym_row = Counter(), Counter(), {}
    dep = defaultdict(Counter)
    test_hits = defaultdict(Counter)
    tested_files = set()
    for sp, tp, tid, tkind, tname, tline, n in uses:
        if sp in tests:
            if tp in owner:
                test_hits[owner[tp]][sp] += n
                tested_files.add(tp)
            continue
        file_in[tp] += n
        if tkind not in ("file", "import", "module"):
            sym_in[tid] += n
            sym_row[tid] = (tkind, tname, tp, tline)
        a, b = owner.get(sp), owner.get(tp)
        if a is not None and b is not None and a != b:
            dep[a][b] += n
    for i, m in enumerate(mods):
        fs = m["files"]
        m["label"] = label_of(m["dir"])
        m["role"] = role_of(m["dir"])
        m["langs"] = [l for l, _ in Counter(files[f]["lang"] for f in fs).most_common(3)]
        m["key_files"] = [(f, file_in[f]) for f in sorted(fs, key=lambda f: (-file_in[f], f))[:6]]
        m["key_symbols"] = [dict(zip(("kind", "name", "path", "line"), sym_row[s]), users=c)
                            for s, c in sym_in.most_common() if owner.get(sym_row[s][2]) == i
                            and sym_row[s][0] not in ("variable", "constant", "parameter")][:8]
        m["depends_on"] = [(mods[j]["dir"], n) for j, n in dep[i].most_common(5)]
        m["used_by"] = sorted(((mods[j]["dir"], dep[j][i]) for j in dep if dep[j].get(i)), key=lambda x: -x[1])[:5]
        m["tests"] = [t for t, _ in test_hits[i].most_common(5)]
        m["routes"] = [r for r in routes if owner.get(r[1]) == i][:8]
    entries = [f for f in files if f not in tests and PurePosixPath(f).stem.lower() in ENTRY_STEMS
               and file_in[f] == 0][:8]
    hotspots = [dict(zip(("kind", "name", "path", "line"), sym_row[s]), users=c) for s, c in sym_in.most_common(10)
                if sym_row[s][0] not in ("variable", "constant", "parameter")][:8]
    langs = Counter(v["lang"] for v in files.values() if v["lang"] not in NON_CODE)
    test_dirs = sorted({str(PurePosixPath(t).parent) for t in tests})[:6]
    return {"files": len(files), "langs": langs.most_common(6), "modules": mods, "entries": entries,
            "hotspots": hotspots, "routes": routes, "test_dirs": test_dirs, "n_tests": len(tests)}


# ---- rendering ----------------------------------------------------------------------

HEADER = ("<!-- Generated by UCCIF %s from the CodeGraph index; `uccif skills generate` rewrites it when the "
          "project's structure changes. Put your own notes inside the notes block: they are kept. -->" % __version__)
NOTES = "## Notes\n\n<!-- uccif:notes -->\n%s<!-- /uccif:notes -->\n"


def _uses(n):
    return "%d use%s" % (n, "" if n == 1 else "s")


def _sym(s):
    return "`%s` %s — %s:%d (%s)" % (s["name"], s["kind"], s["path"], s["line"], _uses(s["users"]))


def _front(name, description):
    description = re.sub(r"\s+", " ", description).strip().replace('"', "'")[:1000]
    return '---\nname: %s\ndescription: "%s"\n---\n\n%s\n' % (name, description, HEADER)


def _tests_block(runners, cmds):
    lines = []
    for r in runners[:4]:
        lines.append("- %s%s: one file `%s`%s" % (r["name"], (" in `%s/`" % r["dir"]) if r["dir"] != "." else "",
                                                   r["run_one"], (", all `%s`" % r["run_all"]) if r["run_all"] else ""))
    test_cmd = next((c for p, c in cmds if p == "test"), None)
    if test_cmd and not any(r["run_all"] == test_cmd for r in runners):
        lines.append("- project test command: `%s`" % test_cmd)
    return lines or ["- no test runner found in the manifests; ask the user how tests are run"]


def render_map(name, proj, a, cmds, mod_skills):
    lang_txt = ", ".join("%s (%d)" % (l, n) for l, n in a["langs"])
    mods = a["modules"]
    desc = ("Map of the %s codebase: where each kind of code lives (modules %s), entry points, routes, "
            "build/test commands and how to look code up with CodeGraph. Use first when you need to know "
            "where something is in %s, before searching or reading files."
            % (proj, ", ".join(m["dir"] for m in mods[:8]), proj))
    out = [_front(name, desc), "# %s — project map\n" % proj,
           "%d indexed files · %s · %d test files\n" % (a["files"], lang_txt, a["n_tests"]),
           "## Modules\n", "| dir | files | role | skill |", "|---|---|---|---|"]
    for m in sorted(mods, key=lambda m: -len(m["files"]))[:20]:
        out.append("| `%s` | %d | %s | %s |" % (m["dir"], len(m["files"]), m["role"] or "—",
                                                mod_skills.get(m["dir"], "—")))
    if len(mods) > 20:
        out.append("| … | +%d smaller modules | | |" % (len(mods) - 20))
    if a["entries"]:
        out += ["", "## Entry points (nothing in the repo imports them)", ""] + ["- `%s`" % e for e in a["entries"]]
    if a["routes"]:
        out += ["", "## Routes (%d)" % len(a["routes"]), ""]
        out += ["- `%s` — %s:%d" % r for r in a["routes"][:15]]
        if len(a["routes"]) > 15:
            out.append("- … `codegraph query <path> --kind route` for the rest")
    if a["hotspots"]:
        out += ["", "## Most-used symbols (a change here spreads)", ""] + ["- " + _sym(s) for s in a["hotspots"]]
    if cmds:
        out += ["", "## Commands", ""] + ["- %s: `%s`" % pc for pc in cmds[:12]]
    out += ["", "## Look code up (cheapest first)", "",
            "1. `codegraph_explore` MCP tool — or `codegraph explore \"<question>\"` in Bash / subagents.",
            "2. `codegraph node <symbol|file>`, `codegraph callers|callees <symbol>`, "
            "`codegraph files --filter <dir>`.",
            "3. Grep/Glob with a `path` from the table above, only for literals, config and non-code files.",
            "4. Read only the line range you still need.", "", NOTES % ""]
    return "\n".join(out)


def render_bugfix(name, proj, a, runners, cmds):
    desc = ("Shortest path to fix a bug, error, crash, failing test or wrong behaviour in %s: locate it with "
            "CodeGraph from the error message or symptom, trace callers, check impact, make the smallest fix and "
            "run only the affected tests. Use whenever the user reports something broken in %s." % (proj, proj))
    out = [_front(name, desc), "# Fix a bug in %s — shortest path\n" % proj,
           "Every step answers from the graph first; open files only for lines it did not return.\n",
           "1. **Locate.** `codegraph explore \"<error message | failing test name | symptom>\"`. With a stack",
           "   trace, take the deepest frame inside this repo and run `codegraph node <that file>` (or the",
           "   function name). The returned source counts as read.",
           "2. **Trace the cause, not the symptom.** `codegraph callers <symbol>` (who passes the bad",
           "   input) and `codegraph callees <symbol>` (what it relies on). Stop at the first frame whose",
           "   input is already wrong.",
           "3. **Literals the graph cannot see** (error text, config keys, env vars, SQL, templates):",
           "   Grep with `path` set to the module dir from `%s-map`." % name.rsplit("-", 1)[0],
           "4. **Reproduce** with the narrowest test or command before editing when it is cheap.",
           "5. **Impact before editing a shared symbol:** `codegraph impact <symbol> --depth 2`. If it",
           "   reaches more than one module, use the `uccif:code-impact-analysis` skill.",
           "6. **Fix** with the smallest edit at the cause.",
           "7. **Test only what is affected:** `git diff --name-only | codegraph affected --stdin --quiet`,",
           "   then run those files:", ""]
    out += ["   " + l for l in _tests_block(runners, cmds)]
    out += ["", "8. Two failed fixes in a row → stop and gather evidence (logs, repro) first.",
            "9. Record it: `uccif task checkpoint --issue \"<cause> -> <fix>\"`."]
    if a["hotspots"]:
        out += ["", "## Hotspots (most-used symbols: a bug here shows up in many places)", ""]
        out += ["- " + _sym(s) for s in a["hotspots"][:6]]
    if a["test_dirs"]:
        out += ["", "## Where tests live", ""] + ["- `%s/`" % d for d in a["test_dirs"]]
    out += ["", NOTES % ""]
    return "\n".join(out)


def render_module(name, proj, m, runners):
    syms = [s["name"] for s in m["key_symbols"][:6]]
    desc = ("%s module `%s/`%s%s. Use when reading, changing, debugging or reviewing code under %s/ "
            "or these symbols." % (proj, m["dir"], (" (%s)" % m["role"]) if m["role"] else "",
                                   (": " + ", ".join(syms)) if syms else "", m["dir"]))
    out = [_front(name, desc),
           "# %s — `%s/`%s\n" % (proj, m["dir"], (" · " + m["role"]) if m["role"] else ""),
           "%d files · %s\n" % (len(m["files"]), ", ".join(m["langs"]))]
    if m["key_files"]:
        out += ["## Key files (most used from elsewhere)", ""]
        out += ["- `%s`%s" % (f, (" — " + _uses(n)) if n else "") for f, n in m["key_files"]]
    if m["key_symbols"]:
        out += ["", "## Key symbols", ""] + ["- " + _sym(s) for s in m["key_symbols"]]
    if m["routes"]:
        out += ["", "## Routes", ""] + ["- `%s` — %s:%d" % r for r in m["routes"]]
    if m["depends_on"] or m["used_by"]:
        out += ["", "## Neighbours", ""]
        if m["depends_on"]:
            out.append("- depends on: " + ", ".join("`%s` (%d)" % d for d in m["depends_on"]))
        if m["used_by"]:
            out.append("- used by: " + ", ".join("`%s` (%d)" % d for d in m["used_by"]))
    out += ["", "## Tests", ""]
    out += ["- `%s`" % t for t in m["tests"]] or ["- none reach this module directly (check `codegraph affected`)"]
    if m["tests"]:
        cmd = stack.run_one(runners, m["tests"][0])
        if cmd:
            out.append("- run one: `%s`" % cmd)
    out += ["", "## Look up here", "",
            "- `codegraph explore \"<question> in %s\"`" % m["dir"],
            "- `codegraph files --filter %s`" % m["dir"],
            "- before changing a key symbol: `codegraph impact <symbol>`", "", NOTES % ""]
    return "\n".join(out)


# ---- writing --------------------------------------------------------------------------

def _body_sha(text):
    text = SHA_RE.sub("", text).rstrip("\n")
    text = NOTES_RE.sub(lambda m: m.group(1) + m.group(3), text)
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


def _finish(text, notes):
    if notes:
        text = NOTES_RE.sub(lambda m: m.group(1) + notes + m.group(3), text, count=1)
    return text.rstrip("\n") + "\n<!-- uccif:sha=%s -->\n" % _body_sha(text)


def _existing(path):
    """(state, notes): state is 'none', 'user' (no marker), 'edited' or 'ours'."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return "none", ""
    m = SHA_RE.search(text)
    if not m:
        return "user", ""
    nm = NOTES_RE.search(text)
    notes = nm.group(2) if nm else ""
    return ("ours" if _body_sha(text) == m.group(1) else "edited"), notes


def skills_root(project):
    return Path(project.root) / SKILLS_DIR


def agents_root(project):
    """.agents/skills/, or the legacy .agent/skills/ when only that one exists."""
    root = Path(project.root)
    if not (root / ".agents").is_dir() and (root / ".agent").is_dir():
        return root / LEGACY_AGENT_SKILLS_DIR
    return root / AGENTS_SKILLS_DIR


def wants_agents(project):
    """auto: the project already uses the .agents/ (or legacy .agent/) standard, or the host is
    Antigravity (UCCIF_AGENT, set by its hooks)."""
    root = Path(project.root)
    return ((root / ".agents").is_dir() or (root / ".agent").is_dir()
            or os.environ.get("UCCIF_AGENT") == "antigravity")


def target_roots(project, target="auto"):
    if target not in TARGETS:
        raise ValueError("unknown skills target: %s" % target)
    roots = []
    if target in ("auto", "claude", "all"):
        roots.append(skills_root(project))
    if target in ("agents", "all") or (target == "auto" and wants_agents(project)):
        roots.append(agents_root(project))
    return roots


def _rel_dir(project, root):
    return Path(root).relative_to(project.root).as_posix() + "/"


def generated(project):
    """Names of skill dirs that hold a UCCIF-generated SKILL.md (.claude/skills/, else .agents/skills/)."""
    for root in (skills_root(project), agents_root(project)):
        if root.is_dir():
            names = sorted(p.parent.name for p in root.glob("*/SKILL.md") if _existing(p)[0] in ("ours", "edited"))
            if names:
                return names
    return []


def generate(project, force=False, dry_run=False, target="auto"):
    """Returns {'written': [...], 'unchanged': [...], 'skipped': [(name, why)], 'removed': [...],
    'roots': [...]}; names carry their folder ('.agents/skills/x') when more than one is written."""
    a = analyse(project)
    proj = Path(project.root).name
    slug = slugify(proj, 30)
    runners = stack.test_runners(project.root)
    cmds = stack.commands(project.root)
    mods = [m for m in sorted(a["modules"], key=lambda m: -len(m["files"]))
            if len(m["files"]) >= MIN_MODULE_FILES and m["dir"] != "."][:MAX_MODULE_SKILLS]
    names, mod_skills = set(), {}
    for m in mods:
        n = "%s-mod-%s" % (slug, slugify(m["label"], 32))
        while n in names:
            n += "-x"
        names.add(n)
        mod_skills[m["dir"]] = n
    docs = {"%s-map" % slug: render_map("%s-map" % slug, proj, a, cmds, mod_skills),
            "%s-bugfix" % slug: render_bugfix("%s-bugfix" % slug, proj, a, runners, cmds)}
    for m in mods:
        docs[mod_skills[m["dir"]]] = render_module(mod_skills[m["dir"]], proj, m, runners)
    roots = target_roots(project, target)
    res = {"written": [], "unchanged": [], "skipped": [], "removed": [],
           "roots": [_rel_dir(project, r) for r in roots]}
    for root in roots:
        label = (lambda n: n) if len(roots) == 1 else (lambda n, pre=_rel_dir(project, root): pre + n)
        _write_root(root, docs, slug, res, label, force, dry_run)
    if not dry_run:
        ensure_local(project)
        write_json(project.local_dir / "skills.json", {"fingerprint": fingerprint(project), "updated": now_iso(),
                                                      "skills": sorted(docs), "roots": res["roots"]})
    return res


def _write_root(root, docs, slug, res, label, force, dry_run):
    for name, text in docs.items():
        path = root / name / "SKILL.md"
        state, notes = _existing(path)
        if state == "user":
            res["skipped"].append((label(name), "written by you (no UCCIF marker)"))
            continue
        if state == "edited" and not force:
            res["skipped"].append((label(name), "edited outside the notes block (use --force to overwrite)"))
            continue
        new = _finish(text, notes)
        try:
            old = path.read_text(encoding="utf-8")
        except OSError:
            old = None
        if old == new:
            res["unchanged"].append(label(name))
            continue
        if not dry_run:
            write_text_atomic(path, new)
        res["written"].append(label(name))
    prefix = "%s-mod-" % slug
    if root.is_dir():
        for p in sorted(root.glob(prefix + "*/SKILL.md")):
            name = p.parent.name
            state, notes = _existing(p)
            if name not in docs and state == "ours" and not notes.strip():
                if not dry_run:
                    shutil.rmtree(str(p.parent), ignore_errors=True)
                res["removed"].append(label(name))


def fingerprint(project):
    from uccif_lib import drift
    fp = drift.fingerprint(project)
    return hashlib.sha1(json.dumps([fp, __version__], sort_keys=True).encode("utf-8")).hexdigest()[:16]


def auto(project):
    """Background (maintain): regenerate when the project's shape changed since the last run.
    A user who deleted the generated skills is respected until the structure changes."""
    if not codegraph.indexed(project):
        return None
    state = read_json(project.local_dir / "skills.json", {}) or {}
    roots = [_rel_dir(project, r) for r in target_roots(project)]
    if state.get("fingerprint") == fingerprint(project) and set(roots) <= set(state.get("roots") or [".claude/skills/"]):
        return None
    try:
        return generate(project)
    except NoIndex:
        return None


def report(res):
    lines = []
    for key, label in (("written", "written"), ("unchanged", "unchanged"), ("removed", "removed (module gone)")):
        if res[key]:
            lines.append("%s: %s" % (label, ", ".join(res[key])))
    lines += ["skipped %s: %s" % s for s in res["skipped"]]
    where = " and ".join(res.get("roots") or [".claude/skills/"])
    lines.append("Skills live in %s (commit them to share with your team)." % where)
    return lines
