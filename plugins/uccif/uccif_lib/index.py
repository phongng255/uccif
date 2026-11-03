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

from uccif_lib import ts_parse
from uccif_lib.paths import LockTimeout, file_lock, now_iso

SCHEMA = 2
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
JS_RESOLVE_EXT = (".ts", ".tsx", ".js", ".jsx", ".vue", ".mjs", ".cjs", ".mts", ".svelte", ".d.ts")
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
            return sqlite3.connect(uri, uri=True, timeout=5)
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
        CREATE TABLE IF NOT EXISTS imports (src TEXT, raw TEXT, target TEXT);
        CREATE TABLE IF NOT EXISTS calls (src_path TEXT, src_symbol TEXT, callee_name TEXT,
            callee_path TEXT, line INTEGER);
        CREATE INDEX IF NOT EXISTS call_callee ON calls(callee_name);
        CREATE INDEX IF NOT EXISTS call_src ON calls(src_path);
        CREATE INDEX IF NOT EXISTS sym_name ON symbols(name);
        CREATE INDEX IF NOT EXISTS sym_lname ON symbols(lower(name));
        CREATE INDEX IF NOT EXISTS sym_path ON symbols(path);
        CREATE INDEX IF NOT EXISTS imp_src ON imports(src);
        CREATE INDEX IF NOT EXISTS imp_target ON imports(target);
    """)
    if _meta(con, "schema") not in (None, str(SCHEMA)):
        con.executescript("DELETE FROM files; DELETE FROM symbols; DELETE FROM imports; DELETE FROM calls; "
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


def raw_imports(text, lang):
    fam = LANG_FAMILY.get(lang)
    rxs = IMPORT_RES.get(fam, [])
    seen = []
    for rx in rxs:
        for m in rx.finditer(text):
            v = m.group(1)
            if v and v not in seen:
                seen.append(v)
    return seen[:200]


class Resolver:
    """Map an import string to a repo file (or None for external packages)."""

    def __init__(self, files):
        self.files = set(files)
        self.py_roots = [""] + [d for d in ("src", "lib", "app") if any(f.startswith(d + "/") for f in files)]

    def _try_js(self, base):
        base = str(PurePosixPath(base))
        cands = [base] + [base + e for e in JS_RESOLVE_EXT] + \
                [base + "/index" + e for e in JS_RESOLVE_EXT]
        return next((c for c in cands if c in self.files), None)

    def resolve(self, src, raw, lang):
        fam = LANG_FAMILY.get(lang)
        here = PurePosixPath(src).parent
        if fam in ("js", "style"):
            if raw.startswith(("@/", "~/")):
                target = "src/" + raw[2:]
            elif raw.startswith(".") or (fam == "style" and "://" not in raw and not raw.startswith("~")):
                target = os.path.normpath(str(here / raw)).replace(os.sep, "/")
            else:
                return None  # a package, not a repo file
            if target.startswith("../"):
                return None
            hit = self._try_js(target)
            if hit or fam == "js":
                return hit
            p = PurePosixPath(target)  # scss partials: _name.scss
            for cand in (target + ".scss", str(p.parent / ("_" + p.name + ".scss")), target + ".css",
                         target + ".less"):
                cand = os.path.normpath(cand).replace(os.sep, "/")
                if cand in self.files:
                    return cand
            return None
        if fam == "python":
            dots = len(raw) - len(raw.lstrip("."))
            mod = raw.lstrip(".").replace(".", "/")
            bases = []
            if dots:
                base = here
                for _ in range(dots - 1):
                    base = base.parent
                bases.append(str(base / mod) if mod else str(base))
            else:
                bases = [(r + "/" + mod) if r else mod for r in self.py_roots]
            for b in bases:
                b = os.path.normpath(b).replace(os.sep, "/").lstrip("./")
                for cand in (b + ".py", b + "/__init__.py"):
                    if cand in self.files:
                        return cand
            return None
        if fam == "rust":
            for cand in (str(here / (raw + ".rs")), str(here / raw / "mod.rs")):
                if cand in self.files:
                    return cand
        return None


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


def _update(project, full, only=None):
    t0 = time.time()
    root = project.root
    con = connect(project)
    if full:
        con.executescript("DELETE FROM files; DELETE FROM symbols; DELETE FROM imports; DELETE FROM calls;")
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
        if old and old[0] == st.st_size and abs((old[1] or 0) - st.st_mtime) < 1e-6:
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
        if old and old[2] == h:
            con.execute("UPDATE files SET mtime=? WHERE path=?", (st.st_mtime, rel))
            continue
        to_parse.append((rel, st, h, text))

    # symbol sources, best first: tree-sitter (optional) -> universal-ctags -> regex
    ast = {}
    for rel, _, _, text in to_parse:
        lang = lang_of(rel)
        res = ts_parse.parse(_script_part(text, lang), rel, lang)
        if res is not None:
            ast[rel] = res
    need_ctags = [r for r, _, _, _ in to_parse if r not in ast]
    tagged = ctags_symbols(exe, root, need_ctags) if exe and need_ctags else {}
    resolver = Resolver(current)
    for rel in removed:
        _drop(con, rel)
    for rel, st, h, text in to_parse:
        _drop(con, rel)
        lang = lang_of(rel)
        if rel in ast:
            syms, precision = list(ast[rel][0]), "ast"
            if lang in ("vue", "svelte"):
                syms.append((None, "component", 1, None))
            raws = ast[rel][1]
            call_rows = _resolve_calls(rel, lang, ast[rel], resolver)
        else:
            call_rows = []
            syms, precision = tagged.get(rel), "ctags"
            if not syms:
                syms, precision = regex_symbols(text, lang), "approx"
            raws = raw_imports(text, lang)
        stem = PurePosixPath(rel).stem
        rows = [((n if n is not None else stem), k, rel, ln, sc, precision) for n, k, ln, sc in syms]
        con.executemany("INSERT INTO symbols VALUES (?,?,?,?,?,?)", rows)
        imps = [(rel, raw, resolver.resolve(rel, raw, lang)) for raw in raws]
        con.executemany("INSERT INTO imports VALUES (?,?,?)", imps)
        con.executemany("INSERT INTO calls VALUES (?,?,?,?,?)", call_rows)
        con.execute("INSERT INTO files VALUES (?,?,?,?,?,?,?)",
                    (rel, lang, st.st_size, st.st_mtime, h, int(is_test(rel)), len(rows)))
    if to_parse or removed or full:
        _set_meta(con, "updated_at", now_iso())
        _set_meta(con, "symbol_tool", tool)
        if full or not _meta(con, "built_at"):
            _set_meta(con, "built_at", now_iso())
    con.commit()
    con.close()
    return {"files": len(current), "parsed": len(to_parse), "removed": len(removed),
            "ms": int((time.time() - t0) * 1000), "tool": tool}


def _resolve_calls(rel, lang, parsed, resolver):
    """Best-effort: attach each call to the repo file defining its callee.
    Resolved through the file's own import bindings, or to this file when it defines the
    name itself (and for `this.x()` / `self.x()`). Anything else keeps callee_path NULL
    ("unresolved"): a lead to verify by reading, not a fact."""
    syms, _, calls, binds = parsed
    local = {n for n, _, _, _ in syms if n}
    bound = {}
    for name, (raw, orig) in binds.items():
        target = None
        if lang == "python" and orig != "*" and raw.strip(".") == "":
            target = resolver.resolve(rel, raw + orig, lang)  # from . import mod
        if target is None:
            target = resolver.resolve(rel, raw, lang)
        bound[name] = (target, orig)
    rows = []
    for caller, name, obj, line in calls:
        path, callee = None, name
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
        rows.append((rel, caller, callee, path, line))
    return rows


def _drop(con, rel):
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


def dependents(con, rel):
    return [r[0] for r in con.execute("SELECT DISTINCT src FROM imports WHERE target=? ORDER BY src", (rel,))]


def tests_for(con, rel):
    """Test files that import `rel`, plus tests named after it (x.test.ts, test_x.py, ...)."""
    direct = [r[0] for r in con.execute(
        "SELECT DISTINCT i.src FROM imports i JOIN files f ON f.path=i.src WHERE i.target=? AND f.is_test=1",
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
    total, top = _refs(project, name)
    room = QUERY_LINES - len(lines) - 1  # header line
    if total and room >= 1:
        lines.append("Referenced (whole word) in %d files%s:" % (total, ", top 10" if total > 10 else ""))
        lines.extend("  %s (%d)" % (p, c) for p, c in top[:room])
    con.close()
    return lines[:QUERY_LINES]


def _called_by(con, defs, budget, cap=8):
    """'Called by' lines from the call graph (only files parsed with tree-sitter have calls)."""
    if budget < 3 or not defs:
        return []
    exact = {(n, p) for n, _, p, _, _, _ in defs}
    names = {n for n, _ in exact}
    rows = []
    try:
        for n in names:
            rows += [(n,) + r for r in con.execute(
                "SELECT callee_path, src_path, src_symbol, line FROM calls WHERE callee_name=? "
                "ORDER BY src_path, line", (n,))]
    except sqlite3.OperationalError:  # index from an older schema, upgraded by the next update
        return []
    sure = [(sp, ss, ln) for n, cp, sp, ss, ln in rows if cp and (n, cp) in exact]
    # callee_path NULL: same name, receiver unknown (e.g. `store.add()`); keep apart and mark
    maybe = [(sp, ss, ln) for n, cp, sp, ss, ln in rows if not cp]
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
    con.close()
    return lines[:QUERY_LINES]


def query_tests_for(project, path):
    con = connect(project, write=False)
    rel = _norm(project, path)
    tests = tests_for(con, rel)
    con.close()
    return ["Tests for %s:" % rel] + (["  " + t for t in tests] or ["  none found"])


def status(project):
    if not exists(project):
        return ["Index: not built yet (builds in the background at session start, or on first query)."]
    con = connect(project, write=False)
    files = con.execute("SELECT count(*) FROM files").fetchone()[0]
    syms = con.execute("SELECT count(*) FROM symbols").fetchone()[0]
    imps = con.execute("SELECT count(*), count(target) FROM imports").fetchone()
    try:
        edges = con.execute("SELECT count(*), count(callee_path) FROM calls").fetchone()
    except sqlite3.OperationalError:
        edges = (0, 0)
    langs = Counter(dict(con.execute("SELECT lang, count(*) FROM files GROUP BY lang").fetchall()))
    out = ["Index: %d files, %d symbols, %d imports (%d resolved to repo files), %d call edges (%d resolved)"
           % (files, syms, imps[0], imps[1], edges[0], edges[1]),
           "Languages: " + ", ".join("%s %d" % kv for kv in langs.most_common(6)),
           "Symbols from: %s (precision ast > ctags > approx) · built %s · updated %s" % (_meta(con, "symbol_tool"), _meta(con, "built_at"),
                                                       _meta(con, "updated_at")),
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
