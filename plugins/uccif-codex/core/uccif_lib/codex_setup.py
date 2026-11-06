"""Repository-scoped Codex setup. No hook trust, home config or task-history writes.

Only unchanged owned files/blocks may be updated or removed. A manifest never grants
permission to follow a symlink outside the project. MCP edits are opt-in and conservative.
"""

import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from uccif_lib import codegraph, codex_workflows
from uccif_lib.paths import file_lock, write_json, write_text_atomic
from uccif_lib.rules import core_rules

MANIFEST = ".codex/.uccif-setup.json"
AGENTS_BEGIN, AGENTS_END = "<!-- UCCIF:CODEX:BEGIN -->", "<!-- UCCIF:CODEX:END -->"
MCP_BEGIN, MCP_END = "# UCCIF:CODEX:MCP:BEGIN", "# UCCIF:CODEX:MCP:END"
BLOCKS = {"AGENTS.md": (AGENTS_BEGIN, AGENTS_END),
          ".codex/config.toml": (MCP_BEGIN, MCP_END)}


def _hash(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _read(path):
    return path.read_bytes().decode("utf-8") if path.exists() else ""


def _safe(root, rel):
    """Reject absolute/traversing paths and all symlinked components, including dangling links."""
    p = Path(rel)
    if p.is_absolute() or ".." in p.parts or not p.parts:
        raise ValueError("unsafe setup path: %s" % rel)
    target = root / p
    for part in [target] + list(target.parents):
        if part == root:
            break
        if part.is_symlink():
            raise ValueError("symlinked setup path: %s" % rel)
    return target


def _manifest(root):
    manifest = _safe(root, MANIFEST)
    state = json.loads(_read(manifest)) if manifest.exists() else {}
    if not isinstance(state, dict) or not isinstance(state.get("files", {}), dict):
        raise ValueError("invalid Codex setup manifest")
    owned = state.get("files", {})
    allowed = {".agents/skills/%s/SKILL.md" % n for n in codex_workflows.WORKFLOWS} | set(BLOCKS)
    if any(rel not in allowed or not isinstance(entry, dict) for rel, entry in owned.items()):
        raise ValueError("invalid owned path in Codex setup manifest")
    return state


def command():
    script = Path(__file__).resolve().parents[1] / "scripts" / "uccif_main.py"
    argv = [sys.executable, str(script)]
    return subprocess.list2cmdline(argv) if os.name == "nt" else " ".join(map(shlex.quote, argv))


def _agents(cmd):
    # Rule 4 is replaced: setup does not enable automatic hooks/task memory.
    rules = core_rules("vi").splitlines()
    rules = [line for line in rules if not line.startswith("4.")]
    return "\n".join([AGENTS_BEGIN, "## UCCIF for Codex"] + rules + [
        "Task tracking is manual in this Codex setup; no lifecycle hooks are installed.",
        "Use `$uccif` with init, resume, codegraph or status, or the dedicated uccif-codex-* skills.",
        "Run UCCIF from this project directory: `%s`." % cmd,
        "Task memory, decisions and notes are shared with other hosts at `.claude/uccif/`.",
        "Read `.claude/uccif/summary.md` when present. Never estimate tokens or change hook trust.",
        AGENTS_END]) + "\n"


def _mcp():
    cfg = codegraph.PLUGIN_ROOT / ".mcp.json"
    server = json.loads(cfg.read_text(encoding="utf-8"))["mcpServers"]["codegraph"]
    # JSON strings and arrays of strings are valid TOML basic strings/arrays.
    out = [MCP_BEGIN, "[mcp_servers.codegraph]",
           "command = " + json.dumps(server["command"]), "args = " + json.dumps(server["args"])]
    if server.get("env"):
        out.append("[mcp_servers.codegraph.env]")
        out.extend("%s = %s" % (json.dumps(k), json.dumps(v)) for k, v in server["env"].items())
    return "\n".join(out + [MCP_END]) + "\n"


def _toml(text):
    try:
        import tomllib
    except ImportError:
        try:
            import tomli as tomllib
        except ImportError:
            return None
    try:
        return tomllib.loads(text)
    except ValueError:
        return None


def _config_paths(root):
    home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
    # Codex can load parent project layers as well as the current repository layer.
    return [home / "config.toml"] + [p / ".codex" / "config.toml"
            for p in reversed([root] + list(root.parents))]


def mcp_status(project):
    """Configured is not connected. Unknown TOML/plugin layers never count as ready."""
    root = Path(project.root)
    entries, unknown = [], False
    for path in dict.fromkeys(_config_paths(root)):
        if not path.exists():
            continue
        try:
            data = _toml(_read(path))
        except (OSError, UnicodeError):
            data = None
        if not isinstance(data, dict):
            unknown = True
            continue
        servers = data.get("mcp_servers", {})
        if not isinstance(servers, dict):
            unknown = True
            continue
        for name, cfg in servers.items():
            if "codegraph" in name.lower() or "codegraph" in json.dumps(cfg, default=str).lower():
                entries.append({"source": str(path), "name": name,
                                "enabled": isinstance(cfg, dict) and cfg.get("enabled", True) is not False})
        # Plugin config does not expose every installed plugin's bundled server. Do not guess.
        if data.get("plugins"):
            unknown = True
    configured = any(e["enabled"] for e in entries)
    return {"configured": configured, "verified": False, "unknown": unknown,
            "entries": entries, "mcp_via": "config" if configured else None}


def _span(text, rel):
    begin, end = BLOCKS[rel]
    if begin not in text and end not in text:
        return None
    if text.count(begin) != 1 or text.count(end) != 1:
        raise ValueError("ambiguous UCCIF block in %s" % rel)
    a, b = text.index(begin), text.index(end) + len(end)
    if b < a + len(begin):
        raise ValueError("invalid UCCIF block in %s" % rel)
    if text[b:b + 2] == "\r\n":
        b += 2
    elif text[b:b + 1] == "\n":
        b += 1
    return a, b


def _plan(root, owned, rel, new):
    path = _safe(root, rel)
    old = _read(path)
    entry = owned.get(rel)
    if rel in BLOCKS:
        span = _span(old, rel)
        if span:
            a, b = span
            if not entry or _hash(old[a:b]) != entry.get("sha256"):
                return None, None, "existing block is unowned or you edited it"
            return old[:a] + new + old[b:], dict(entry, sha256=_hash(new)), None
        if entry:
            return None, None, "owned block was removed; preserving your change"
        sep = "" if not old or old.endswith("\n\n") else ("\n" if old.endswith("\n") else "\n\n")
        return old + sep + new, {"sha256": _hash(new), "separator": sep,
                                 "created": not path.exists()}, None
    if path.exists() and (not entry or _hash(old) != entry.get("sha256")):
        return None, None, "existing file is unowned or you edited it"
    if not path.exists() and entry:
        return None, None, "owned file was removed; preserving your change"
    return new, {"sha256": _hash(new)}, None


def setup(project, dry_run=False, with_codegraph=False):
    root = Path(project.root)
    state = _manifest(root)
    owned = dict(state.get("files", {}))
    desired = {"AGENTS.md": _agents(command())}
    desired.update({".agents/skills/%s/SKILL.md" % n: t
                    for n, t in codex_workflows.skills(command()).items()})
    lines = []
    if with_codegraph:
        status = mcp_status(project)
        own_mcp = ".codex/config.toml" in owned
        external = [e for e in status["entries"] if not
                    (own_mcp and e["source"] == str(root / ".codex/config.toml") and e["name"] == "codegraph")]
        if status["unknown"] or external:
            lines.append("Skipped MCP: existing/disabled server or unknown config/plugin wiring; no duplicate added.")
            lines.append("Review the existing server before adding this project snippet:\n" + _mcp())
        else:
            desired[".codex/config.toml"] = _mcp()
    changes = []
    for rel, new in desired.items():
        text, entry, reason = _plan(root, owned, rel, new)
        if reason:
            lines.append("Skipped %s: %s." % (rel, reason))
            continue
        if _read(root / rel) != text:
            changes.append((rel, text))
            lines.append(("Would write " if dry_run else "Wrote ") + rel)
        owned[rel] = entry
    # Validate every destination before any file is written.
    manifest = _safe(root, MANIFEST)
    if not dry_run:
        updated = {"version": 1, "files": owned, "mode": "repository", "hooks_verified": False}
        previous = [(rel, (root / rel).read_bytes() if (root / rel).exists() else None)
                    for rel, _ in changes]
        applied = []
        try:
            for (rel, text), (_, original) in zip(changes, previous):
                write_text_atomic(_safe(root, rel), text)
                applied.append((rel, original))
            if state != updated:
                write_json(manifest, updated)
        except OSError:
            # Do not strand partially written files without ownership if a later write fails.
            for rel, original in reversed(applied):
                path = _safe(root, rel)
                if original is None:
                    if path.exists():
                        path.unlink()
                elif path.exists():
                    path.write_bytes(original)
            raise
    lines += ["Codex repository workflows: $uccif init | resume | codegraph | status.",
              "No hooks installed; automatic tracking and token footer unavailable. App/IDE UI not verified.",
              "Generated instructions/skills contain this machine's core path; do not commit them.",
              "Undo with uccif setup codex --remove."]
    return lines


def remove(project, dry_run=False):
    root = Path(project.root)
    state = _manifest(root)
    owned = state.get("files", {})
    if not owned:
        return ["Nothing to remove: no Codex setup manifest."]
    kept, changes, lines = {}, [], []
    for rel, entry in owned.items():
        path = _safe(root, rel)
        if not path.exists():
            continue
        text = _read(path)
        if rel in BLOCKS:
            span = _span(text, rel)
            if not span:
                continue
            a, b = span
            chunk = text[a:b]
            sep = entry.get("separator", "")
            if sep and text[:a].endswith(sep):
                a -= len(sep)
            new = text[:a] + text[b:]
        else:
            chunk, new = text, ""
        if _hash(chunk) != entry.get("sha256"):
            kept[rel] = entry
            lines.append("Kept %s: you edited it." % rel)
            continue
        delete = not new and (rel not in BLOCKS or entry.get("created"))
        changes.append((rel, new, delete))
        lines.append(("Would remove " if dry_run else "Removed ") + rel)
    if not dry_run:
        for rel, new, delete in changes:
            path = _safe(root, rel)
            if delete:
                path.unlink()
            else:
                write_text_atomic(path, new)
            parent = path.parent
            while parent != root and parent != root / ".codex":
                try:
                    parent.rmdir()
                except OSError:
                    break
                parent = parent.parent
        manifest = _safe(root, MANIFEST)
        if kept:
            write_json(manifest, dict(state, files=kept))
        else:
            manifest.unlink()
            try:
                manifest.parent.rmdir()
            except OSError:
                pass
    return lines


def run(project, remove_=False, dry_run=False, with_codegraph=False):
    """Serialize mutations. A dry run creates neither directories nor locks."""
    if dry_run:
        return remove(project, True) if remove_ else setup(project, True, with_codegraph)
    root = Path(project.root)
    lock = _safe(root, ".codex/.uccif-setup.lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    with file_lock(lock):
        lines = remove(project) if remove_ else setup(project, with_codegraph=with_codegraph)
    if remove_:
        try:
            lock.parent.rmdir()
        except OSError:
            pass
    return lines


def doctor(project):
    root = Path(project.root)
    state = _manifest(root)
    core = Path(__file__).resolve().parents[1]
    package_manifest = core.parent / "plugin.json"
    packaged = core.name == "core" and package_manifest.is_file()
    if packaged:
        lines = ["Codex install mode: packaged core (running from this plugin's files)"]
    else:
        lines = ["Codex install mode: repository" if state else "Codex repository setup: not installed"]
    cli = shutil.which("codex")
    lines.append("Codex CLI: %s" % (cli or "not found; app/IDE versions not inspected"))
    lines.append("Codex app/IDE skill loading: unverified (requires a real client session)")
    lines.append("Codex hooks: not installed; automatic task tracking unavailable")
    lines.append("Codex token footer and LSP integration: unavailable")
    mcp = mcp_status(project)
    lines.append("CodeGraph MCP: %s; runtime connection unverified" %
                 ("configured" if mcp["configured"] else "unknown" if mcp["unknown"] else "not configured"))
    lines.append("CodeGraph CLI: %s" % (codegraph.cli() or "not installed"))
    lines.append("CodeGraph index: %s" % ("present" if codegraph.indexed(project) else "absent"))
    return bool(state) or packaged, lines
