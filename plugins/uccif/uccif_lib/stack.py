"""Commands and test runners of any repository, read from its manifests.

Framework-neutral and data-driven: every row says which file or dependency
reveals a tool and which exact command runs it. Nothing here guesses beyond the
tool's documented default command. Stdlib only, read-only.
"""

import json
import re
from pathlib import Path

# name, how it is detected (manifest, dependency or None), run-all, run-one ({file}, {name})
TEST_RUNNERS = [
    ("vitest", ("npm", "vitest"), None, "npx vitest run {file}"),
    ("jest", ("npm", "jest"), None, "npx jest {file}"),
    ("mocha", ("npm", "mocha"), None, "npx mocha {file}"),
    ("playwright", ("npm", "@playwright/test"), "npx playwright test", "npx playwright test {file}"),
    ("pytest", ("py", "pytest"), "python -m pytest -q", "python -m pytest -q {file}"),
    ("go test", ("file", "go.mod"), "go test ./...", "go test ./{dir}/..."),
    ("cargo test", ("file", "Cargo.toml"), "cargo test", "cargo test"),
    ("maven", ("file", "pom.xml"), "mvn -q test", "mvn -q test -Dtest={stem}"),
    ("gradle", ("file", "build.gradle"), "{gradle} test", "{gradle} test --tests '*{stem}*'"),
    ("gradle", ("file", "build.gradle.kts"), "{gradle} test", "{gradle} test --tests '*{stem}*'"),
    ("phpunit", ("php", "phpunit/phpunit"), "vendor/bin/phpunit", "vendor/bin/phpunit {file}"),
    ("rspec", ("ruby", "rspec"), "bundle exec rspec", "bundle exec rspec {file}"),
    ("rspec", ("ruby", "rspec-rails"), "bundle exec rspec", "bundle exec rspec {file}"),
    ("flutter test", ("dart", "flutter"), "flutter test", "flutter test {file}"),
    ("mix test", ("file", "mix.exs"), "mix test", "mix test {file}"),
    ("dotnet test", ("glob", "*.sln"), "dotnet test", "dotnet test"),
]
DEP_FILES = {
    "npm": ("package.json",),
    "py": ("pyproject.toml", "requirements.txt", "requirements-dev.txt", "Pipfile", "setup.py", "setup.cfg", "tox.ini"),
    "php": ("composer.json",),
    "ruby": ("Gemfile",),
    "dart": ("pubspec.yaml",),
}
SCRIPT_ORDER = ("dev", "start", "build", "test", "lint", "typecheck", "type-check", "format")
MAKE_TARGETS = ("dev", "run", "start", "build", "test", "check", "lint", "fmt", "format", "typecheck")


def _read(path, limit=400000):
    try:
        if path.stat().st_size > limit:
            return ""
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _npm(root):
    try:
        data = json.loads(_read(Path(root) / "package.json"))
        return data if isinstance(data, dict) else {}
    except ValueError:
        return {}


def _has_dep(root, eco, token, npm):
    if eco == "npm":
        return any(token in (npm.get(k) or {}) for k in ("dependencies", "devDependencies"))
    rx = re.compile(r"(?<![A-Za-z0-9_\-])%s(?![A-Za-z0-9_\-])" % re.escape(token), re.I)
    return any(rx.search(_read(Path(root) / f)) for f in DEP_FILES[eco])


MANIFESTS = ("package.json", "pyproject.toml", "requirements.txt", "setup.py", "go.mod", "Cargo.toml", "pom.xml",
             "build.gradle", "build.gradle.kts", "Gemfile", "composer.json", "pubspec.yaml", "mix.exs")
SKIP = {"node_modules", "vendor", "dist", "build", "target", "venv", ".venv", "examples", "example", "fixtures",
        "testdata", "docs"}


