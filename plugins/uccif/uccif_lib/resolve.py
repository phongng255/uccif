"""Map an import string to a repo file (or None for an external package).

JS/TS path aliases come from the nearest project config of the importing file:
`tsconfig.json` / `jsconfig.json` (`compilerOptions.baseUrl` + `paths`, following a relative
`extends`) and `vite.config.*` (`resolve.alias`, object or `{ find, replacement }` form). With
no config, `@/` and `~/` mean `<project>/src/` as before. A "project" is the nearest folder
holding package.json, a tsconfig/jsconfig or a vite config, so a monorepo package (or a test
fixture) keeps its own aliases.

Python absolute imports try, in order: the repo root, `src/`, `lib/`, `app/`; package roots
declared in `pyproject.toml` / `setup.cfg` (`package-dir`, `packages.find where`, poetry
`from`); the parent of every top-level package (a folder with `__init__.py` whose parent has
none); then the importing file's own folder (how scripts and pytest import siblings).

Config files are read lazily and cached for one index update; nothing here writes.
"""

import json
import os
import re
from pathlib import PurePosixPath

JS_RESOLVE_EXT = (".ts", ".tsx", ".js", ".jsx", ".vue", ".mjs", ".cjs", ".mts", ".svelte", ".d.ts")
PROJECT_MARKERS = ("package.json", "tsconfig.json", "jsconfig.json", "vite.config.ts", "vite.config.js",
                   "vite.config.mjs", "vite.config.mts")
DEFAULT_ALIASES = (("@/", "src/"), ("~/", "src/"))
JS_FAMILY = ("typescript", "javascript", "vue", "svelte")
STYLE_FAMILY = ("css", "scss", "less")

_VITE_PATH = (r"(?:fileURLToPath\(\s*new\s+URL\(\s*|(?:path\.)?(?:resolve|join)\(\s*(?:__dirname|process\.cwd\(\))"
              r"\s*,\s*)?['\"]([^'\"]+)['\"]")
_VITE_OBJ = re.compile(r"['\"]?([@~#$][\w@~#$/-]*|[A-Za-z_][\w-]*)['\"]?\s*:\s*" + _VITE_PATH)
_VITE_FIND = re.compile(r"find\s*:\s*['\"]([^'\"]+)['\"]\s*,\s*replacement\s*:\s*" + _VITE_PATH)


def _norm(p):
    p = os.path.normpath(p).replace(os.sep, "/")
    return "" if p == "." else p


def _join(base, rel):
    return _norm(str(PurePosixPath(base) / rel)) if base else _norm(rel)


def _loose_json(text):
    """tsconfig allows comments and trailing commas."""
    text = re.sub(r'("(?:\\.|[^"\\])*")|//[^\n]*|/\*.*?\*/', lambda m: m.group(1) or "", text, flags=re.S)
    text = re.sub(r",\s*([}\]])", r"\1", text)
    try:
        return json.loads(text)
    except ValueError:
        return None


