"""Drift: notice structural changes that make the project docs stale.

A fingerprint of the repo's shape (source dirs to depth 2, manifest hashes,
declared dependencies) is kept in <project data>/drift.json, outside the repo
so branches and teammates never conflict over it. `check` compares it with the
current repo and records pending items naming the doc to update; the next
UserPromptSubmit hook hands them to Claude. Changes inside a function never
count as drift. `ack` stores the current fingerprint once docs are updated.
"""

import hashlib
import json
import re
from pathlib import PurePosixPath

from uccif_lib.paths import now_iso, read_json, write_json

MANIFESTS = ("package.json", "pyproject.toml", "requirements.txt", "go.mod", "Cargo.toml",
             "pom.xml", "build.gradle", "build.gradle.kts", "composer.json", "Gemfile",
             "pubspec.yaml", "firebase.json", "tsconfig.json", "vite.config.ts", "vite.config.js",
             "nuxt.config.ts", "next.config.js", "Dockerfile", "docker-compose.yml")
MAX_PENDING = 5


def _file(project):
    return project.data_dir / "drift.json"


def _deps(root):
    deps = set()
    try:
        data = json.loads((root / "package.json").read_text(encoding="utf-8"))
        for key in ("dependencies", "devDependencies"):
            deps.update("npm:" + d for d in (data.get(key) or {}))
    except (OSError, ValueError, AttributeError):
        pass
    try:
        for line in (root / "requirements.txt").read_text(encoding="utf-8").splitlines():
            m = re.match(r"\s*([A-Za-z0-9_.\-]+)", line)
            if m and not line.strip().startswith(("#", "-")):
                deps.add("py:" + m.group(1).lower())
    except OSError:
        pass
    return deps


def fingerprint(project, files=None):
    from uccif_lib.index import list_source_files
    root = project.root
    files = files if files is not None else list_source_files(root)
    dirs = set()
    for f in files:
        parts = PurePosixPath(f).parts[:-1]
        if parts:
            dirs.add(parts[0])
            if len(parts) > 1:
                dirs.add("/".join(parts[:2]))
    manifests = {}
    for m in MANIFESTS:
        try:
            manifests[m] = hashlib.sha1((root / m).read_bytes()).hexdigest()[:12]
        except OSError:
            pass
    return {"dirs": sorted(dirs), "manifests": manifests, "deps": sorted(_deps(root))}


def diff(old, new):
    """Human-readable drift items: (what changed, doc to update)."""
    items = []
    add = sorted(set(new["dirs"]) - set(old.get("dirs", [])))
    rem = sorted(set(old.get("dirs", [])) - set(new["dirs"]))
    if add:
        items.append(("new source dirs: %s" % ", ".join(add[:6]), "architecture.md (+ summary.md layout)"))
    if rem:
        items.append(("removed source dirs: %s" % ", ".join(rem[:6]), "architecture.md (+ summary.md layout)"))
    dadd = sorted(set(new["deps"]) - set(old.get("deps", [])))
    drem = sorted(set(old.get("deps", [])) - set(new["deps"]))
    if dadd or drem:
        parts = (["added " + ", ".join(d.split(":", 1)[1] for d in dadd[:6])] if dadd else []) + \
                (["removed " + ", ".join(d.split(":", 1)[1] for d in drem[:6])] if drem else [])
        items.append(("dependencies: %s" % "; ".join(parts), "summary.md (stack)"))
    om, nm = old.get("manifests", {}), new["manifests"]
    changed = sorted(m for m in set(om) | set(nm) if om.get(m) != nm.get(m))
    other = [m for m in changed if m not in ("package.json", "requirements.txt") or not (dadd or drem)]
    if other:
        items.append(("build/config files changed: %s" % ", ".join(other[:6]),
                      "summary.md (commands) and architecture.md if entry/routing/build changed"))
    return items


def check(project, files=None):
    """Compare with the stored fingerprint. First run only stores a baseline."""
    state = read_json(_file(project), {}) or {}
    new = fingerprint(project, files)
    if "fingerprint" not in state:
        write_json(_file(project), {"fingerprint": new, "pending": [], "updated": now_iso()})
        return []
    items = diff(state["fingerprint"], new)
    if not (project.docs_dir / "summary.md").exists():
        # nothing to keep in sync yet: init will describe the current shape
        write_json(_file(project), {"fingerprint": new, "pending": [], "updated": now_iso()})
        return []
    pending = ["%s -> update %s" % it for it in items][:MAX_PENDING]
    if pending != state.get("pending", []):  # new drift, or a change was reverted
        state.update(pending=pending, updated=now_iso())
        write_json(_file(project), state)
    return pending


def pending(project):
    return (read_json(_file(project), {}) or {}).get("pending", [])


def ack(project):
    write_json(_file(project), {"fingerprint": fingerprint(project), "pending": [], "updated": now_iso()})
