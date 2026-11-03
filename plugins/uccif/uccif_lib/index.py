"""Code index: a small SQLite map of the repo so Claude finds code without scanning it.

Lives at <project data>/index/index.db (outside the repo). Holds files, symbol
definitions, imports (resolved to repo files where possible) and test links.
Symbols come from universal-ctags when it is installed, otherwise from
per-language regexes (marked precision "approx"). References are counted at
query time with `git grep -w`, so they are always current.

The index is a lead, not the truth: every answer cites file:line to read.
Every query first refreshes changed files (a stat pass, plus parsing only what
changed), so edits made outside Claude are picked up too.
"""

import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import time
from collections import Counter
from pathlib import Path, PurePosixPath

from uccif_lib import styles, ts_parse, vue_template
from uccif_lib.resolve import JS_RESOLVE_EXT, Resolver  # noqa: F401 (re-exported)
from uccif_lib.paths import LockTimeout, file_lock, now_iso

SCHEMA = 14
DERIVE_BUDGET_MS = 150  # above this, a post-Edit update defers the derived edges (see _update)
MAX_BYTES = 1000000
QUERY_LINES = 30

LANG_EXT = {
    ".ts": "typescript", ".tsx": "typescript", ".mts": "typescript", ".cts": "typescript",
    ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".vue": "vue", ".svelte": "svelte", ".py": "python", ".pyi": "python", ".go": "go",
    ".rs": "rust", ".java": "java", ".kt": "kotlin", ".kts": "kotlin", ".cs": "csharp",
    ".rb": "ruby", ".php": "php", ".swift": "swift", ".dart": "dart",
    ".c": "c", ".h": "c", ".cc": "cpp", ".cpp": "cpp", ".hpp": "cpp",
    ".css": "css", ".scss": "scss", ".sass": "scss", ".less": "less",
}
JS_LIKE = ("typescript", "javascript", "vue", "svelte")
SKIP_SUFFIXES = (".min.js", ".min.css", ".map", ".d.ts.map", ".bundle.js")
TEST_DIRS = {"test", "tests", "__tests__", "spec", "specs", "e2e"}
KEYWORDS = {"if", "for", "while", "switch", "catch", "return", "function", "constructor",
            "else", "do", "try", "with", "new", "typeof", "await", "super"}