def package_dirs(root, depth=2, cap=8):
    """'.' plus sub-dirs (≤ depth) holding a manifest: the packages of a monorepo."""
    root = Path(root)
    out = ["."]
    level = [root]
    for _ in range(depth):
        nxt = []
        for d in level:
            try:
                subs = sorted(p for p in d.iterdir() if p.is_dir() and not p.name.startswith(".")
                              and p.name not in SKIP)
            except OSError:
                continue
            for p in subs:
                if any((p / m).exists() for m in MANIFESTS):
                    out.append(p.relative_to(root).as_posix())
                nxt.append(p)
        level = nxt
    return out[:cap]


def _cd(d, cmd):
    return cmd if d == "." or not cmd else "cd %s && %s" % (d, cmd)


def test_runners(root):
    """[{'name', 'dir', 'run_all', 'run_one'}] for the tools each package of this repo uses;
    commands of a sub-package start with `cd <dir> &&` and take paths relative to it."""
    out = []
    for d in package_dirs(root):
        for r in _runners_in(Path(root) / d if d != "." else Path(root)):
            out.append(dict(r, dir=d, run_all=_cd(d, r["run_all"]), run_one=_cd(d, r["run_one"])))
    return out


def run_one(runners, test_path):
    """The command that runs one test file (repo-relative path), from the package holding it."""
    best = None
    for r in runners:
        if r["dir"] == "." or test_path.startswith(r["dir"] + "/"):
            if best is None or len(r["dir"]) > len(best["dir"]):
                best = r
    if not best:
        return None
    rel = test_path if best["dir"] == "." else test_path[len(best["dir"]) + 1:]
    p = Path(rel)
    return (best["run_one"].replace("{file}", rel).replace("{dir}", p.parent.as_posix())
            .replace("{stem}", p.stem))


def _runners_in(root):
    npm = _npm(root)
    gradle = "./gradlew" if (root / "gradlew").exists() else "gradle"
    out, seen = [], set()
    for name, (eco, token), run_all, run_one in TEST_RUNNERS:
        if name in seen:
            continue
        if eco == "file":
            hit = (root / token).exists()
        elif eco == "glob":
            hit = any(root.glob(token))
        else:
            hit = _has_dep(root, eco, token, npm)
        if hit:
            seen.add(name)
            out.append({"name": name, "run_all": run_all and run_all.replace("{gradle}", gradle),
                        "run_one": run_one.replace("{gradle}", gradle)})
    return out


def _pm(root):
    for lock, pm in (("pnpm-lock.yaml", "pnpm"), ("yarn.lock", "yarn"), ("bun.lockb", "bun"), ("bun.lock", "bun")):
        if (Path(root) / lock).exists():
            return pm
    return "npm"


def commands(root):
    """[(purpose, exact command)] from package.json scripts, Makefile/justfile targets and the
    default commands of the build tools present."""
    root = Path(root)
    out = []

    def add(purpose, cmd):
        if cmd and all(c != cmd for _, c in out):
            out.append((purpose, cmd))

    pm = _pm(root)
    for d in package_dirs(root):
        scripts = _npm(root / d if d != "." else root).get("scripts") or {}
        if not isinstance(scripts, dict):
            continue
        keys = [k for k in SCRIPT_ORDER if k in scripts]
        if d == ".":
            keys += sorted(k for k in scripts if k not in SCRIPT_ORDER)[:4]
        for k in keys:
            add(k, _cd(d, "%s test" % pm if k == "test" else "%s run %s" % (pm, k)))
    for mk, tool in (("Makefile", "make"), ("makefile", "make"), ("justfile", "just"), ("Justfile", "just")):
        for t in re.findall(r"^([A-Za-z][\w.-]*)\s*:(?!=)", _read(root / mk), re.M):
            if t in MAKE_TARGETS:
                add(t, "%s %s" % (tool, t))
    if (root / "go.mod").exists():
        add("build", "go build ./...")
        add("lint", "go vet ./...")
    if (root / "Cargo.toml").exists():
        add("build", "cargo build")
        add("lint", "cargo clippy")
    if (root / "manage.py").exists():
        add("run", "python manage.py runserver")
    for r in test_runners(root):
        if r["run_all"] and r["run_all"] not in (c for _, c in out):
            add("test", r["run_all"])
    return out