class Resolver:
    def __init__(self, files, root=None):
        self.files = set(files)
        self.root = root
        self._proj = {}
        self._aliases = {}
        self.py_names = set()
        inits = set()
        for f in self.files:
            if f.endswith((".py", ".pyi")):
                pp = PurePosixPath(f)
                self.py_names.update(pp.parent.parts)
                self.py_names.add(pp.stem)
                if pp.name == "__init__.py":
                    inits.add(str(pp.parent))
        roots = [""] + [d for d in ("src", "lib", "app") if any(f.startswith(d + "/") for f in self.files)]
        roots += self._declared_py_roots()
        for d in sorted(inits):  # top-level packages: their parent is an import root
            parent = str(PurePosixPath(d).parent)
            parent = "" if parent == "." else parent
            if (parent + "/__init__.py" if parent else "__init__.py") not in self.files:
                roots.append(parent)
        self.py_roots = list(dict.fromkeys(roots))
        self._gomods = None
        self._java_idx = None
        self._dirs = {}
        for f in self.files:
            d = str(PurePosixPath(f).parent)
            self._dirs.setdefault("" if d == "." else d, []).append(f)

    # ---- config files ---------------------------------------------------------------

    def _text(self, rel):
        if self.root is None:
            return None
        try:
            with open(os.path.join(str(self.root), rel), encoding="utf-8", errors="replace") as fh:
                return fh.read(200000)
        except OSError:
            return None

    def _declared_py_roots(self):
        out = []
        t = self._text("pyproject.toml") or ""
        for rx in (r'package-dir\s*=\s*\{[^}]*?""\s*=\s*"([^"]+)"', r'where\s*=\s*\[\s*"([^"]+)"',
                   r'packages\s*=\s*\[[^\]]*?from\s*=\s*"([^"]+)"'):
            out += re.findall(rx, t, re.S)
        t = self._text("setup.cfg") or ""
        out += re.findall(r"package_dir\s*=\s*\n?\s*=\s*(\S+)", t)
        out += re.findall(r"^\s*where\s*=\s*(\S+)", t, re.M)
        return [_norm(r).strip("/") for r in out if r and _norm(r) not in ("", "..")]

    def project_of(self, src):
        """Nearest folder (repo-relative, '' = root) holding a project marker."""
        d = str(PurePosixPath(src).parent)
        d = "" if d == "." else d
        chain = []
        while True:
            if d in self._proj:
                found = self._proj[d]
                break
            chain.append(d)
            if self.root is not None and any(os.path.isfile(os.path.join(str(self.root), d, m))
                                             for m in PROJECT_MARKERS):
                found = d
                break
            if not d:
                found = ""
                break
            parent = str(PurePosixPath(d).parent)
            d = "" if parent == "." else parent
        for c in chain:
            self._proj[c] = found
        return found

    def aliases(self, proj):
        """[(prefix, [targets])], longest prefix first. Targets are repo-relative folders/files."""
        if proj in self._aliases:
            return self._aliases[proj]
        found = []
        for name in ("tsconfig.json", "jsconfig.json"):
            found += self._ts_paths(_join(proj, name), depth=0)
        for name in PROJECT_MARKERS[3:]:
            t = self._text(_join(proj, name))
            if not t:
                continue
            block = t[t.find("alias"):] if "alias" in t else ""
            for rx in (_VITE_FIND, _VITE_OBJ):
                for key, target in rx.findall(block[:4000]):
                    if key in ("find", "replacement", "alias", "resolve"):
                        continue
                    target = target.lstrip("/") if target.startswith("/") else target
                    found.append((key.rstrip("/") + "/", [_join(proj, target)]))
                    found.append((key, [_join(proj, target)]))
        have = {p for p, _ in found}
        for prefix, target in DEFAULT_ALIASES:
            if prefix not in have:
                found.append((prefix, [_join(proj, target)]))
        seen, out = set(), []
        for p, t in sorted(found, key=lambda x: -len(x[0])):
            if p not in seen:
                seen.add(p)
                out.append((p, t))
        self._aliases[proj] = out
        return out

    def _ts_paths(self, cfg, depth):
        t = self._text(cfg)
        data = _loose_json(t) if t else None
        if not isinstance(data, dict):
            return []
        here = str(PurePosixPath(cfg).parent)
        here = "" if here == "." else here
        found = []
        ext = data.get("extends")
        if isinstance(ext, str) and ext.startswith(".") and depth < 3:
            found += self._ts_paths(_join(here, ext if ext.endswith(".json") else ext + ".json"), depth + 1)
        opts = data.get("compilerOptions") or {}
        base = _join(here, opts.get("baseUrl") or ".")
        for key, targets in (opts.get("paths") or {}).items():
            if not isinstance(targets, list):
                continue
            tg = [_join(base, x.rstrip("*").rstrip("/")) for x in targets if isinstance(x, str)]
            if key.endswith("/*"):
                found.append((key[:-1], tg))
            elif key.endswith("*"):
                found.append((key[:-1], tg))
            else:
                found.append((key + "\0", tg))  # exact key, no sub-path
        return found

    def _alias_target(self, src, raw):
        for prefix, targets in self.aliases(self.project_of(src)):
            if prefix.endswith("\0"):
                if raw == prefix[:-1]:
                    return targets
                continue
            if raw.startswith(prefix) or (not prefix.endswith("/") and raw == prefix):
                rest = raw[len(prefix):].lstrip("/")
                return [_join(t, rest) if rest else t for t in targets]
        return None

    # ---- resolution -------------------------------------------------------------------

    # ---- Go / Rust / Java (roadmap layer E) ------------------------------------------

    def package_files(self, d, ext):
        """Non-test source files directly in folder `d` with extension `ext` (a Go / Java package)."""
        return sorted(f for f in self._dirs.get(d, ()) if f.endswith(ext) and not f.endswith("_test.go"))

    def _go_modules(self):
        """[(module path, folder)] from every go.mod in the repo, longest module first."""
        if self._gomods is None:
            self._gomods = []
            for d in sorted(set(self._dirs) | {""}):
                t = self._text(_join(d, "go.mod"))
                m = re.search(r"^\s*module\s+(\S+)", t or "", re.M)
                if m:
                    self._gomods.append((m.group(1), d))
            self._gomods.sort(key=lambda x: -len(x[0]))
        return self._gomods

    def _go_dir(self, raw):
        for mod, d in self._go_modules():
            if raw == mod or raw.startswith(mod + "/"):
                return _join(d, raw[len(mod) + 1:]) if raw != mod else d
        return None

    def _rust_mod_dir(self, src):
        """Folder holding the child modules of the module that `src` is."""
        p = PurePosixPath(src)
        if p.name in ("main.rs", "lib.rs", "mod.rs"):
            d = str(p.parent)
        else:
            d = str(p.parent / p.stem)
        return "" if d == "." else d

    def _rust_crate_dir(self, src):
        d = str(PurePosixPath(src).parent)
        d = "" if d == "." else d
        while True:
            for root in ("main.rs", "lib.rs"):
                if _join(d, root) in self.files:
                    return d
            if not d:
                return ""
            parent = str(PurePosixPath(d).parent)
            d = "" if parent == "." else parent

    def _rust_module_file(self, base, segments):
        """Deepest file reached by following `segments` from module folder `base`."""
        hit, d = None, base
        for seg in segments:
            for cand in (_join(d, seg + ".rs"), _join(d, seg + "/mod.rs")):
                if cand in self.files:
                    hit, d = cand, _join(d, seg)
                    break
            else:
                break
        return hit

    def _rust(self, src, raw):
        segs = [x for x in raw.split("::") if x]
        if not segs:
            return None
        if segs[0] == "crate":
            return self._rust_module_file(self._rust_crate_dir(src), segs[1:]) or None
        base = self._rust_mod_dir(src)
        if segs[0] == "self":
            return self._rust_module_file(base, segs[1:]) or (src if len(segs) == 1 else None)
        if segs[0] == "super":
            parent = str(PurePosixPath(base).parent)
            base = "" if parent == "." else parent
            for x in segs[1:]:
                if x != "super":
                    break
            return self._rust_module_file(base, [x for x in segs[1:] if x != "super"])
        return self._rust_module_file(base, segs)  # `mod x;` or a path starting at a child module

    def _java_files(self):
        if self._java_idx is None:
            self._java_idx = {}
            for f in self.files:
                if f.endswith(".java"):
                    self._java_idx.setdefault(PurePosixPath(f).stem, []).append(f)
        return self._java_idx

    def _java(self, raw):
        parts = raw.split(".")
        for f in self._java_files().get(parts[-1], ()):
            if f[:-5].endswith("/".join(parts)):
                return f
        return None

    def _java_package(self, raw):
        tail = "/".join(raw.split("."))
        return [f for d, fs in self._dirs.items() if d == tail or d.endswith("/" + tail)
                for f in sorted(fs) if f.endswith(".java")]

    def resolve_many(self, src, raw, lang):
        """Every repo file an import names: a Go package or a Java `a.b.*` is a folder of files."""
        if lang == "go":
            d = self._go_dir(raw)
            return self.package_files(d, ".go") if d is not None else []
        if lang == "java" and raw.endswith(".*"):
            return self._java_package(raw[:-2])
        hit = self.resolve(src, raw, lang)
        return [hit] if hit else []

    def internal(self, raw, lang, src=None):
        """Does this import string name a file in this repo (even one we could not place)?
        False means a package: known, just not ours."""
        if raw.startswith((".", "@/", "~/")):
            return True
        if lang == "python" or (lang or "").startswith("python"):
            return raw.split(".")[0] in self.py_names
        if lang == "go":
            return self._go_dir(raw) is not None
        if lang == "rust":
            return raw.split("::")[0] in ("crate", "self", "super") or (src is not None and self._rust(src, raw)
                                                                         is not None)
        if lang == "java":
            return bool(self._java(raw[:-2] if raw.endswith(".*") else raw) or self._java_package(
                raw[:-2] if raw.endswith(".*") else raw.rsplit(".", 1)[0]))
        if src is not None and lang in JS_FAMILY and self._alias_target(src, raw) is not None:
            return True
        return False

    def _try_js(self, base):
        base = _norm(base)
        cands = [base] + [base + e for e in JS_RESOLVE_EXT] + [base + "/index" + e for e in JS_RESOLVE_EXT]
        return next((c for c in cands if c in self.files), None)

    def resolve(self, src, raw, lang):
        here = str(PurePosixPath(src).parent)
        here = "" if here == "." else here
        if lang in JS_FAMILY or lang in STYLE_FAMILY:
            style = lang in STYLE_FAMILY
            if raw.startswith("."):
                targets = [_join(here, raw)]
            elif style and "://" not in raw and not raw.startswith("~") and not raw.startswith("@"):
                targets = [_join(here, raw)]
            else:
                targets = self._alias_target(src, raw) if not style or raw.startswith(("@/", "~/")) else None
                if targets is None:
                    return None  # a package, not a repo file
            for target in targets:
                if target.startswith("../"):
                    continue
                hit = self._try_js(target)
                if hit:
                    return hit
                if style:
                    p = PurePosixPath(target)  # scss partials: _name.scss
                    for cand in (target + ".scss", str(p.parent / ("_" + p.name + ".scss")), target + ".css",
                                 target + ".less"):
                        cand = _norm(cand)
                        if cand in self.files:
                            return cand
            return None
        if lang == "python":
            dots = len(raw) - len(raw.lstrip("."))
            mod = raw.lstrip(".").replace(".", "/")
            if dots:
                base = PurePosixPath(here or ".")
                for _ in range(dots - 1):
                    base = base.parent
                bases = [str(base / mod) if mod else str(base)]
            else:
                bases = [(r + "/" + mod) if r else mod for r in self.py_roots]
                bases.append((here + "/" + mod) if here else mod)  # sibling module (scripts, pytest)
            for b in bases:
                b = _norm(b)
                for cand in (b + ".py", b + "/__init__.py"):
                    if cand in self.files:
                        return cand
            return None
        if lang == "rust":
            return self._rust(src, raw)
        if lang == "go":
            files = self.resolve_many(src, raw, lang)
            return files[0] if files else None
        if lang == "java":
            return self._java(raw) if not raw.endswith(".*") else None
        return None
