"""Mechanical project survey (`uccif detect`) and install check (`uccif doctor`).

Read-only. Everything here is cheap and deterministic so the init skill spends
model tokens only on what needs understanding.
"""

import json
import os
import shutil
import subprocess
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

from uccif_lib import __version__, log
from uccif_lib.paths import data_root

SKIP_DIRS = {".git", "node_modules", "vendor", ".venv", "venv", "env", "dist", "build",
             "out", "bin", "obj", ".next", ".nuxt", ".output", "target", "coverage",
             "__pycache__", ".pytest_cache", ".mypy_cache", ".idea", ".vscode", ".claude"}
LANG_EXT = {
    ".ts": "typescript", ".tsx": "typescript", ".mts": "typescript", ".cts": "typescript",
    ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".vue": "vue", ".svelte": "svelte", ".py": "python", ".go": "go", ".rs": "rust",
    ".java": "java", ".kt": "kotlin", ".cs": "csharp", ".rb": "ruby", ".php": "php",
    ".swift": "swift", ".c": "c", ".h": "c", ".cpp": "cpp", ".hpp": "cpp", ".dart": "dart",
}
MANIFESTS = ("package.json", "pyproject.toml", "requirements.txt", "setup.py", "Pipfile",
             "go.mod", "Cargo.toml", "pom.xml", "build.gradle", "build.gradle.kts",
             "composer.json", "Gemfile", "pubspec.yaml", "firebase.json", "vite.config.ts",
             "vite.config.js", "vue.config.js", "nuxt.config.ts", "next.config.js",
             "tsconfig.json", "Makefile", "Dockerfile", "docker-compose.yml")
ENTRY_NAMES = ("main.ts", "main.js", "index.ts", "index.js", "App.vue", "main.py",
               "app.py", "__main__.py", "manage.py", "main.go", "main.rs", "server.js", "server.ts")
LARGE_REPO = 300


def list_files(root):
    try:
        out = subprocess.run(["git", "ls-files", "-co", "--exclude-standard"], cwd=str(root),
                             capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10)
        if out.returncode == 0:
            return [p for p in out.stdout.splitlines()
                    if not any(part in SKIP_DIRS for part in Path(p).parts[:-1])]
    except (OSError, subprocess.SubprocessError):
        pass
    files = []
    for dirpath, dirnames, filenames in os.walk(str(root)):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        rel = os.path.relpath(dirpath, str(root))
        files.extend(os.path.normpath(os.path.join(rel, f)) for f in filenames)
    return files