_ID = r"[A-Za-z_$][\w$]*"
SYMBOL_RES = {
    "js": [
        ("function", re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*(%s)" % _ID)),
        ("class", re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(?:abstract\s+)?class\s+(%s)" % _ID)),
        ("interface", re.compile(r"^\s*(?:export\s+)?(?:declare\s+)?interface\s+(%s)" % _ID)),
        ("type", re.compile(r"^\s*(?:export\s+)?(?:declare\s+)?type\s+(%s)\s*(?:<[^=]*>)?\s*=" % _ID)),
        ("enum", re.compile(r"^\s*(?:export\s+)?(?:declare\s+)?(?:const\s+)?enum\s+(%s)" % _ID)),
        ("function", re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+(%s)\s*(?::[^=]+)?=\s*(?:async\s*)?"
                                r"(?:function\b|\([^)]*\)\s*(?::[^=]+)?=>|%s\s*=>)" % (_ID, _ID))),
        ("store", re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+(%s)\s*=\s*defineStore\b" % _ID)),
        ("variable", re.compile(r"^\s*export\s+(?:const|let|var)\s+(%s)" % _ID)),
        ("method", re.compile(r"^\s+(?:(?:public|private|protected|static|async|readonly|override|get|set)\s+)*"
                              r"(%s)\s*\([^)]*\)\s*(?::\s*[^{=;]+)?\{\s*$" % _ID)),
    ],
    "python": [
        ("class", re.compile(r"^(\s*)class\s+(\w+)")),
        ("function", re.compile(r"^(\s*)(?:async\s+)?def\s+(\w+)")),
        ("constant", re.compile(r"^()([A-Z][A-Z0-9_]{2,})\s*(?::[^=]+)?=")),
    ],
    "go": [
        ("function", re.compile(r"^func\s+(?:\([^)]*\)\s*)?(\w+)")),
        ("type", re.compile(r"^type\s+(\w+)\s")),
    ],
    "rust": [
        ("function", re.compile(r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:const\s+)?(?:async\s+)?(?:unsafe\s+)?fn\s+(\w+)")),
        ("type", re.compile(r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:struct|enum|trait|type|union)\s+(\w+)")),
    ],
    "jvm": [
        ("class", re.compile(r"^\s*(?:[\w@]+\s+)*(?:class|interface|enum|record|object)\s+(\w+)")),
        ("function", re.compile(r"^\s*(?:[\w@<>\[\],?]+\s+)*fun\s+(?:<[^>]*>\s*)?(?:\w+\.)?(\w+)\s*\(")),
        ("method", re.compile(r"^\s+(?:(?:public|private|protected|internal|static|final|abstract|override|"
                              r"virtual|async|synchronized)\s+)+[\w<>\[\],?. ]+\s+(\w+)\s*\(")),
    ],
    "php": [
        ("function", re.compile(r"^\s*(?:(?:public|private|protected|static|abstract|final)\s+)*function\s+&?(\w+)")),
        ("class", re.compile(r"^\s*(?:abstract\s+|final\s+)?(?:class|interface|trait|enum)\s+(\w+)")),
    ],
    "ruby": [
        ("function", re.compile(r"^\s*def\s+(?:self\.)?(\w+[?!=]?)")),
        ("class", re.compile(r"^\s*(?:class|module)\s+([A-Z]\w*)")),
    ],
    "c": [
        ("function", re.compile(r"^[A-Za-z_][\w\s\*&:<>,]*?\b(\w+)\s*\([^;]*\)\s*(?:const\s*)?\{?\s*$")),
        ("type", re.compile(r"^\s*(?:typedef\s+)?(?:struct|class|enum|union)\s+(\w+)")),
    ],
    "swift": [
        ("function", re.compile(r"^\s*(?:[\w@]+\s+)*func\s+(\w+)")),
        ("class", re.compile(r"^\s*(?:[\w@]+\s+)*(?:class|struct|enum|protocol|extension|actor)\s+(\w+)")),
    ],
    "dart": [
        ("class", re.compile(r"^\s*(?:abstract\s+)?(?:class|mixin|enum|extension)\s+(\w+)")),
    ],
    "style": [
        ("css-var", re.compile(r"^\s*(--[\w-]+)\s*:")),
        ("scss-var", re.compile(r"^\s*(\$[\w-]+)\s*:")),
        ("mixin", re.compile(r"^\s*@mixin\s+([\w-]+)")),
    ],
}
LANG_FAMILY = {
    "typescript": "js", "javascript": "js", "vue": "js", "svelte": "js", "python": "python",
    "go": "go", "rust": "rust", "java": "jvm", "kotlin": "jvm", "csharp": "jvm", "php": "php",
    "ruby": "ruby", "c": "c", "cpp": "c", "swift": "swift", "dart": "dart",
    "css": "style", "scss": "style", "less": "style",
}
IMPORT_RES = {
    "js": [re.compile(r"""(?:import|export)\s[^'"`;]*?\bfrom\s*['"]([^'"]+)['"]"""),
           re.compile(r"""^\s*import\s*['"]([^'"]+)['"]""", re.M),
           re.compile(r"""\brequire\(\s*['"]([^'"]+)['"]\s*\)"""),
           re.compile(r"""\bimport\(\s*['"]([^'"]+)['"]\s*\)""")],
    "python": [re.compile(r"^\s*from\s+(\.*[\w.]*)\s+import\b", re.M),
               re.compile(r"^\s*import\s+([\w.]+)", re.M)],
    "go": [re.compile(r'^\s*(?:import\s+)?(?:\w+\s+)?"([\w./-]+)"\s*$', re.M)],
    "style": [re.compile(r"""@(?:import|use|forward)\s+(?:url\()?['"]([^'"]+)['"]""")],
    "rust": [re.compile(r"^\s*(?:pub\s+)?mod\s+(\w+)\s*;", re.M)],
}


# ---- helpers ------------------------------------------------------------------

def db_path(project):
    return project.data_dir / "index" / "index.db"


class IndexUnavailable(Exception):
    pass


def connect(project, write=True):
    """Writers (hooks, `index update`) create/upgrade the schema. Readers open the file
    read-only: queries run from Claude's Bash, whose sandbox denies writes under ~/.claude.
    Rollback-journal mode (not WAL) so a read-only open needs no -shm/-wal files."""
    path = db_path(project)
    if not write:
        if not path.exists():
            raise IndexUnavailable("not built yet")
        uri = "file:%s?mode=ro" % path.as_posix().replace("?", "%3f").replace("#", "%23")
        if os.name == "nt" and not uri.startswith("file:/"):
            uri = "file:/" + uri[5:]
        try:
            con = sqlite3.connect(uri, uri=True, timeout=5)
            if _meta(con, "schema") != str(SCHEMA):
                con.close()
                raise IndexUnavailable("built by another version; rebuilds on the next update")
            return con
        except sqlite3.Error as e:
            raise IndexUnavailable(str(e))
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path), timeout=5)
    con.execute("PRAGMA journal_mode=DELETE")
    con.executescript("""
        CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS files (path TEXT PRIMARY KEY, lang TEXT, size INTEGER,
            mtime REAL, hash TEXT, is_test INTEGER, n_symbols INTEGER);
        CREATE TABLE IF NOT EXISTS symbols (name TEXT, kind TEXT, path TEXT, line INTEGER,
            scope TEXT, precision TEXT);
        CREATE TABLE IF NOT EXISTS imports (src TEXT, raw TEXT, target TEXT, line INTEGER);
        CREATE TABLE IF NOT EXISTS calls (src_path TEXT, src_symbol TEXT, callee_name TEXT,
            callee_path TEXT, line INTEGER);
        CREATE TABLE IF NOT EXISTS nodes (id TEXT PRIMARY KEY, kind TEXT, name TEXT, path TEXT, line INTEGER,
            end_line INTEGER, scope TEXT, precision TEXT, detail TEXT);
        CREATE TABLE IF NOT EXISTS edges (src_id TEXT, dst_id TEXT, kind TEXT, line INTEGER,
            confidence TEXT, detail TEXT, src_path TEXT, dst_path TEXT, via TEXT);
        CREATE TABLE IF NOT EXISTS bindings (path TEXT, name TEXT, orig TEXT, raw TEXT, line INTEGER);
        CREATE TABLE IF NOT EXISTS tags (path TEXT, tag TEXT, line INTEGER);
        CREATE TABLE IF NOT EXISTS refs (src_id TEXT, src_path TEXT, kind TEXT, member TEXT, line INTEGER,
            origin_path TEXT, origin_name TEXT);
        CREATE INDEX IF NOT EXISTS refs_path ON refs(src_path);
        CREATE TABLE IF NOT EXISTS tag_uses (path TEXT, tag TEXT, line INTEGER, kind TEXT, name TEXT,
            attr_line INTEGER);
        CREATE INDEX IF NOT EXISTS tag_uses_path ON tag_uses(path);
        CREATE TABLE IF NOT EXISTS navs (src_id TEXT, src_path TEXT, line INTEGER, kind TEXT, value TEXT,
            dynamic INTEGER);
        CREATE INDEX IF NOT EXISTS navs_path ON navs(src_path);
        CREATE TABLE IF NOT EXISTS cochanges (a TEXT, b TEXT, n INTEGER, ratio REAL);
        CREATE INDEX IF NOT EXISTS cochanges_a ON cochanges(a);
        CREATE TABLE IF NOT EXISTS css_uses (path TEXT, src_id TEXT, kind TEXT, name TEXT, line INTEGER);
        CREATE INDEX IF NOT EXISTS css_uses_path ON css_uses(path);
        CREATE TABLE IF NOT EXISTS globals (path TEXT, name TEXT, target TEXT, line INTEGER);
        CREATE INDEX IF NOT EXISTS tags_path ON tags(path);
        CREATE INDEX IF NOT EXISTS globals_path ON globals(path);
        CREATE INDEX IF NOT EXISTS bind_path ON bindings(path);
        CREATE INDEX IF NOT EXISTS node_path ON nodes(path);
        CREATE INDEX IF NOT EXISTS node_name ON nodes(name);
        CREATE INDEX IF NOT EXISTS edge_src ON edges(src_path, kind);
        CREATE INDEX IF NOT EXISTS edge_dst ON edges(dst_path, kind);
        CREATE INDEX IF NOT EXISTS edge_detail ON edges(detail);
        CREATE INDEX IF NOT EXISTS call_callee ON calls(callee_name);
        CREATE INDEX IF NOT EXISTS call_src ON calls(src_path);
        CREATE INDEX IF NOT EXISTS call_cpath ON calls(callee_path);
        CREATE INDEX IF NOT EXISTS sym_name ON symbols(name);
        CREATE INDEX IF NOT EXISTS sym_lname ON symbols(lower(name));
        CREATE INDEX IF NOT EXISTS sym_path ON symbols(path);
        CREATE INDEX IF NOT EXISTS imp_src ON imports(src);
        CREATE INDEX IF NOT EXISTS imp_target ON imports(target);
    """)
    if _meta(con, "schema") not in (None, str(SCHEMA)):
        con.executescript("DELETE FROM files; DELETE FROM symbols; DELETE FROM imports; DELETE FROM calls; "
                         "DELETE FROM nodes; DELETE FROM edges; DELETE FROM bindings; DELETE FROM tags; "
                         "DELETE FROM globals; DELETE FROM refs; DELETE FROM tag_uses; DELETE FROM navs; DELETE FROM css_uses; DELETE FROM cochanges; "
                         "DELETE FROM meta;")
    _set_meta(con, "schema", SCHEMA)
    return con


def _meta(con, key):
    row = con.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row[0] if row else None


def _set_meta(con, key, value):
    con.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)", (key, str(value)))


def lang_of(path):
    if path.endswith(SKIP_SUFFIXES):
        return None
    if path.endswith(".d.ts"):
        return "typescript"
    return LANG_EXT.get(PurePosixPath(path).suffix.lower())


def is_test(path):
    p = PurePosixPath(path)
    name = p.name.lower()
    return (any(part.lower() in TEST_DIRS for part in p.parts[:-1])
            or ".test." in name or ".spec." in name
            or name.startswith("test_") or name.endswith("_test" + p.suffix.lower()))


def list_source_files(root):
    from uccif_lib.detect import list_files  # shared skip rules
    out = set()
    for f in list_files(root):
        f = f.replace(os.sep, "/")
        # git ls-files still lists tracked files deleted from the working tree
        if lang_of(f) and os.path.isfile(str(root / f)):
            out.add(f)
    return sorted(out)


def ctags_binary():
    exe = shutil.which("ctags") or shutil.which("universal-ctags")
    if not exe:
        return None
    try:
        out = subprocess.run([exe, "--version"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    return exe if "Universal Ctags" in out.stdout else None


def symbol_tool(exe=None):
    """Human-readable list of what extracts symbols right now, best first."""
    parts = []
    if any(ts_parse.availability().values()):
        parts.append("tree-sitter")
    if exe:
        parts.append("universal-ctags")
    return "+".join(parts + ["regex"])


# ---- parsing --------------------------------------------------------------------

def _script_part(text, lang):
    """For .vue/.svelte keep line numbers but blank everything outside <script>."""
    if lang not in ("vue", "svelte"):
        return text
    out, inside = [], False
    for line in text.split("\n"):
        if re.match(r"\s*<script\b", line):
            inside = True
            out.append("")
            continue
        if re.match(r"\s*</script>", line):
            inside = False
        out.append(line if inside else "")
    return "\n".join(out)


def regex_symbols(text, lang):
    fam = LANG_FAMILY.get(lang)
    rules = SYMBOL_RES.get(fam, [])
    text = _script_part(text, lang)
    found, scope_stack = [], []
    for no, line in enumerate(text.split("\n"), 1):
        if len(line) > 400:
            continue
        for kind, rx in rules:
            m = rx.match(line)
            if not m:
                continue
            if fam == "python":
                indent, name = len(m.group(1).expandtabs(4)), m.group(2)
                while scope_stack and scope_stack[-1][0] >= indent:
                    scope_stack.pop()
                scope = scope_stack[-1][1] if scope_stack else None
                if kind == "function" and scope:
                    kind = "method"
                if kind == "class":
                    scope_stack.append((indent, name))
            else:
                name, scope = m.group(1), None
            if name in KEYWORDS:
                continue
            found.append((name, kind, no, scope))
            break
    if lang in ("vue", "svelte"):
        found.append((None, "component", 1, None))  # name filled in by caller
    return found


def ctags_symbols(exe, root, paths):
    """{path: [(name, kind, line, scope)]} for files ctags understood."""
    if not paths:
        return {}
    try:
        out = subprocess.run(
            [exe, "--output-format=json", "--fields=+nKZ", "--extras=-F", "-f", "-", "-L", "-"],
            cwd=str(root), input="\n".join(paths), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    except (OSError, subprocess.SubprocessError):
        return {}
    res = {}
    for line in out.stdout.splitlines():
        try:
            t = json.loads(line)
        except ValueError:
            continue
        if t.get("_type") != "tag" or not t.get("line"):
            continue
        p = t.get("path", "").replace(os.sep, "/")
        res.setdefault(p, []).append((t["name"], t.get("kind", "?"), int(t["line"]), t.get("scope")))
    return res


def raw_imports(text, lang, lines=None):
    """Import strings found by regex. If `lines` is a dict it receives {raw: first line}."""
    fam = LANG_FAMILY.get(lang)
    rxs = IMPORT_RES.get(fam, [])
    seen = []
    for rx in rxs:
        for m in rx.finditer(text):
            v = m.group(1)
            if v and v not in seen:
                seen.append(v)
                if lines is not None:
                    lines[v] = text.count("\n", 0, m.start(1)) + 1
    return seen[:200]


# ---- build / update ---------------------------------------------------------------

def _read(root, rel):
    try:
        data = (root / rel).read_bytes()
    except OSError:
        return None, None
    if b"\0" in data[:8000]:
        return None, None
    return data, data.decode("utf-8", errors="replace")


def update(project, full=False, wait=10.0, paths=None):
    """Incremental refresh. Returns stats dict, or None if another process holds the lock.

    `paths` limits the work to those repo-relative files (used after an Edit, where
    a full stat pass over a big repo would be wasted); otherwise every file is checked.
    """
    try:
        with file_lock(db_path(project).with_name("index.lock"), timeout=wait, stale=600):
            return _update(project, full, paths)
    except LockTimeout:
        return None


def _update(project, full, only=None, force=()):
    t0 = time.time()
    root = project.root
    con = connect(project)
    if full:
        con.executescript("DELETE FROM files; DELETE FROM symbols; DELETE FROM imports; DELETE FROM calls; "
                          "DELETE FROM nodes; DELETE FROM edges; DELETE FROM bindings; DELETE FROM tags; "
                          "DELETE FROM globals; DELETE FROM refs; DELETE FROM tag_uses; DELETE FROM navs; "
                          "DELETE FROM css_uses;")
    known = {r[0]: (r[1], r[2], r[3]) for r in con.execute("SELECT path, size, mtime, hash FROM files")}
    if only is not None:
        only = {p.replace(os.sep, "/") for p in only if lang_of(p.replace(os.sep, "/"))}
        present = {p for p in only if os.path.isfile(str(root / p))}
        current = sorted(set(known) - only | present)
        removed = sorted(p for p in only - present if p in known)
        check = sorted(present)
    else:
        current = list_source_files(root)
        cur_set = set(current)
        removed = [p for p in known if p not in cur_set]
        check = current
    changed = []
    for rel in check:
        try:
            st = os.stat(str(root / rel))
        except OSError:
            continue
        old = known.get(rel)
        if old and old[0] == st.st_size and abs((old[1] or 0) - st.st_mtime) < 1e-6 and rel not in force:
            continue
        changed.append((rel, st))

    exe = ctags_binary()
    tool = symbol_tool(exe)
    to_parse = []
    for rel, st in changed:
        if st.st_size > MAX_BYTES:
            continue
        data, text = _read(root, rel)
        if data is None:
            continue
        h = hashlib.sha1(data).hexdigest()
        old = known.get(rel)
        if old and old[2] == h and rel not in force:
            con.execute("UPDATE files SET mtime=? WHERE path=?", (st.st_mtime, rel))
            continue
        to_parse.append((rel, st, h, text))

    # symbol sources, best first: tree-sitter (optional) -> universal-ctags -> regex
    ast, tpl_tags, tpl_uses, tpl_classes = {}, {}, {}, {}
    for rel, _, _, text in to_parse:
        lang = lang_of(rel)
        res = ts_parse.parse(_script_part(text, lang), rel, lang)
        if res is not None:
            if lang == "vue":  # template: component tags and the functions it calls
                tpl = vue_template.parse(text)
                if tpl:
                    stem = PurePosixPath(rel).stem
                    res = (res[:2] + (res[2] + [(stem, n, o, ln) for n, o, ln in tpl.calls],) + res[3:8]
                           + (res[8] + [(stem, o, pr, ln) for o, pr, ln in tpl.reads],)
                           + (res[9] + [(stem, ev, ln) for ev, ln in tpl.emits],)
                           + (res[10] + [(stem, k, v, d, ln) for k, v, d, ln in tpl.navs],) + res[11:13]
                           + (res[13] + [(stem, n, rw, ln) for n, rw, ln in tpl.idents],) + res[14:])
                    tpl_tags[rel] = tpl.tags
                    tpl_uses[rel] = tpl.uses
                    tpl_classes[rel] = tpl.classes
            ast[rel] = res
    need_ctags = [r for r, _, _, _ in to_parse if r not in ast]
    tagged = ctags_symbols(exe, root, need_ctags) if exe and need_ctags else {}
    resolver = Resolver(current, root)
    for rel in removed:
        _drop(con, rel)
        _unresolve_incoming(con, rel)
    for rel, st, h, text in to_parse:
        _drop(con, rel)
        lang = lang_of(rel)
        if rel in ast:
            syms, precision = list(ast[rel][0]), "ast"
            if lang in ("vue", "svelte"):
                syms.append((None, "component", 1, None))
            raws, ilines = ast[rel][1], ast[rel][4]
            call_rows, ref_rows = _resolve_calls(rel, lang, ast[rel], resolver)
            herit_rows = _resolve_heritage(rel, lang, ast[rel], resolver)
            tag_rows = _resolve_tags(rel, lang, ast[rel], tpl_tags.get(rel, ()), resolver)
        else:
            call_rows, ilines, herit_rows, tag_rows, ref_rows = [], {}, [], [], []
            syms, precision = tagged.get(rel), "ctags"
            if not syms:
                syms, precision = regex_symbols(text, lang), "approx"
            raws = raw_imports(text, lang, ilines)
        stem = PurePosixPath(rel).stem
        scoped_classes = set()
        if lang in styles.STYLE_LANGS or lang in ("vue", "svelte"):  # CSS vars / classes (regex, always)
            css_syms, scoped_classes = styles.symbols(text, lang)
            syms = list(syms) + css_syms
        rows = [((n if n is not None else stem), k, rel, ln, (stem if sc is None and k in ("prop", "emit") else sc),
                 precision) for n, k, ln, sc in syms]
        con.executemany("INSERT INTO symbols VALUES (?,?,?,?,?,?)", rows)
        imps = [(rel, raw, resolver.resolve(rel, raw, lang), ilines.get(raw)) for raw in raws]
        con.executemany("INSERT INTO imports VALUES (?,?,?,?)", imps)
        con.executemany("INSERT INTO calls VALUES (?,?,?,?,?)", [r[:5] for r in call_rows])
        con.execute("INSERT INTO files VALUES (?,?,?,?,?,?,?)",
                    (rel, lang, st.st_size, st.st_mtime, h, int(is_test(rel)), len(rows)))
        _write_graph(con, rel, lang, rows, imps, call_rows, resolver, text, herit_rows, tag_rows, ref_rows,
                     {(m[0], m[1]): m[2] for m in ast[rel][6]} if rel in ast else {},
                     ast[rel][9] if rel in ast else (), tpl_uses.get(rel, ()),
                     ast[rel][10] if rel in ast else (),
                     _resolve_routes(rel, lang, ast[rel], resolver) if rel in ast else (),
                     styles.uses(text, lang) + [("class", c, ln) for c, ln in tpl_classes.get(rel, ())],
                     scoped_classes)
    # Derived edges (barrels, components, store members, CSS, variables ...) are recomputed from the
    # whole repo. On a big repo that would blow the post-Edit budget, so a one-file update (`only`)
    # skips it when the last run was slow and marks it stale; the next full-scan update (every query
    # does one first, and the hooks start one in the background) catches up. Direct edges are always
    # current.
    stale = False
    if to_parse or removed or full or _meta(con, "derived_stale") == "1":
        if only is not None and float(_meta(con, "derive_ms") or 0) > DERIVE_BUDGET_MS:
            _set_meta(con, "derived_stale", 1)
            stale = True
        else:
            t1 = time.time()
            _through_barrels(con)
            _derive_all(con)
            _set_meta(con, "derive_ms", int((time.time() - t1) * 1000))
            _set_meta(con, "derived_stale", 0)
        _set_meta(con, "updated_at", now_iso())
        _set_meta(con, "symbol_tool", tool)
        if full or not _meta(con, "built_at"):
            _set_meta(con, "built_at", now_iso())
    # D5: files that change together, from git history; recomputed only when HEAD moves, never in the
    # one-file update after an Edit (it stays a few ms)
    if only is None:
        cochanged = _refresh_cochanges(con, root, set(current))
    else:
        cochanged = False
    if cochanged and not stale:  # new history: the derived edges (co_changes among them) are rebuilt once
        _derive_all(con)
    # C3: a file that imports a path which did not exist when it was parsed keeps an unresolved import
    # (and calls through it). When new files appear, re-parse exactly the importers whose import now
    # resolves, once.
    rescue = set()
    cur_set = set(current)
    if not force and to_parse and cur_set - set(known):
        for src, raw in con.execute("SELECT DISTINCT src_path, detail FROM edges WHERE kind='imports' "
                                    "AND confidence='unresolved' AND via IS NULL").fetchall():
            if src in cur_set and resolver.resolve(src, raw, lang_of(src)):
                rescue.add(src)
    con.commit()
    con.close()
    extra = _update(project, False, only=rescue, force=rescue) if rescue else None
    if extra:
        to_parse = list(to_parse) + [None] * extra["parsed"]
    return {"files": len(current), "parsed": len(to_parse), "removed": len(removed),
            "ms": int((time.time() - t0) * 1000), "tool": tool, "derived_stale": stale}

# Language built-ins: calls to these are known (not repo code), so they are external, not leads.
PY_BUILTINS = frozenset(n for n in dir(__import__("builtins")) if not n.startswith("_"))
JS_GLOBALS = frozenset((
    "console", "Math", "JSON", "Object", "Array", "Promise", "Number", "String", "Boolean", "Date",
    "Symbol", "Reflect", "Intl", "window", "document", "globalThis", "navigator", "localStorage",
    "sessionStorage", "Error", "Map", "Set", "WeakMap", "RegExp", "URL", "BigInt",
    "setTimeout", "clearTimeout", "setInterval", "clearInterval", "requestAnimationFrame",
    "parseInt", "parseFloat", "isNaN", "isFinite", "fetch", "structuredClone", "queueMicrotask",
    "encodeURIComponent", "decodeURIComponent", "alert", "confirm"))


# Methods of built-in types (arrays, strings, maps, promises, the DOM, dicts, files, DB cursors ...). A call
# `x.map()` whose receiver we cannot place is `calls_ext` unless the repo defines a method of that name.
BUILTIN_METHODS = frozenset("""map filter reduce reduceRight forEach find findIndex findLast some every includes indexOf
lastIndexOf push pop shift unshift splice slice concat join split trim trimStart trimEnd toLowerCase toUpperCase
replace replaceAll match matchAll test exec toString toFixed toISOString toLocaleString toJSON substring substr
startsWith endsWith padStart padEnd charAt charCodeAt localeCompare sort reverse keys values entries has get set add
delete clear then catch finally flat flatMap fill at assign freeze fromEntries stringify parse addEventListener
removeEventListener querySelector querySelectorAll getElementById appendChild removeChild setAttribute getAttribute
preventDefault stopPropagation focus blur click remove closest getBoundingClientRect scrollTo scrollIntoView
setItem getItem removeItem resolve reject all allSettled race next call apply bind valueOf
append extend insert items copy update setdefault popitem count index sort strip lstrip rstrip format lower upper
encode decode isdigit isalpha splitlines startswith endswith read readline readlines write close seek flush
execute executemany fetchone fetchall fetchmany commit rollback cursor mkdir exists is_file is_dir read_text
write_text read_bytes write_bytes iterdir glob rglob relative_to with_suffix expanduser unlink rmdir joinpath
isoformat strftime total_seconds timestamp group groups groupdict finditer findall sub subn dumps loads dump load
add_argument add_parser parse_args set_defaults print_help getvalue acquire release put task_done join""".split())


# pytest's built-in fixtures, received as test parameters: their methods are pytest's, not the repo's.
PYTEST_FIXTURES = frozenset(("monkeypatch", "capsys", "capfd", "caplog", "tmp_path", "tmpdir", "request",
                             "recwarn", "pytestconfig", "tmp_path_factory", "mocker"))


def _builtin(lang, name, obj):
    if lang == "python":
        return (obj is None and name in PY_BUILTINS) or obj in PYTEST_FIXTURES
    return (obj if obj is not None else name) in JS_GLOBALS


def _bind_map(rel, lang, binds, resolver):
    """({local name: (repo file or None, name in that file)}, {names imported from packages})."""
    bound, pkg = {}, set()
    for name, (raw, orig) in binds.items():
        if not resolver.internal(raw, lang, rel):
            pkg.add(name)
        target = None
        if lang == "python" and orig not in ("*", "default"):
            # `from . import mod` / `from pkg import mod`: a submodule is a namespace (mod.func())
            sub = resolver.resolve(rel, (raw + orig) if raw.strip(".") == "" else (raw + "." + orig), lang)
            if sub is not None:
                bound[name] = (sub, "*")
                continue
        if target is None:
            target = resolver.resolve(rel, raw, lang)
        bound[name] = (target, orig)
    return bound, pkg


def _resolve_heritage(rel, lang, parsed, resolver):
    """[(class, base, kind, line, base file or None, external)] for extends / implements."""
    syms, binds, heritage = parsed[0], parsed[3], parsed[5]
    if not heritage:
        return []
    local = {n for n, k, _, _ in syms if n and k not in ("prop", "emit", "store_member")}
    bound, pkg = _bind_map(rel, lang, binds, resolver)
    rows = []
    for cls, base, kind, line in heritage:
        path, name, ext = None, base, False
        if "." in base:
            obj, _, rest = base.partition(".")
            name = rest.rsplit(".", 1)[-1]
            if obj in bound and bound[obj][1] == "*":
                path = bound[obj][0]
            ext = obj in pkg and path is None
        elif base in bound and bound[base][0]:
            path = bound[base][0]
            if bound[base][1] not in ("default", "*"):
                name = bound[base][1]
        elif base in local:
            path = rel
        elif base in pkg:
            ext = True
        elif _builtin(lang, base, None):
            ext = True
        rows.append((cls, name, kind, line, path, ext))
    return rows


def _pick(cands, caller):
    """The origin of a variable: the one declared in the same function, else the only one."""
    if not cands:
        return None
    same = [c for c in cands if c[0] == caller]
    pool = same or cands
    return pool[0] if len({c[1:3] for c in pool}) == 1 else None


def _var_origins(rel, parsed, bound, local):
    """Where local variables come from, so `store.add()` / `f.go()` / `const {a} = useX(); a()` can
    be tied to a definition. -> ({var: [(function, file, name)]}, {destructured local: [(function,
    file, name, member)]}, read refs for destructured members)."""
    var_of, destructured, refs = {}, {}, []
    origins = parsed[7] if len(parsed) > 7 else []

    def place(callee):
        if callee in bound and bound[callee][0]:
            orig = bound[callee][1]
            return bound[callee][0], callee if orig in ("default", "*") else orig
        if callee in local:
            return rel, callee
        return None

    for aliased in (False, True):  # storeToRefs(store) needs the variable it names resolved first
        for caller, kind, callee, alias, names, line in origins:
            if (alias is not None) != aliased:
                continue
            if alias is not None:
                src = _pick(var_of.get(alias), caller)
                found = (src[1], src[2]) if src else None
            else:
                found = place(callee)
            if not found:
                continue
            for local_name, member in names:
                if member is None:
                    var_of.setdefault(local_name, []).append((caller, found[0], found[1]))
                else:
                    destructured.setdefault(local_name, []).append((caller, found[0], found[1], member))
                    refs.append((caller, "read", member, line, found[0], found[1]))
    return var_of, destructured, refs


def _resolve_calls(rel, lang, parsed, resolver):
    """Best-effort: attach each call to the repo file defining its callee.
    Resolved through the file's own import bindings, or to this file when it defines the
    name itself (and for `this.x()` / `self.x()`). Anything else keeps callee_path NULL
    ("unresolved"): a lead to verify by reading, not a fact."""
    syms, calls, binds = parsed[0], parsed[2], parsed[3]
    local = {n for n, k, _, _ in syms if n and k not in ("prop", "emit", "store_member")}
    bound, pkg = _bind_map(rel, lang, binds, resolver)
    var_of, destructured, refs = _var_origins(rel, parsed, bound, local)
    emit_vars = {"emit"} | {nm for _, _, callee, _, names, _ in (parsed[7] if len(parsed) > 7 else ())
                            if callee == "defineEmits" for nm, _ in names}
    rows = []
    for caller, name, obj, line in calls:
        path, callee = None, name
        origin = _pick(var_of.get(obj), caller) if obj not in (None, "this") else None
        if origin is None and obj is None and name not in local:
            d = _pick(destructured.get(name), caller)
            if d:
                refs.append((caller, "call", d[3], line, d[1], d[2]))
                rows.append((rel, caller, name, None, line, False, True))
                continue
        if origin:
            refs.append((caller, "call", name, line, origin[1], origin[2]))
            rows.append((rel, caller, name, None, line, False, True))
            continue
        ext = ((name in pkg) if obj is None else (obj in pkg)) or (
            _builtin(lang, name, obj) and name not in local and name not in bound) or (
            obj is None and name in emit_vars and name not in local and name not in bound)
        if (not ext and name in BUILTIN_METHODS and name not in local and name not in bound
                and obj not in ("this", "self") and not (obj in bound and bound[obj][1] == "*")):
            # decided from the whole repo later (_derive_builtins): ext unless the repo defines such a method
            refs.append((caller, "builtin", name, line, None, None))
            rows.append((rel, caller, name, None, line, False, True))
            continue
        if obj is None:
            if name in bound and bound[name][0]:
                path = bound[name][0]
                if bound[name][1] not in ("default", "*"):
                    callee = bound[name][1]
            elif name in local:
                path = rel
        elif obj == "this":
            path = rel if name in local else None
        elif obj in bound and bound[obj][1] == "*":
            path = bound[obj][0]
        rows.append((rel, caller, callee, path, line, ext and path is None, False))
    for caller, obj, prop, line in (parsed[8] if len(parsed) > 8 else ()):
        origin = _pick(var_of.get(obj), caller)
        if origin:
            refs.append((caller, "read", prop, line, origin[1], origin[2]))
    seen_refs = set()
    local_vars = {n for n, k, _, sc in syms if n and k in ("variable", "ref", "constant") and sc is None}
    local_types = {n for n, k, _, sc in syms if n and k in ("interface", "type", "class", "enum")}
    for caller, name, rw, line in (parsed[13] if len(parsed) > 13 else ()):  # module variables / refs used
        kind = "vwrite" if rw == "w" else "vread"
        if name in local_vars and name not in bound:
            target = (rel, name)
        elif name in bound and bound[name][0] and bound[name][1] not in ("default", "*"):
            target = (bound[name][0], bound[name][1])
        else:
            continue
        if (caller, kind, target) not in seen_refs:
            seen_refs.add((caller, kind, target))
            refs.append((caller, kind, target[1], line, target[0], target[1]))
    for caller, name, line in (parsed[14] if len(parsed) > 14 else ()):  # type references
        if name in local_types and name not in bound:
            target = (rel, name)
        elif name in bound and bound[name][0] and bound[name][1] not in ("default", "*"):
            target = (bound[name][0], bound[name][1])
        else:
            continue
        if (caller, "type", target) not in seen_refs:
            seen_refs.add((caller, "type", target))
            refs.append((caller, "type", target[1], line, target[0], target[1]))
    for caller, name, how, line in (parsed[12] if len(parsed) > 12 else ()):  # f(handler): maybe a function
        if how == "this" or (name in local and name not in bound):
            refs.append((caller, "callback", name, line, rel, name))
        elif name in bound and bound[name][0] and bound[name][1] not in ("default", "*"):
            refs.append((caller, "callback", bound[name][1], line, bound[name][0], bound[name][1]))
    return rows, refs


_JS_IMPORT = re.compile(r"""\bimport\s+(?:type\s+)?(?:([\w$]+)\s*,?\s*)?(?:\{([^}]*)\}|\*\s*as\s+([\w$]+))?"""
                        r"""\s*from\s*['"]([^'"]+)['"]""")
_JS_REEXPORT = re.compile(r"""\bexport\s+(?:type\s+)?(?:\*\s*(?:as\s+([\w$]+)\s*)?|\{([^}]*)\}\s*)"""
                          r"""from\s*['"]([^'"]+)['"]""")
_PY_FROM = re.compile(r"^[ \t]*from\s+(\.*[\w.]*)\s+import\s+(\([^)]*\)|[^\n#]+)", re.M)


def _names(clause):
    """'a, b as c, type d' -> [(orig, local)]."""
    out = []
    for part in clause.replace("(", "").replace(")", "").replace("\\", "").split(","):
        part = part.strip()
        if part.startswith("type "):
            part = part[5:].strip()
        if not part:
            continue
        orig, _, local = part.partition(" as ")
        orig, local = orig.strip(), (local.strip() or orig.strip())
        if re.match(r"^[\w$*]+$", orig) and re.match(r"^[\w$*]+$", local):
            out.append((orig, local))
    return out


def bindings_of(text, lang, rel):
    """([(local name, exported name, raw, line)], [(raw, orig, exported as, line)]).
    The first list says which name in this file comes from which import; the second is what
    this file re-exports (barrels: `export * from`, `export { a as b } from`; for Python, every
    `from x import y` in an `__init__.py`)."""
    binds, rex = [], []
    if not text:
        return binds, rex
    fam = LANG_FAMILY.get(lang)
    src = _script_part(text, lang)
    line_of = lambda pos: src.count("\n", 0, pos) + 1  # noqa: E731
    if fam == "js":
        for m in _JS_IMPORT.finditer(src):
            default, named, ns, raw = m.groups()
            ln = line_of(m.start())
            if default:
                binds.append((default, "default", raw, ln))
            if ns:
                binds.append((ns, "*", raw, ln))
            for orig, local in _names(named or ""):
                binds.append((local, orig, raw, ln))
        for m in _JS_REEXPORT.finditer(src):
            ns, named, raw = m.groups()
            ln = line_of(m.start())
            if named is None:
                rex.append((raw, "*", ns or "*", ln))
            for orig, local in _names(named or ""):
                rex.append((raw, orig, local, ln))
    elif fam == "python":
        init = PurePosixPath(rel).name == "__init__.py"
        for m in _PY_FROM.finditer(src):
            raw, ln = m.group(1), line_of(m.start())
            for orig, local in _names(m.group(2)):
                binds.append((local, orig, raw, ln))
                if init:
                    rex.append((raw, orig, local if orig != "*" else "*", ln))
    return binds[:300], rex[:300]


def _through_barrels(con):
    """Derived edges that see through barrel files (index.ts re-exports, package __init__.py).

    `import { formatMoney } from '@/utils'` resolves to utils/index.ts; if that file only
    re-exports it, add an `imports` edge (and re-point calls) to the file that defines it,
    with `via` = the barrel. Recomputed from scratch after every update that changed
    anything, so it can never go stale; the direct edges to the barrel stay as they are."""
    con.execute("DELETE FROM edges WHERE via IS NOT NULL AND via NOT LIKE '~%'")
    rex = {}
    for src, dst, detail in con.execute("SELECT src_path, dst_path, detail FROM edges "
                                        "WHERE kind='re_exports' AND dst_path IS NOT NULL"):
        orig, _, name = detail.partition(" as ")
        rex.setdefault(src, []).append((dst, orig, name))
    if not rex:
        return
    defs = {}

    def names_in(path):
        if path not in defs:
            defs[path] = {r[0] for r in con.execute("SELECT name FROM nodes WHERE path=? AND kind<>'file'", (path,))}
        return defs[path]

    def find(path, name, seen):
        """(file, name) that really defines `name` as seen from `path`, or None."""
        if (path, name) in seen or len(seen) > 30:
            return None
        seen.add((path, name))
        if name in names_in(path):
            return path, name
        for dst, orig, alias in rex.get(path, ()):
            if alias == "*" and orig == "*":
                hit = find(dst, name, seen)
                if hit:
                    return hit
            elif alias == name:
                return (dst, name) if orig == "*" else (find(dst, orig, seen) or (dst, orig))
        return None

    new, seen_pairs = [], set()
    for barrel in rex:
        for f, raw, line in con.execute("SELECT src_path, detail, line FROM edges WHERE kind='imports' "
                                        "AND dst_path=? AND via IS NULL", (barrel,)).fetchall():
            for (orig,) in con.execute("SELECT orig FROM bindings WHERE path=? AND raw=?", (f, raw)).fetchall():
                if orig in ("*", "default"):
                    continue
                hit = find(barrel, orig, set())
                if hit and hit[0] not in (barrel, f) and (f, hit[0]) not in seen_pairs:
                    seen_pairs.add((f, hit[0]))
                    new.append((f, hit[0], "imports", line, "extracted", raw, f, hit[0], barrel))
        for sid, line, name, f, kind in con.execute(
                "SELECT src_id, line, detail, src_path, kind FROM edges WHERE kind IN ('calls','extends','implements') "
                "AND dst_path=? AND via IS NULL", (barrel,)).fetchall():
            if name in names_in(barrel):
                continue
            hit = find(barrel, name, set())
            if hit and hit[0] != barrel:
                r = con.execute("SELECT id FROM nodes WHERE path=? AND name=? AND kind<>'file' LIMIT 1",
                                hit).fetchone()
                dst = r[0] if r else hit[0]
                new.append((sid, dst, kind, line, "extracted", hit[1], f, hit[0], barrel))
                if kind == "calls" and is_test(f):
                    new.append((sid, dst, "tests", line, "extracted", hit[1], f, hit[0], barrel))
    con.executemany("INSERT INTO edges VALUES (?,?,?,?,?,?,?,?,?)", new)


COCHANGE_COMMITS = 300
COCHANGE_MAX_FILES = 30  # bigger commits (formatting, renames, vendoring) say nothing about coupling
COCHANGE_MIN = 2
COCHANGE_RATIO = 0.3


def _refresh_cochanges(con, root, files):
    """Rebuild the cochanges table from `git log` when HEAD changed. -> True if it was rebuilt."""
    try:
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(root), capture_output=True, text=True,
                              timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return False
    if not head or _meta(con, "cochange_head") == head:
        return False
    try:
        out = subprocess.run(["git", "log", "--no-merges", "-n", str(COCHANGE_COMMITS), "--name-only",
                              "--format=@@%H"], cwd=str(root), capture_output=True, text=True, encoding="utf-8",
                             errors="replace", timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    changes, pairs = Counter(), Counter()
    for block in out.split("@@")[1:]:
        names = sorted({ln.strip() for ln in block.splitlines()[1:] if ln.strip() in files})
        if not names or len(names) > COCHANGE_MAX_FILES:
            continue
        changes.update(names)
        for i, a in enumerate(names):
            for b in names[i + 1:]:
                pairs[(a, b)] += 1
    rows = []
    for (a, b), n in pairs.items():
        ratio = n / float(min(changes[a], changes[b]))
        if n >= COCHANGE_MIN and ratio >= COCHANGE_RATIO:
            rows += [(a, b, n, ratio), (b, a, n, ratio)]
    con.execute("DELETE FROM cochanges")
    con.executemany("INSERT INTO cochanges VALUES (?,?,?,?)", rows)
    _set_meta(con, "cochange_head", head)
    return True


def _derive_cochanges(con):
    """co_changes edges (inferred) from the cached git-history table, for files still in the index."""
    con.execute("INSERT INTO edges SELECT c.a, c.b, 'co_changes', NULL, 'inferred', "
                "c.n || ' commits (' || CAST(ROUND(c.ratio * 100) AS INTEGER) || '%)', c.a, c.b, '~git' "
                "FROM cochanges c JOIN files fa ON fa.path=c.a JOIN files fb ON fb.path=c.b")


def _derive_all(con):
    """Edges that depend on other files' contents, recomputed from scratch (`via` starts with '~')."""
    con.execute("DELETE FROM edges WHERE via LIKE '~%'")
    _derive_components(con)
    _derive_links(con)
    _derive_navs(con)
    _derive_members(con)
    _derive_callbacks(con)
    _derive_builtins(con)
    _derive_css(con)
    _derive_vars(con)
    _derive_cochanges(con)
    _derive_uses(con)


def _find_def(con, path, name, kinds, cache, depth=0):
    """(node id, file) defining top-level `name` of one of `kinds` in `path`, following re-exports
    (barrels) a few levels; None if not found."""
    key = (path, name, kinds)
    if key in cache:
        return cache[key]
    hit = con.execute("SELECT id, path FROM nodes WHERE path=? AND name=? AND kind IN %s AND scope IS NULL "
                      "LIMIT 1" % _in(kinds), (path, name) + tuple(kinds)).fetchone()
    if hit is None and depth < 4:
        for dst, detail in con.execute("SELECT dst_path, detail FROM edges WHERE kind='re_exports' AND src_path=? "
                                       "AND dst_path IS NOT NULL", (path,)).fetchall():
            orig, _, alias = detail.partition(" as ")
            if alias == name or (orig == "*" and alias == "*"):
                hit = _find_def(con, dst, name if orig == "*" else orig, kinds, cache, depth + 1)
                if hit:
                    break
    cache[key] = hit
    return hit


def _derive_vars(con):
    """references_type (a type used in a signature, annotation or generic) and reads / writes of
    module-level variables and top-level refs of <script setup>, all extracted: parameters, locals,
    catch / for-of variables, v-for aliases and slot props that shadow a name are left out when the
    file is parsed. One edge per user and target."""
    new, seen, cache = [], set(), {}
    spec = {"type": ("references_type", ("interface", "type", "class", "enum"), "extracted"),
            "vread": ("reads", ("variable", "ref", "constant"), "extracted"),
            "vwrite": ("writes", ("variable", "ref", "constant"), "extracted")}
    for sid, sp, kind, member, line, op in con.execute(
            "SELECT src_id, src_path, kind, member, line, origin_path FROM refs WHERE kind IN ('type','vread','vwrite') "
            "ORDER BY src_path, line").fetchall():
        ekind, kinds, conf = spec[kind]
        hit = _find_def(con, op, member, kinds, cache)
        if hit and (sid, hit[0], ekind) not in seen and hit[0] != sid:
            seen.add((sid, hit[0], ekind))
            new.append((sid, hit[0], ekind, line, conf, member, sp, hit[1], "~var"))
    con.executemany("INSERT INTO edges VALUES (?,?,?,?,?,?,?,?,?)", new)


def _derive_css(con):
    """uses_css_var / defines_css_var (`var(--x)`, `setProperty('--x')`) to every definition of the
    variable (extracted; none found: an unresolved lead), and uses_class (a template class to a
    selector of the same name, inferred): the component's own <style> first, otherwise selectors in
    stylesheets and unscoped <style> blocks. Classes with no selector (utility CSS) add nothing."""
    uses_ = con.execute("SELECT path, src_id, kind, name, line FROM css_uses").fetchall()
    if not uses_:
        return
    var_defs, cls_defs = {}, {}
    for nid, name, path in con.execute("SELECT id, name, path FROM nodes WHERE kind='css_var'"):
        var_defs.setdefault(name, []).append((nid, path))
    for nid, name, path, det in con.execute("SELECT id, name, path, detail FROM nodes WHERE kind='css_class'"):
        cls_defs.setdefault(name, []).append((nid, path, det))
    new, seen = [], set()
    for path, sid, kind, name, line in uses_:
        if kind == "class":
            defs = cls_defs.get(name, [])
            own = [d for d in defs if d[1] == path]
            for nid, dpath, _ in (own or [d for d in defs if d[2] != "scoped"])[:3]:
                if (sid, nid, line) not in seen:
                    seen.add((sid, nid, line))
                    new.append((sid, nid, "uses_class", line, "inferred", name, path, dpath, "~css"))
            continue
        ekind = "defines_css_var" if kind == "define" else "uses_css_var"
        defs = sorted(var_defs.get(name, []), key=lambda d: d[1] != path)
        if not defs:
            new.append((sid, None, ekind, line, "unresolved", name, path, None, "~css"))
        for nid, dpath in defs[:5]:
            if (sid, nid, line, ekind) not in seen:
                seen.add((sid, nid, line, ekind))
                new.append((sid, nid, ekind, line, "extracted", name, path, dpath, "~css"))
    con.executemany("INSERT INTO edges VALUES (?,?,?,?,?,?,?,?,?)", new)


def _derive_callbacks(con):
    """passes_callback: a function handed to another call (`watch(src, sync)`, `onMounted(init)`,
    `arr.map(this.fmt)`, `Thread(target=worker)`). Identifiers that are not functions are dropped."""
    new = []
    for sid, sp, member, line, op in con.execute("SELECT src_id, src_path, member, line, origin_path FROM refs "
                                                 "WHERE kind='callback'").fetchall():
        hit = con.execute("SELECT id FROM nodes WHERE path=? AND name=? AND kind IN ('function','method') "
                          "AND id<>? LIMIT 1", (op, member, sid)).fetchone()
        if hit:
            new.append((sid, hit[0], "passes_callback", line, "extracted", member, sp, op, "~cb"))
    con.executemany("INSERT INTO edges VALUES (?,?,?,?,?,?,?,?,?)", new)


def _derive_builtins(con):
    """A call to a built-in method on a receiver we could not place (`items.map()`, `cur.execute()`):
    external, unless some file of the repo defines a function or method with that name, in which
    case it stays an unresolved lead."""
    defined, new = {}, []
    for sid, sp, member, line in con.execute("SELECT src_id, src_path, member, line FROM refs "
                                             "WHERE kind='builtin'").fetchall():
        if member not in defined:
            defined[member] = bool(con.execute("SELECT 1 FROM nodes WHERE name=? AND kind IN ('function','method') "
                                               "LIMIT 1", (member,)).fetchone())
        if defined[member]:
            new.append((sid, None, "calls", line, "unresolved", member, sp, None, "~builtin"))
        else:
            new.append((sid, None, "calls_ext", line, "extracted", member, sp, None, "~builtin"))
    con.executemany("INSERT INTO edges VALUES (?,?,?,?,?,?,?,?,?)", new)


PINIA_BUILTINS = ("$patch", "$reset", "$state", "$subscribe", "$onAction", "$dispose", "$id")


def _base_chain(con, class_id, depth=5):
    """Ids of the classes `class_id` extends, nearest first (resolved edges only)."""
    out, cur = [], [class_id]
    for _ in range(depth):
        nxt = [r[0] for c in cur for r in con.execute(
            "SELECT dst_id FROM edges WHERE src_id=? AND kind='extends' AND dst_id IS NOT NULL", (c,))]
        nxt = [n for n in nxt if n not in out]
        if not nxt:
            break
        out += nxt
        cur = nxt
    return out


def _resolve_routes(rel, lang, parsed, resolver):
    """[(path, line, component file or None, has a component, component name)] of a router config."""
    routes = parsed[11] if len(parsed) > 11 else ()
    if not routes:
        return []
    bound, _ = _bind_map(rel, lang, parsed[3], resolver)
    rows = []
    for full, _name, comp, line in routes:
        if comp is None:
            rows.append((full, line, None, False, None))
        elif comp[0] == "import":
            cpath = resolver.resolve(rel, comp[1], lang)
            rows.append((full, line, cpath, True, PurePosixPath(cpath).stem if cpath else None))
        else:
            cpath, orig = bound.get(comp[1], (None, None))
            rows.append((full, line, cpath, True, (PurePosixPath(cpath).stem if cpath and cpath.endswith(".vue")
                                                   else orig) if cpath else None))
    return rows


def _route_regex(path):
    parts = []
    for seg in path.strip("/").split("/"):
        if "(" in seg or "*" in seg:
            parts.append(".*")
        elif seg.startswith(":"):
            parts.append("[^/]*" if seg.endswith(("?", "*")) else "[^/]+")
        else:
            parts.append(re.escape(seg))
    return re.compile("^/" + "/".join(parts) + "/?$")


def _derive_navs(con):
    """navigates_to: `router.push('/x')`, `router.push({ name })`, `<RouterLink to>` tied to the route
    they open. Exact path or name: extracted; a path that only fits a pattern (`/trip/:id`) or has
    a dynamic part: inferred; no route: an unresolved lead. External URLs and relative targets are
    ignored."""
    routes = con.execute("SELECT id, name, path, detail FROM nodes WHERE kind='route'").fetchall()
    if not routes:
        return
    regexes = [(_route_regex(r[1]), r) for r in routes]
    new = []
    for sid, sp, line, kind, value, dyn in con.execute("SELECT src_id, src_path, line, kind, value, dynamic "
                                                      "FROM navs").fetchall():
        hit, conf = None, "extracted"
        if kind == "name":
            hit = next((r for r in routes if r[3] == value), None)
        else:
            if not value.startswith("/"):
                continue
            v = re.split(r"[?#]", value)[0]
            v = v if dyn else (v.rstrip("/") or "/")  # a dynamic prefix keeps its trailing slash
            if not dyn:
                hit = next((r for r in routes if r[1].rstrip("/") == v or (r[1] == "/" and v == "/")), None)
            if hit is None:
                sample = v + ("x" if dyn else "")
                # catch-all routes (`/:pathMatch(.*)*`) never count: a path only they accept has no real route
                cands = [r for rx, r in regexes if rx.match(sample) and "(" not in r[1] and "*" not in r[1]]
                hit = (cands or [None])[0]
                conf = "inferred"
        if hit:
            new.append((sid, hit[0], "navigates_to", line, conf, value, sp, hit[2], "~nav"))
        else:
            new.append((sid, None, "navigates_to", line, "unresolved", value, sp, None, "~nav"))
    con.executemany("INSERT INTO edges VALUES (?,?,?,?,?,?,?,?,?)", new)


def _derive_links(con):
    """passes_prop / listens: what a parent hands to a component tag (`:title=`, `@toggle-theme=`),
    tied to the prop / emit the child declares. Needs the final `renders` edges, so it runs after
    them. Attributes the child does not declare (class, native events, fallthrough) add nothing."""
    declared = {}
    new = []
    for path, tag, tline, kind, name, aline in con.execute(
            "SELECT path, tag, line, kind, name, attr_line FROM tag_uses").fetchall():
        r = con.execute("SELECT src_id, dst_path FROM edges WHERE kind='renders' AND src_path=? AND detail=? AND "
                        "line=? AND dst_path IS NOT NULL ORDER BY confidence='extracted' DESC LIMIT 1",
                        (path, tag, tline)).fetchone()
        if not r:
            continue
        src, dst = r
        if dst not in declared:
            declared[dst] = {}
            for nid, nkind, nname in con.execute("SELECT id, kind, name FROM nodes WHERE path=? AND kind IN "
                                                 "('prop','emit')", (dst,)):
                declared[dst][(nkind, vue_template.norm(nname))] = nid
        hit = declared[dst].get(("prop" if kind == "prop" else "emit", vue_template.norm(name)))
        if hit:
            new.append((src, hit, "passes_prop" if kind == "prop" else "listens", aline, "extracted", name, path,
                        dst, "~link"))
    con.executemany("INSERT INTO edges VALUES (?,?,?,?,?,?,?,?,?)", new)


def _derive_members(con):
    """Calls and reads on a variable whose origin is known (`const s = useStore(); s.add()`,
    `const f = new Foo(); f.go()`, `const {a} = useX(); a()`), tied to the member they hit:
    Pinia state/getter/action (calls_action / reads_state, extracted), class methods (also through
    base classes), or a function returned by a composable (inferred)."""
    refs = con.execute("SELECT src_id, src_path, kind, member, line, origin_path, origin_name FROM refs "
                       "WHERE kind IN ('call','read')").fetchall()
    new, defined = [], {}

    def unknown(sid, member, line, sp):
        """A method we could not tie to the origin: a built-in one (`con.execute()` on what
        `sqlite3.connect()` returned) is external unless the repo defines it; else a lead."""
        if member in BUILTIN_METHODS:
            if member not in defined:
                defined[member] = bool(con.execute("SELECT 1 FROM nodes WHERE name=? AND kind IN "
                                                   "('function','method') LIMIT 1", (member,)).fetchone())
            if not defined[member]:
                new.append((sid, None, "calls_ext", line, "extracted", member, sp, None, "~member"))
                return
        new.append((sid, None, "calls", line, "unresolved", member, sp, None, "~member"))
    for sid, sp, kind, member, line, op, on in refs:
        o = con.execute("SELECT id, kind FROM nodes WHERE path=? AND name=? AND kind<>'file' AND scope IS NULL "
                        "ORDER BY kind='store' DESC, kind='class' DESC LIMIT 1", (op, on)).fetchone()

        def edge(k, dst, dpath, conf):
            new.append((sid, dst, k, line, conf, member, sp, dpath, "~member"))
            if k in ("calls", "calls_action") and is_test(sp):
                new.append((sid, dst, "tests", line, conf, member, sp, dpath, "~member"))

        if o and o[1] == "store":
            mem = con.execute("SELECT id, detail FROM nodes WHERE path=? AND scope=? AND name=? AND "
                              "kind='store_member'", (op, on, member)).fetchone()
            if mem:
                edge("calls_action" if mem[1] == "action" and kind == "call" else "reads_state"
                     if mem[1] != "action" else "calls_action", mem[0], op, "extracted")
            elif member in PINIA_BUILTINS:
                if kind == "call":
                    new.append((sid, None, "calls_ext", line, "extracted", member, sp, None, "~member"))
            elif kind == "call":
                unknown(sid, member, line, sp)
        elif o and o[1] == "class" and kind == "call":
            found = None
            for cid in [o[0]] + _base_chain(con, o[0]):
                cpath, _, cname = cid.partition("#")
                found = con.execute("SELECT id, path FROM nodes WHERE path=? AND scope=? AND name=? "
                                    "AND kind='method'", (cpath, cname, member)).fetchone()
                if found:
                    break
            if found:
                edge("calls", found[0], found[1], "extracted")
            else:
                unknown(sid, member, line, sp)
        elif kind == "call":
            hit = con.execute("SELECT id FROM nodes WHERE path=? AND name=? AND kind IN "
                              "('function','variable','constant','method') AND id<>? LIMIT 1",
                              (op, member, o[0] if o else "")).fetchone() if o else None
            if hit:
                edge("calls", hit[0], op, "inferred")
            else:
                unknown(sid, member, line, sp)
    con.executemany("INSERT INTO edges VALUES (?,?,?,?,?,?,?,?,?)", new)


def _derive_uses(con):
    """uses_store / uses_composable: a call whose target is a Pinia store or a `useXxx` function."""
    for kind, cond in (("uses_store", "n.kind='store'"), ("uses_composable", "n.kind='function' AND "
                                                                     "n.name GLOB 'use[A-Z]*'")):
        con.execute("INSERT INTO edges SELECT e.src_id, e.dst_id, '%s', e.line, 'extracted', e.detail, "
                    "e.src_path, e.dst_path, '~uses' FROM edges e JOIN nodes n ON n.id=e.dst_id "
                    "WHERE e.kind='calls' AND %s" % (kind, cond))


def _derive_components(con):
    """`renders` edges for tags the template's own imports did not explain: components
    registered globally (`app.component('BaseButton', BaseButton)`: extracted), or a single
    .vue file named like the tag (inferred); otherwise an unresolved lead. Recomputed from
    scratch after every update that changed anything (via starts with '~')."""
    tags = con.execute("SELECT path, tag, line FROM tags").fetchall()
    if not tags:
        return
    glob = {}
    for name, target in con.execute("SELECT name, target FROM globals WHERE target IS NOT NULL ORDER BY path"):
        glob.setdefault(vue_template.norm(name), target)
    by_name = {}
    for (p,) in con.execute("SELECT path FROM files WHERE lang='vue'"):
        by_name.setdefault(vue_template.norm(PurePosixPath(p).stem), []).append(p)
    comps = {r[0] for r in con.execute("SELECT id FROM nodes WHERE kind='component'")}
    new = []
    for path, tag, line in tags:
        key = vue_template.norm(tag)
        src = _sym_id(path, PurePosixPath(path).stem, None)
        src = src if src in comps else path
        target = glob.get(key)
        if target and target != path:
            new.append((src, _dst_node(con, target, PurePosixPath(target).stem), "renders", line, "extracted", tag,
                        path, target, "~global"))
            continue
        cands = [c for c in by_name.get(key, ()) if c != path]
        if len(cands) == 1:
            new.append((src, _dst_node(con, cands[0], PurePosixPath(cands[0]).stem), "renders", line, "inferred",
                        tag, path, cands[0], "~name"))
        else:
            new.append((src, None, "renders", line, "unresolved", tag, path, None, "~none"))
    con.executemany("INSERT INTO edges VALUES (?,?,?,?,?,?,?,?,?)", new)


def _sym_id(path, name, scope, kind=None):
    """Stable node id. Props and emits get a kind prefix so `title` the prop and `title` the event
    (or a method) never collide."""
    pre = kind + ":" if kind in ("prop", "emit", "route", "css-class") else ""
    return "%s#%s%s%s" % (path, (scope + ".") if scope else "", pre, name)


def _caller_id(rel, caller, own):
    sid = _sym_id(rel, caller, None) if caller else rel
    if "." in (caller or ""):
        scope, _, nm = caller.rpartition(".")
        sid = _sym_id(rel, nm, scope)
    return sid if sid in own else rel


def _dst_node(con, cpath, name):
    """Node a reference to `name` in file `cpath` should point at (see _write_graph)."""
    hit = con.execute("SELECT id FROM nodes WHERE path=? AND name=? AND kind<>'file' LIMIT 1",
                      (cpath, name)).fetchone()
    if hit:
        return hit[0]
    if con.execute("SELECT 1 FROM nodes WHERE id=?", (cpath,)).fetchone():
        return cpath  # target already parsed and has no such symbol
    return _sym_id(cpath, name, None)  # target not parsed yet; corrected when it is


_COMPONENT_REG = re.compile(r"""\.component\(\s*['"]([\w-]+)['"]\s*,\s*([A-Za-z_$][\w$]*)\s*[,)]""")


def _resolve_tags(rel, lang, parsed, tags, resolver):
    """[(tag, line, status, file, name)] for component tags in a template. status: local (found
    through the script's imports), ext (a package or Vue/router built-in), unres (imported from a
    repo path we could not place), open (not imported here: global registration or file name)."""
    if not tags:
        return []
    bound, pkg = _bind_map(rel, lang, parsed[3], resolver)
    by_norm = {vue_template.norm(n): n for n in bound}
    rows = []
    for tag, line in tags:
        key = vue_template.norm(tag)
        name = by_norm.get(key)
        if name is None:
            rows.append((tag, line, "ext" if key in vue_template.VUE_BUILTINS else "open", None, None))
        elif bound[name][0]:
            rows.append((tag, line, "local", bound[name][0], bound[name][1]))
        elif name in pkg:
            rows.append((tag, line, "ext", None, None))
        else:
            rows.append((tag, line, "unres", None, None))
    return rows


def _write_graph(con, rel, lang, sym_rows, imps, call_rows, resolver, text="", herit_rows=(), tag_rows=(),
                 ref_rows=(), member_kinds=None, emit_rows=(), use_rows=(), nav_rows=(), route_rows=(),
                 css_rows=(), scoped_classes=()):
    """Mirror one parsed file into the unified graph: nodes (file + symbols) and edges.

    Node ids are stable (`path` for a file, `path#Scope.name` for a symbol) so edges from other
    files survive this file being re-parsed. Edge confidence: extracted = found through an
    explicit import/declaration; unresolved = a name we saw but could not place (dst NULL)."""
    member_kinds = member_kinds or {}
    nodes = [(rel, "file", PurePosixPath(rel).name, rel, 1, None, None, None, None)]
    for n, k, _, ln, sc, pr in sym_rows:
        nodes.append((_sym_id(rel, n, sc, k), k.replace("-", "_"), n, rel, ln, None, sc, pr,
                      member_kinds.get((sc, n)) if k in ("store_member", "route") else
                      ("scoped" if n in scoped_classes else None) if k == "css-class" else None))
    con.executemany("INSERT OR IGNORE INTO nodes VALUES (?,?,?,?,?,?,?,?,?)", nodes)
    edges = []
    own_ids = {nd[0] for nd in nodes}
    for nd in nodes[1:]:  # contains: file -> top-level symbol, class -> method
        scope = nd[6]
        box = _sym_id(rel, scope, None) if scope else rel
        edges.append((box if box in own_ids else rel, nd[0], "contains", nd[4], "extracted", nd[2], rel, rel, None))
    for src, raw, target, line in imps:
        if target:
            edges.append((rel, target, "imports", line, "extracted", raw, rel, target, None))
        elif resolver.internal(raw, lang, rel):  # looks like a repo file we could not place
            edges.append((rel, None, "imports", line, "unresolved", raw, rel, None, None))
        else:  # a package: fully known, just not in the repo
            edges.append((rel, None, "imports_ext", line, "extracted", raw, rel, None, None))
    own = {r[0] for r in con.execute("SELECT id FROM nodes WHERE path=?", (rel,))}
    for _, caller, callee, cpath, line, ext, handled in call_rows:
        sid = _caller_id(rel, caller, own)
        if handled:  # `store.add()` etc.: decided later from the origin of the variable (refs)
            continue
        if cpath:
            edges.append((sid, _dst_node(con, cpath, callee), "calls", line, "extracted", callee, rel, cpath, None))
        elif ext:  # a function from an installed package: fully known, just not in the repo
            edges.append((sid, None, "calls_ext", line, "extracted", callee, rel, None, None))
        else:
            edges.append((sid, None, "calls", line, "unresolved", callee, rel, None, None))
    for cls, name, kind, line, cpath, ext in herit_rows:
        sid = _sym_id(rel, cls, None)
        sid = sid if sid in own_ids else rel
        if cpath:
            edges.append((sid, _dst_node(con, cpath, name), kind, line, "extracted", name, rel, cpath, None))
        elif ext:
            edges.append((sid, None, kind + "_ext", line, "extracted", name, rel, None, None))
        else:
            edges.append((sid, None, kind, line, "unresolved", name, rel, None, None))
    comp = _sym_id(rel, PurePosixPath(rel).stem, None)
    comp = comp if comp in own_ids else rel
    emit_ids = {vue_template.norm(nd[2]): nd[0] for nd in nodes if nd[1] == "emit"}
    for caller, event, line in emit_rows:  # emit('save') / $emit('save') -> the declared emit
        dst = emit_ids.get(vue_template.norm(event))
        edges.append((_caller_id(rel, caller, own), dst, "emits", line, "extracted" if dst else "unresolved", event,
                      rel, rel if dst else None, None))
    con.executemany("INSERT INTO tag_uses VALUES (?,?,?,?,?,?)", [(rel,) + tuple(u) for u in use_rows])
    con.executemany("INSERT INTO css_uses VALUES (?,?,?,?,?)", [(rel, comp, k, n, ln) for k, n, ln in css_rows])
    con.executemany("INSERT INTO navs VALUES (?,?,?,?,?,?)",
                    [(_caller_id(rel, c, own), rel, ln, k, v, int(d)) for c, k, v, d, ln in nav_rows])
    for full, line, cpath, has_comp, cname in route_rows:  # route -> the component it shows
        rid = _sym_id(rel, full, None, "route")
        if rid not in own_ids or not has_comp:
            continue
        if cpath:
            edges.append((rid, _dst_node(con, cpath, cname), "routes_to", line, "extracted", full, rel, cpath, None))
        else:
            edges.append((rid, None, "routes_to", line, "unresolved", full, rel, None, None))
    con.executemany("INSERT INTO refs VALUES (?,?,?,?,?,?,?)",
                    [(_caller_id(rel, c, own), rel, k, m, ln, op, on) for c, k, m, ln, op, on in ref_rows])
    for tag, line, status, cpath, name in tag_rows:
        if status == "local":
            cname = PurePosixPath(cpath).stem if cpath.endswith(".vue") or name in ("default", "*") else name
            edges.append((comp, _dst_node(con, cpath, cname), "renders", line, "extracted", tag, rel, cpath, None))
        elif status == "ext":
            edges.append((comp, None, "renders_ext", line, "extracted", tag, rel, None, None))
        elif status == "unres":
            edges.append((comp, None, "renders", line, "unresolved", tag, rel, None, None))
        else:  # decided after all files are known (_derive_components)
            con.execute("INSERT INTO tags VALUES (?,?,?)", (rel, tag, line))
    if is_test(rel):  # tests: the symbols a test file calls, at function level
        edges += [(e[0], e[1], "tests", e[3], "extracted", e[5], rel, e[7], None)
                  for e in edges if e[2] == "calls" and e[7]]
    binds, rexports = bindings_of(text, lang, rel)
    con.executemany("INSERT INTO bindings VALUES (?,?,?,?,?)", [(rel,) + b for b in binds])
    if LANG_FAMILY.get(lang) == "js" and ".component(" in text:  # app.component('Name', Comp)
        by_local = {b[0]: b[2] for b in binds}
        for m in _COMPONENT_REG.finditer(text):
            raw = by_local.get(m.group(2))
            target = resolver.resolve(rel, raw, lang) if raw else None
            con.execute("INSERT INTO globals VALUES (?,?,?,?)",
                        (rel, m.group(1), target, text.count("\n", 0, m.start()) + 1))
    for raw, orig, name, line in rexports:
        target = resolver.resolve(rel, raw, lang)
        edges.append((rel, target, "re_exports", line, "extracted" if target else "unresolved",
                      "%s as %s" % (orig, name), rel, target, None))
    con.executemany("INSERT INTO edges VALUES (?,?,?,?,?,?,?,?,?)", edges)
    # edges from other files into this one: re-point to the symbol now defined here (by name),
    # or to the file when the symbol is gone / was guessed before this file was parsed
    con.execute("UPDATE edges SET dst_id=COALESCE((SELECT n.id FROM nodes n WHERE n.path=edges.dst_path "
                "AND n.name=edges.detail AND n.kind<>'file' LIMIT 1), dst_path) "
                "WHERE dst_path=? AND dst_id<>dst_path AND dst_id NOT IN (SELECT id FROM nodes WHERE path=?)",
                (rel, rel))


def _unresolve_incoming(con, rel):
    """A file was deleted: edges that pointed into it become unresolved instead of dangling."""
    con.execute("UPDATE edges SET dst_id=NULL, dst_path=NULL, confidence='unresolved' WHERE dst_path=?",
                (rel,))


def _drop(con, rel):
    con.execute("DELETE FROM bindings WHERE path=?", (rel,))
    con.execute("DELETE FROM tags WHERE path=?", (rel,))
    con.execute("DELETE FROM globals WHERE path=?", (rel,))
    con.execute("DELETE FROM refs WHERE src_path=?", (rel,))
    con.execute("DELETE FROM tag_uses WHERE path=?", (rel,))
    con.execute("DELETE FROM navs WHERE src_path=?", (rel,))
    con.execute("DELETE FROM css_uses WHERE path=?", (rel,))
    con.execute("DELETE FROM nodes WHERE path=?", (rel,))
    con.execute("DELETE FROM edges WHERE src_path=?", (rel,))
    con.execute("DELETE FROM files WHERE path=?", (rel,))
    con.execute("DELETE FROM symbols WHERE path=?", (rel,))
    con.execute("DELETE FROM imports WHERE src=?", (rel,))
    con.execute("DELETE FROM calls WHERE src_path=?", (rel,))


def exists(project):
    return db_path(project).exists()


# ---- queries --------------------------------------------------------------------

def _norm(project, path):
    p = Path(path)
    if p.is_absolute():
        try:
            p = Path(os.path.realpath(str(p))).relative_to(project.root)
        except ValueError:
            return str(path).replace(os.sep, "/")
    return str(PurePosixPath(*p.parts)) if p.parts else str(path)


def _refs(project, name, limit=10):
    """(total files, [(path, count)]) of whole-word occurrences, via git grep."""
    if not re.match(r"^[\w$.-]+$", name):
        return 0, []
    try:
        out = subprocess.run(["git", "grep", "-I", "-w", "-c", "-F", "--", name],
                             cwd=str(project.root), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10)
    except (OSError, subprocess.SubprocessError):
        return 0, []
    if out.returncode not in (0, 1):
        return 0, []
    rows = []
    for line in out.stdout.splitlines():
        path, _, cnt = line.rpartition(":")
        if path and cnt.isdigit() and lang_of(path):
            rows.append((path, int(cnt)))
    rows.sort(key=lambda r: -r[1])
    return len(rows), rows[:limit]


CONFIDENCE = {"extracted": 2, "inferred": 1, "unresolved": 0}


def _conf_ok(min_confidence):
    """Confidence levels at or above `min_confidence` (default: everything that has a target)."""
    floor = CONFIDENCE.get(min_confidence or "inferred", 1)
    return [c for c, r in CONFIDENCE.items() if r >= max(floor, 1)]


def _in(values):
    return "(%s)" % ",".join("?" * len(values))


def dependents(con, rel):
    return [r[0] for r in con.execute(
        "SELECT DISTINCT src_path FROM edges WHERE kind='imports' AND dst_path=? ORDER BY src_path", (rel,))]


def tests_for(con, rel):
    """Test files that import `rel`, plus tests named after it (x.test.ts, test_x.py, ...)."""
    direct = [r[0] for r in con.execute(
        "SELECT DISTINCT e.src_path FROM edges e JOIN files f ON f.path=e.src_path "
        "WHERE e.kind='imports' AND e.dst_path=? AND f.is_test=1", (rel,))]
    direct += [r[0] for r in con.execute("SELECT DISTINCT src_path FROM edges WHERE kind='tests' AND dst_path=?",
                                         (rel,))]
    stem = PurePosixPath(rel).stem
    names = {stem + ".test", stem + ".spec", "test_" + stem, stem + "_test", stem}
    by_name = [r[0] for r in con.execute("SELECT path FROM files WHERE is_test=1 AND path<>?", (rel,))
               if PurePosixPath(r[0]).stem in names]
    return sorted(set(direct) | set(by_name))


def query_symbol(project, name):
    con = connect(project, write=False)
    defs = con.execute("SELECT name, kind, path, line, scope, precision FROM symbols WHERE name=? "
                       "ORDER BY kind='method', path LIMIT 12", (name,)).fetchall()
    note = ""
    if not defs:
        defs = con.execute("SELECT name, kind, path, line, scope, precision FROM symbols "
                           "WHERE lower(name)=lower(?) OR lower(name) LIKE lower(?) "
                           "ORDER BY length(name), path LIMIT 12", (name, name + "%")).fetchall()
        note = " (no exact match; showing case-insensitive/prefix matches)"
    lines = ["Definitions of %s%s:" % (name, note)]
    if not defs:
        lines.append("  none in index — search by behaviour (Grep) before concluding it is missing")
    for n, k, p, ln, sc, pr in defs:
        dep = len(dependents(con, p))
        lines.append("  %s:%d  %s %s%s%s%s" % (p, ln, k, n, (" in " + sc) if sc else "",
                                              "  [%d dependents]" % dep if dep else "",
                                              "  ~approx" if pr == "approx" else ""))
    lines.extend(_called_by(con, defs, QUERY_LINES - len(lines) - 2))
    lines.extend(_relations(con, defs, QUERY_LINES - len(lines) - 2))
    total, top = _refs(project, name)
    room = QUERY_LINES - len(lines) - 1  # header line
    if total and room >= 1:
        lines.append("Referenced (whole word) in %d files%s:" % (total, ", top 10" if total > 10 else ""))
        lines.extend("  %s (%d)" % (p, c) for p, c in top[:room])
    con.close()
    return lines[:QUERY_LINES]


def _called_by(con, defs, budget, cap=8):
    """'Called by' lines from the call edges (only files parsed with tree-sitter have calls)."""
    if budget < 3 or not defs:
        return []
    exact = {(n, p) for n, _, p, _, _, _ in defs}
    names = {n for n, _ in exact}
    sure, maybe = [], []
    for n in sorted(names):
        for cp, sp, sid, ln, conf in con.execute(
                "SELECT dst_path, src_path, src_id, line, confidence FROM edges WHERE kind IN ('calls', 'calls_action') "
                "AND detail=? ORDER BY src_path, line", (n,)):
            caller = sid[len(sp) + 1:] if sid.startswith(sp + "#") else None
            if conf == "unresolved":
                # same name, receiver unknown (e.g. `store.add()`); keep apart and mark
                maybe.append((sp, caller, ln))
            elif (n, cp) in exact:
                sure.append((sp, caller, ln))
    out = []
    for label, items in (("Called by", sure), ("Possibly called by (receiver unresolved)", maybe)):
        room = budget - len(out) - 1  # minus this section's header
        if not items or room < 1:
            continue
        shown = items[:min(cap, room)]
        out.append("%s (%d):" % (label, len(items)))
        out.extend("  %s:%d%s" % (sp, ln, (" in " + ss) if ss else "") for sp, ss, ln in shown)
        if len(items) > len(shown) and len(out) < budget:
            out.append("  ... +%d more" % (len(items) - len(shown)))
    return out


def _relations(con, defs, budget, cap=5):
    """Inheritance and test lines for the definitions found: what a class extends/implements,
    who extends/implements it, and which test files call it."""
    if budget < 3 or not defs:
        return []
    ids = [_sym_id(p, n, sc, k) for n, k, p, _, sc, _ in defs]
    mark = _in(ids)
    up = con.execute("SELECT kind, detail, dst_path, src_path, line FROM edges WHERE src_id IN %s AND kind IN "
                     "('extends','implements','extends_ext','implements_ext') ORDER BY line" % mark, ids).fetchall()
    down = con.execute("SELECT DISTINCT src_id, kind, src_path, line FROM edges WHERE dst_id IN %s AND kind IN "
                       "('extends','implements') ORDER BY src_path, line" % mark, ids).fetchall()
    renders = con.execute("SELECT detail, dst_path, confidence, line FROM edges WHERE src_id IN %s AND kind IN "
                          "('renders','renders_ext') ORDER BY line" % mark, ids).fetchall()
    used = con.execute("SELECT DISTINCT src_id, src_path, line, kind FROM edges WHERE dst_id IN %s AND kind IN "
                       "('reads_state','uses_store','uses_composable','passes_prop','listens','emits','navigates_to',"
                       "'passes_callback','uses_css_var','defines_css_var','uses_class','references_type','reads','writes') "
                       "ORDER BY src_path, line" % mark,
                       ids).fetchall()
    rendered = con.execute("SELECT DISTINCT src_id, src_path, line, confidence FROM edges WHERE dst_id IN %s AND "
                           "kind='renders' ORDER BY src_path, line" % mark, ids).fetchall()
    routed_to = con.execute("SELECT DISTINCT detail, dst_path, line, src_path FROM edges WHERE src_id IN %s AND "
                            "kind='routes_to' AND dst_path IS NOT NULL ORDER BY line" % mark, ids).fetchall()
    routed_by = con.execute("SELECT DISTINCT detail, src_path, line FROM edges WHERE dst_id IN %s AND "
                            "kind='routes_to' ORDER BY src_path, line" % mark, ids).fetchall()
    tested = con.execute("SELECT DISTINCT src_path, line FROM edges WHERE dst_id IN %s AND kind='tests' "
                         "ORDER BY src_path, line" % mark, ids).fetchall()
    sections = []
    if up:
        sections.append(("Extends / implements", [
            "%s %s%s" % (k.split("_")[0], d, "  (%s)" % (dp if dp else "external")) for k, d, dp, _, _ in up]))
    if down:
        sections.append(("Subclasses / implementations (%d)" % len(down), [
            "%s:%d  %s (%s)" % (sp, ln, sid.split("#", 1)[-1], k) for sid, k, sp, ln in down]))
    if routed_to:
        sections.append(("Routes to", ["%s  %s" % (d, dp) for d, dp, _, _ in routed_to]))
    if routed_by:
        sections.append(("Routed from (%d)" % len(routed_by), ["%s  (%s:%d)" % (d, sp, ln)
                                                               for d, sp, ln in routed_by]))
    if used:
        sections.append(("Used by (%d)" % len(used), [
            "%s:%d%s  (%s)" % (sp, ln, (" in " + sid[len(sp) + 1:]) if sid.startswith(sp + "#") else "",
                               k.replace("_", " ")) for sid, sp, ln, k in used]))
    if renders:
        sections.append(("Renders (%d)" % len(renders), [
            "<%s>  %s%s" % (d, dp or "(external / unresolved)", "  ~inferred" if c == "inferred" else "")
            for d, dp, c, _ in renders]))
    if rendered:
        sections.append(("Rendered by (%d)" % len(rendered), [
            "%s:%d  %s%s" % (sp, ln, sid.split("#", 1)[-1], "  ~inferred" if c == "inferred" else "")
            for sid, sp, ln, c in rendered]))
    if tested:
        sections.append(("Tested by (%d)" % len(tested), ["%s:%d" % (sp, ln) for sp, ln in tested]))
    out = []
    for title, items in sections:
        room = budget - len(out) - 1
        if room < 1:
            break
        shown = items[:min(cap, room)]
        out.append(title + ":")
        out.extend("  " + x for x in shown)
        if len(items) > len(shown) and len(out) < budget:
            out.append("  ... +%d more" % (len(items) - len(shown)))
    return out


def query_file(project, path):
    con = connect(project, write=False)
    rel = _norm(project, path)
    row = con.execute("SELECT lang, n_symbols, is_test FROM files WHERE path=?", (rel,)).fetchone()
    if not row:
        con.close()
        return ["%s is not in the index (not a source file, ignored, or new — retry after saving)." % rel]
    lines = ["%s  [%s%s, %d symbols]" % (rel, row[0], ", test" if row[2] else "", row[1])]
    syms = con.execute("SELECT name, kind, line FROM symbols WHERE path=? ORDER BY line LIMIT 12",
                       (rel,)).fetchall()
    if syms:
        lines.append("Symbols: " + ", ".join("%s %s:%d" % (k, n, ln) for n, k, ln in syms))
    imps = con.execute("SELECT raw, target FROM imports WHERE src=? LIMIT 12", (rel,)).fetchall()
    local = [t for _, t in imps if t]
    ext = [r for r, t in imps if not t]
    if local:
        lines.append("Imports (repo): " + ", ".join(local))
    if ext:
        lines.append("Imports (external): " + ", ".join(ext[:8]))
    deps = dependents(con, rel)
    lines.append("Imported by %d files%s" % (len(deps), (": " + ", ".join(deps[:10])) if deps else ""))
    tests = tests_for(con, rel)
    lines.append("Tests: " + (", ".join(tests[:8]) if tests else "none found"))
    co = con.execute("SELECT dst_path, detail FROM edges WHERE kind='co_changes' AND src_path=? "
                     "ORDER BY CAST(detail AS INTEGER) DESC, dst_path LIMIT 6", (rel,)).fetchall()
    if co:
        lines.append("Often changed with (git): " + ", ".join("%s [%s]" % c for c in co))
    con.close()
    return lines[:QUERY_LINES]


def query_tests_for(project, path):
    con = connect(project, write=False)
    rel = _norm(project, path)
    tests = tests_for(con, rel)
    con.close()
    return ["Tests for %s:" % rel] + (["  " + t for t in tests] or ["  none found"])


# ---- graph queries ----------------------------------------------------------------

MAX_DEPTH = 6
MAX_FILES = 300  # stop expanding the impact BFS beyond this many files


def _edge_text(con, src, dst):
    """Evidence that `src` depends on `dst`: 'src:LINE imports "raw"; calls f at src:LINE'."""
    bits, line = [], None
    r = con.execute("SELECT line, detail, via FROM edges WHERE kind='imports' AND src_path=? AND dst_path=? "
                    "ORDER BY via IS NOT NULL, line LIMIT 1", (src, dst)).fetchone()
    if r:
        line = r[0]
        bits.append("imports '%s'%s" % (r[1], (" via " + r[2]) if r[2] else ""))
    c = con.execute("SELECT line, detail, src_id FROM edges WHERE kind='calls' AND src_path=? AND dst_path=? "
                    "ORDER BY line LIMIT 1", (src, dst)).fetchone()
    if c:
        n = con.execute("SELECT count(*) FROM edges WHERE kind='calls' AND src_path=? AND dst_path=?",
                        (src, dst)).fetchone()[0]
        caller = c[2][len(src) + 1:] if c[2].startswith(src + "#") else None
        line = line or c[0]
        bits.append("calls %s at :%d%s%s" % (c[1], c[0], (" in " + caller) if caller else "",
                                              " (+%d more)" % (n - 1) if n > 1 else ""))
    for k, verb in (("calls_action", "calls store action"), ("reads_state", "reads store state"),
                    ("uses_store", "uses store"), ("uses_composable", "uses composable"),
                    ("routes_to", "routes to"), ("navigates_to", "navigates to"),
                    ("passes_callback", "passes callback"), ("uses_css_var", "uses CSS variable"),
                    ("defines_css_var", "sets CSS variable"), ("uses_class", "uses class"),
                    ("references_type", "uses type"), ("writes", "writes"), ("reads", "reads")):
        e = con.execute("SELECT line, detail FROM edges WHERE kind=? AND src_path=? AND dst_path=? "
                        "ORDER BY line LIMIT 1", (k, src, dst)).fetchone()
        if e:
            line = line or e[0]
            bits.append("%s %s at :%d" % (verb, e[1], e[0]))
    rn = con.execute("SELECT line, detail, via, confidence FROM edges WHERE kind='renders' AND src_path=? AND "
                     "dst_path=? ORDER BY line LIMIT 1", (src, dst)).fetchone()
    if rn:
        line = line or rn[0]
        how = {"~global": ", global registration", "~name": ", matched by file name"}.get(rn[2], "")
        bits.append("renders <%s> at :%d%s" % (rn[1], rn[0], how))
    return "%s%s  %s" % (src, (":%d" % line) if line else "", "; ".join(bits) or "depends on it")


DEFAULT_KINDS = ("imports", "calls", "renders", "calls_action", "reads_state", "uses_store", "uses_composable",
                 "routes_to", "navigates_to", "passes_callback", "uses_css_var", "defines_css_var", "uses_class",
                 "references_type", "reads", "writes")


def _users_of(con, rel, kinds=DEFAULT_KINDS, min_confidence=None):
    """Files that import or call into `rel` (over edges of `kinds` at or above `min_confidence`)."""
    conf = _conf_ok(min_confidence)
    out = {r[0] for r in con.execute(
        "SELECT DISTINCT src_path FROM edges WHERE dst_path=? AND kind IN %s AND confidence IN %s"
        % (_in(kinds), _in(conf)), (rel,) + tuple(kinds) + tuple(conf))}
    out.discard(rel)
    return sorted(out)


def _uses_of(con, rel, kinds=DEFAULT_KINDS, min_confidence=None):
    """Files that `rel` imports or calls into."""
    conf = _conf_ok(min_confidence)
    out = {r[0] for r in con.execute(
        "SELECT DISTINCT dst_path FROM edges WHERE src_path=? AND dst_path IS NOT NULL AND kind IN %s "
        "AND confidence IN %s" % (_in(kinds), _in(conf)), (rel,) + tuple(kinds) + tuple(conf))}
    out.discard(rel)
    return sorted(out)


def _impact_levels(con, rel, depth, kinds, min_confidence):
    level_of, parent, levels, truncated = {rel: 0}, {}, [], False
    frontier = [rel]
    for d in range(1, depth + 1):
        nxt = []
        for f in frontier:
            for u in _users_of(con, f, kinds, min_confidence):
                if u not in level_of:
                    if len(level_of) > MAX_FILES:
                        truncated = True
                        continue
                    level_of[u], parent[u] = d, f
                    nxt.append(u)
        if not nxt:
            break
        levels.append(sorted(nxt))
        frontier = nxt
    return levels, parent, truncated


def impact(project, path, depth=3, kinds=DEFAULT_KINDS, min_confidence=None):
    """Files affected by a change to `path`: BFS over who-imports / who-calls, level by level."""
    depth = max(1, min(int(depth), MAX_DEPTH))
    con = connect(project, write=False)
    rel = _norm(project, path)
    if not con.execute("SELECT 1 FROM files WHERE path=?", (rel,)).fetchone():
        con.close()
        return ["%s is not in the index (not a source file, ignored, or new — retry after saving)." % rel]
    hidden = 0
    if min_confidence is None:  # default: extracted edges; inferred ones only when nothing is certain
        levels, parent, truncated = _impact_levels(con, rel, depth, kinds, "extracted")
        if levels:
            loose = _impact_levels(con, rel, depth, kinds, "inferred")[0]
            hidden = len({f for lv in loose for f in lv} - {f for lv in levels for f in lv})
        else:
            levels, parent, truncated = _impact_levels(con, rel, depth, kinds, "inferred")
    else:
        levels, parent, truncated = _impact_levels(con, rel, depth, kinds, min_confidence)
    is_t = {r[0] for r in con.execute("SELECT path FROM files WHERE is_test=1")}
    affected = [f for lv in levels for f in lv]
    tests = sorted(({f for f in affected if f in is_t} | set(tests_for(con, rel))) - {rel})
    n_src = len([f for f in affected if f not in is_t])
    head = "Impact of %s (depth %d): %d files%s" % (rel, depth, n_src,
                                                   ", %d tests" % len(tests) if tests else "")
    lines = [head + (" — truncated at %d files" % MAX_FILES if truncated else "")]
    if hidden:
        lines.append("  +%d more files through inferred edges (--min-confidence inferred)" % hidden)
    if not affected:
        lines.append("  nothing imports or calls it (within the index)")
    budget = QUERY_LINES - len(lines) - (1 + min(len(tests), 5) if tests else 0)
    for i, lv in enumerate(levels, 1):
        src_files = [f for f in lv if f not in is_t]
        if not src_files:
            continue
        if budget < 2:
            lines.append("Level %d: %d more files not shown (query a dependent for its own impact)"
                         % (i, len(src_files)))
            budget -= 1
            continue
        lines.append("Level %d%s:" % (i, " (direct)" if i == 1 else ""))
        budget -= 1
        room = max(1, min(len(src_files), budget - (1 if len(levels) > i else 0)))
        if len(src_files) > room and room > 1:
            room -= 1  # keep a line for "... +N more"
        for f in src_files[:room]:
            via = "" if i == 1 else "  via " + parent[f]
            lines.append("  " + _edge_text(con, f, parent[f]) + via)
        budget -= room
        if len(src_files) > room:
            lines.append("  ... +%d more" % (len(src_files) - room))
            budget -= 1
    if tests:
        lines.append("Tests to run (%d):" % len(tests))
        lines.extend("  " + t for t in tests[:5])
        if len(tests) > 5:
            lines[-1] += "  (+%d more)" % (len(tests) - 5)
    con.close()
    return lines[:QUERY_LINES]


def _resolve_node(con, project, arg):
    """A file path in the index, or the file defining symbol `arg`."""
    rel = _norm(project, arg)
    if con.execute("SELECT 1 FROM files WHERE path=?", (rel,)).fetchone():
        return rel, None
    r = con.execute("SELECT path, line, kind FROM symbols WHERE name=? ORDER BY kind='method', path LIMIT 1",
                    (arg,)).fetchone()
    return (r[0], "%s %s:%d" % (r[2], r[0], r[1])) if r else (None, None)


def path_between(project, a, b):
    """Shortest dependency chain between two files or symbols (A uses ... uses B)."""
    con = connect(project, write=False)
    (fa, da), (fb, db) = _resolve_node(con, project, a), _resolve_node(con, project, b)
    if not fa or not fb:
        con.close()
        return ["Not in the index: %s — use a repo-relative file path or an exact symbol name."
                % ", ".join(x for x, f in ((a, fa), (b, fb)) if not f)]
    if fa == fb:
        con.close()
        return ["%s and %s are in the same file: %s" % (a, b, fa)]
    for start, goal, flip in ((fa, fb, False), (fb, fa, True)):
        prev, queue = {start: None}, [start]
        for cur in queue:
            if cur == goal or len(prev) > 5000:
                break
            for n in _uses_of(con, cur):
                if n not in prev:
                    prev[n] = cur
                    queue.append(n)
        if goal in prev:
            chain = [goal]
            while prev[chain[-1]]:
                chain.append(prev[chain[-1]])
            chain.reverse()
            lines = ["Path %s%s -> %s%s (%d hops, %s uses %s):" % (
                start, " [%s]" % (db if flip else da) if (db if flip else da) else "",
                goal, " [%s]" % (da if flip else db) if (da if flip else db) else "",
                len(chain) - 1, start, goal)]
            lines.extend("  " + _edge_text(con, x, y) + "  -> " + y for x, y in zip(chain, chain[1:]))
            con.close()
            return lines[:QUERY_LINES]
    con.close()
    return ["No import/call path between %s and %s in either direction (index covers resolved "
            "imports and calls only; dynamic use and unresolved calls are invisible)." % (fa, fb)]


def status(project):
    if not exists(project):
        return ["Index: not built yet (builds in the background at session start, or on first query)."]
    con = connect(project, write=False)
    files = con.execute("SELECT count(*) FROM files").fetchone()[0]
    syms = con.execute("SELECT count(*) FROM symbols").fetchone()[0]
    imps = con.execute("SELECT count(*), count(target) FROM imports").fetchone()
    edges = con.execute("SELECT count(*), count(dst_path) FROM edges WHERE kind='calls'").fetchone()
    conf = dict(con.execute("SELECT confidence, count(*) FROM edges GROUP BY confidence"))
    langs = Counter(dict(con.execute("SELECT lang, count(*) FROM files GROUP BY lang").fetchall()))
    out = ["Index: %d files, %d symbols, %d imports (%d resolved to repo files), %d call edges (%d resolved)"
           % (files, syms, imps[0], imps[1], edges[0], edges[1]),
           "Graph: %d nodes, %d edges (%s)" % (con.execute("SELECT count(*) FROM nodes").fetchone()[0],
                                               sum(conf.values()),
                                               ", ".join("%s %d" % (c, conf.get(c, 0)) for c in CONFIDENCE)),
           "Languages: " + ", ".join("%s %d" % kv for kv in langs.most_common(6)),
           "Symbols from: %s (precision ast > ctags > approx) · built %s · updated %s" % (_meta(con, "symbol_tool"), _meta(con, "built_at"),
                                                       _meta(con, "updated_at")),
           "Derived edges: %s (last full pass %s ms)" % ("pending, refreshed by the next query" if
                                                          _meta(con, "derived_stale") == "1" else "current",
                                                          _meta(con, "derive_ms") or "?"),
           "Path: %s" % db_path(project)]
    con.close()
    return out


def languages(project):
    """{lang: file count} from the index, or {} if it isn't built."""
    try:
        con = connect(project, write=False)
    except IndexUnavailable:
        return {}
    out = dict(con.execute("SELECT lang, count(*) FROM files GROUP BY lang").fetchall())
    con.close()
    return out
