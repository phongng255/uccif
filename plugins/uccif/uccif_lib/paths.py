"""Locate the project root, the plugin data dir and the per-project data dir.

Per-project data lives in <data_root>/projects/<key>/ where <key> is a hash of
the project's real path. Each dir has meta.json recording the path and the
repo's root commit. If a project is opened at a new path, has no data yet, and
an existing entry has the same root commit but its old path no longer exists,
the entry is treated as a renamed/moved repo and its data is moved over.
Two live clones/worktrees of one repo therefore never share task or index data.
"""

import hashlib
import json
import os
import shutil
import subprocess
import time
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

DOCS_SUBDIR = Path(".claude") / "uccif"
# Data dir id of the core plugin installed as uccif@uccif, and the file only the
# core plugin writes there (SessionStart caches userConfig in it).
CORE_DATA_NAME = "uccif-uccif"
CORE_MARKER = "options.json"
LOCAL_SUBDIR = ".local"


def now_iso():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def write_text_atomic(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # a name per writer: two sessions starting together write the same file
    tmp = path.with_name("%s.%s.tmp" % (path.name, uuid.uuid4().hex))
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(str(tmp), str(path))
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


class LockTimeout(Exception):
    pass


@contextmanager
def file_lock(path, timeout=3.0, stale=30.0):
    """Cross-process lock via an O_EXCL lock file (stdlib, works on Windows).

    Two sessions on one project share its task state; this keeps their
    read-modify-write cycles from interleaving. A lock older than `stale`
    seconds is assumed to belong to a crashed process and is taken over.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.time() + timeout
    while True:
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                if time.time() - path.stat().st_mtime > stale:
                    path.unlink()
                    continue
            except OSError:
                continue  # released (or taken over) between the two calls
            if time.time() >= deadline:
                raise LockTimeout("%s is held by another process" % path)
            time.sleep(0.05)
            continue
        os.write(fd, str(os.getpid()).encode("ascii"))
        os.close(fd)
        break
    try:
        yield
    finally:
        try:
            path.unlink()
        except OSError:
            pass


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write_json(path, data):
    write_text_atomic(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def _git(args, cwd, timeout=5):
    try:
        out = subprocess.run(
            ["git"] + args, cwd=str(cwd), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def project_root(cwd=None):
    """CLAUDE_PROJECT_DIR (Gemini CLI sets it too, as an alias), GEMINI_PROJECT_DIR, else the
    git toplevel of cwd, else cwd itself."""
    env = os.environ.get("CLAUDE_PROJECT_DIR") or os.environ.get("GEMINI_PROJECT_DIR")
    if env and os.path.isdir(env):
        return Path(os.path.realpath(env))
    cwd = Path(cwd or os.getcwd())
    top = _git(["rev-parse", "--show-toplevel"], cwd)
    return Path(os.path.realpath(top or str(cwd)))


def data_root_source():
    """(path, source) of the plugin-wide persistent data dir.

    Hooks receive CLAUDE_PLUGIN_DATA; commands run through Claude's Bash tool do
    not, so SessionStart exports UCCIF_DATA_DIR via CLAUDE_ENV_FILE. As a last
    resort use the core plugin's data dir under ~/.claude/plugins/data/: the
    one installed from this marketplace (uccif-uccif), else the most recently
    used dir holding the core marker. A bare uccif-* glob is not enough: sibling
    plugins (uccif-strict, uccif-codeintel) get data dirs with the same prefix.
    """
    for var in ("UCCIF_DATA_DIR", "CLAUDE_PLUGIN_DATA"):
        val = os.environ.get(var)
        if val:
            return Path(val), var
    base = Path.home() / ".claude" / "plugins" / "data"
    exact = base / CORE_DATA_NAME
    if (exact / CORE_MARKER).exists():
        return exact, "fallback-exact"
    cands = [p for p in base.glob("uccif-*") if (p / CORE_MARKER).is_file()]
    if cands:
        return max(cands, key=lambda p: (p / CORE_MARKER).stat().st_mtime), "fallback-marker"
    if exact.is_dir():
        return exact, "fallback-exact"
    return Path.home() / ".uccif", "fallback-home"


def data_root():
    return data_root_source()[0]


def root_commit(root):
    out = _git(["rev-list", "--max-parents=0", "HEAD"], root)
    if not out:
        return None
    return sorted(out.split())[0]


def path_key(root):
    norm = os.path.normcase(os.path.realpath(str(root)))
    return hashlib.sha1(norm.encode("utf-8")).hexdigest()[:16]


class Project:
    def __init__(self, root, data_dir, commit, renamed_from=None):
        self.root = Path(root)
        self.data_dir = Path(data_dir)
        self.root_commit = commit
        self.renamed_from = renamed_from

    @property
    def key(self):
        return self.data_dir.name

    @property
    def docs_dir(self):
        return self.root / DOCS_SUBDIR

    @property
    def local_dir(self):
        """Per-checkout state the CLI must write from inside Claude Code's Bash sandbox
        (task memory, drift state). The sandbox never lets commands write under ~/.claude,
        but the working directory is writable; .claude/uccif/.gitignore keeps it out of git."""
        return self.docs_dir / LOCAL_SUBDIR


def ensure_local(project):
    """Create .claude/uccif/.local/ and make sure git ignores it."""
    project.local_dir.mkdir(parents=True, exist_ok=True)
    gi = project.docs_dir / ".gitignore"
    try:
        lines = gi.read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    if LOCAL_SUBDIR + "/" not in lines:
        with open(str(gi), "a", encoding="utf-8") as f:
            f.write(("\n" if lines and lines[-1] else "") +
                    "# UCCIF per-checkout state (task memory, drift); never commit\n%s/\n" % LOCAL_SUBDIR)
    return project.local_dir


def _find_moved(projects_dir, commit, new_root):
    """Entries with the same root commit whose recorded path no longer exists."""
    found = []
    for meta_path in projects_dir.glob("*/meta.json"):
        meta = read_json(meta_path, {})
        old = meta.get("path")
        if meta.get("root_commit") != commit or not old:
            continue
        if os.path.realpath(old) == str(new_root) or os.path.exists(old):
            continue
        found.append((meta.get("updated", ""), meta_path.parent, old))
    found.sort(reverse=True)
    return found[0] if found else None


def resolve_project(cwd=None, create=True):
    root = project_root(cwd)
    projects_dir = data_root() / "projects"
    data_dir = projects_dir / path_key(root)
    meta_path = data_dir / "meta.json"
    meta = read_json(meta_path, {}) or {}
    # `git rev-list --max-parents=0` walks the whole history, and this runs on
    # every hook: reuse the commit cached in meta.json for a known path.
    if meta.get("path") == str(root) and meta.get("root_commit"):
        commit = meta["root_commit"]
    else:
        commit = root_commit(root)
    renamed_from = None

    try:
        if not data_dir.exists() and create:
            moved = _find_moved(projects_dir, commit, root) if commit else None
            if moved:
                _, old_dir, renamed_from = moved
                projects_dir.mkdir(parents=True, exist_ok=True)
                shutil.move(str(old_dir), str(data_dir))
        if create:
            _write_meta(data_dir, meta_path, root, commit, renamed_from)
    except OSError:
        # Claude Code's Bash sandbox denies writes under ~/.claude. Commands run there
        # only read what hooks (which run outside the sandbox) keep current.
        pass
    return Project(root, data_dir, commit, renamed_from)


def _write_meta(data_dir, meta_path, root, commit, renamed_from):
    data_dir.mkdir(parents=True, exist_ok=True)
    meta = read_json(meta_path, {}) or {}
    changed = (
        meta.get("path") != str(root)
        or (commit and meta.get("root_commit") != commit)
        or renamed_from
    )
    if changed or not meta:
        meta.setdefault("created", now_iso())
        meta["path"] = str(root)
        meta["root_commit"] = commit or meta.get("root_commit")
        meta["updated"] = now_iso()
        if renamed_from:
            meta.setdefault("renamed_from", []).append(renamed_from)
        write_json(meta_path, meta)