def _package_json(root):
    try:
        data = json.loads((root / "package.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    deps = sorted(set(data.get("dependencies", {})) | set(data.get("devDependencies", {})))
    pm = next((m for f, m in (("pnpm-lock.yaml", "pnpm"), ("yarn.lock", "yarn"),
                               ("bun.lockb", "bun"), ("package-lock.json", "npm"))
               if (root / f).exists()), "npm")
    return {"scripts": data.get("scripts", {}), "deps": deps[:40], "package_manager": pm}


def detect(project):
    root = project.root
    files = list_files(root)
    langs = Counter(LANG_EXT[Path(f).suffix] for f in files if Path(f).suffix in LANG_EXT)
    source_count = sum(langs.values())
    tests = sorted({str(Path(f).parent) for f in files if _is_test(f)})[:10]
    top_dirs = Counter(Path(f).parts[0] for f in files if len(Path(f).parts) > 1)
    result = {
        "root": str(root),
        "files": len(files),
        "source_files": source_count,
        "large_repo": source_count > LARGE_REPO,
        "languages": dict(langs.most_common(8)),
        "top_dirs": dict(top_dirs.most_common(12)),
        "manifests": [m for m in MANIFESTS if (root / m).exists()],
        "entry_candidates": [f for f in files if Path(f).name in ENTRY_NAMES][:10],
        "test_dirs": tests,
        "node": _package_json(root) if (root / "package.json").exists() else None,
        "docs": {n: (project.docs_dir / n).exists()
                 for n in ("summary.md", "architecture.md", "decisions.md", "known-issues.md")},
        "claude_md_block": _has_block(root / "CLAUDE.md"),
        "uccif_v2": _v2_traces(root),
        "lsp": _lsp_status(langs),
        "no_lsp": sorted(l for l in langs if l not in _lsp_status(langs)
                         and l not in ("css", "scss", "less")),
    }
    return result


TEST_DIRS = {"test", "tests", "__tests__", "spec", "specs", "e2e"}


def _is_test(path):
    p = Path(path)
    if p.suffix not in LANG_EXT:
        return False
    name = p.name.lower()
    return (any(part.lower() in TEST_DIRS for part in p.parts[:-1])
            or ".test." in name or ".spec." in name
            or name.startswith("test_") or name.endswith("_test" + p.suffix))


def _has_block(path):
    try:
        return "<!-- UCCIF:BEGIN -->" in path.read_text(encoding="utf-8")
    except OSError:
        return False


def _v2_traces(root):
    found = [p for p in (".claude/scripts/uccif.py", ".claude/data/VERSION",
                         ".claude/data/config.json") if (root / p).exists()]
    for name in ("settings.json", "settings.local.json"):
        try:
            if "uccif.py" in (root / ".claude" / name).read_text(encoding="utf-8"):
                found.append(".claude/%s (hooks call uccif.py)" % name)
        except OSError:
            pass
    return found


def _lsp_status(langs):
    """Only languages this plugin configures an LSP for (.lsp.json). Others are listed
    under `no_lsp`: the code index covers them and there is nothing to install."""
    from uccif_lib.hooks import LSP_BUNDLED
    out = {}
    for lang in langs:
        if lang in LSP_BUNDLED:
            binary, cmd = LSP_BUNDLED[lang]
            out[lang] = {"binary": binary, "installed": bool(shutil.which(binary)), "install": cmd}
    return out


def doctor(project):
    """Return (ok, lines). Checks the install, not the project."""
    lines, ok = [], True

    def check(cond, good, bad):
        nonlocal ok
        lines.append(("OK    " if cond else "WARN  ") + (good if cond else bad))
        ok = ok and cond

    def info(text):
        lines.append("INFO  " + text)

    check(sys.version_info >= (3, 8), "python %s" % sys.version.split()[0], "python < 3.8")
    check(True, "uccif %s" % __version__, "")
    dr = data_root()
    try:
        dr.mkdir(parents=True, exist_ok=True)
        probe = dr / ".probe"
        probe.write_text("x")
        probe.unlink()
        check(True, "data dir writable: %s" % dr, "")
    except OSError:
        # Expected when run from Claude's Bash: the sandbox denies writes under ~/.claude.
        # Hooks run outside the sandbox and keep the index and logs current.
        info("data dir read-only in this shell (Claude Code sandbox); hooks write it: %s" % dr)
    try:
        from uccif_lib.paths import ensure_local
        ensure_local(project)
        check(True, "task state writable: %s" % project.local_dir, "")
    except OSError as e:
        check(False, "", "task state not writable: %s (%s)" % (project.local_dir, e))
    check(bool(os.environ.get("UCCIF_DATA_DIR") or os.environ.get("CLAUDE_PLUGIN_DATA")),
          "data dir passed by Claude Code", "UCCIF_DATA_DIR not set: SessionStart has not run in this shell (fallback used)")

    week = datetime.now().astimezone() - timedelta(days=7)
    seen = Counter()
    errors = slow = 0
    for r in log.read(project, "hooks.jsonl"):
        try:
            if datetime.fromisoformat(r.get("ts")) < week:
                continue
        except (TypeError, ValueError):
            continue
        seen[r.get("event")] += 1
        errors += r.get("decision") == "error"
        slow += bool(r.get("slow"))
    for ev in ("session-start", "user-prompt-submit", "stop"):
        check(seen[ev] > 0, "hook %s ran %d× in 7 days" % (ev, seen[ev]),
              "hook %s never ran in 7 days (plugin disabled or hooks not loaded?)" % ev)
    check(errors == 0, "no hook errors in 7 days", "%d hook errors in 7 days: uccif log hooks --only-errors" % errors)
    check(slow == 0, "no slow hooks", "%d slow hook runs in 7 days" % slow)

    from uccif_lib import index, ts_parse
    av = ts_parse.availability()
    if any(av.values()):
        info("tree-sitter active for: %s (precise symbols and imports)"
             % ", ".join(k for k, v in av.items() if v))
    else:
        info("tree-sitter not installed: symbols come from ctags/regex (approximate). Optional: "
             "pip install tree-sitter tree-sitter-javascript tree-sitter-typescript tree-sitter-python")
    idx = index.status(project)
    check(index.exists(project), idx[0], idx[0])
    d = detect(project)
    check(d["claude_md_block"], "CLAUDE.md has UCCIF block", "CLAUDE.md has no UCCIF block (run uccif:init)")
    check(d["docs"]["summary.md"], "project docs present", "no .claude/uccif/summary.md (run uccif:init)")
    check(not d["uccif_v2"], "no UCCIF v2 leftovers", "UCCIF v2 still installed: %s" % ", ".join(d["uccif_v2"]))
    for lang, s in d["lsp"].items():
        check(s["installed"], "LSP for %s: %s" % (lang, s["binary"]),
              "LSP for %s missing: install %s with `%s`, then /reload-plugins"
              % (lang, s["binary"], s["install"]))
    if d["no_lsp"]:
        info("no LSP configured for %s; the code index covers these files (nothing to install)"
             % ", ".join(d["no_lsp"]))
    return ok, lines
