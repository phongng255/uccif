"""`uccif setup antigravity [--remove]`: the project's .agents/ files for the Antigravity IDE.

Writes the always-on rule, the skills and the CodeGraph MCP server. No hooks: a workspace hook
would need this machine's absolute path in .agents/hooks.json. .agents/.uccif-setup.json records
what was written, with a hash, so a later run or --remove touches only files UCCIF wrote and the
user has not edited. A file that already exists and is not on that list is never overwritten.
"""

import hashlib
import json
from pathlib import Path

from uccif_lib import hooks, hostfiles
from uccif_lib.paths import read_json, write_json, write_text_atomic
from uccif_lib.rules import core_rules

AGENTS = ".agents"
MANIFEST = ".uccif-setup.json"
RULE = "rules/uccif.md"
MCP = "mcp_config.json"


def _hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def rule_text():
    return ("---\ntrigger: always_on\ndescription: UCCIF core rules for this workspace.\n---\n\n%s\n\n"
            '`uccif` is not on PATH here: run it as `"%s"` (same arguments).\n'
            % (core_rules(hooks.options()["reply_language"]), hooks.UCCIF_BIN.as_posix()))


def files():
    out = {RULE: rule_text(), MCP: hostfiles.mcp_config_text()}
    for name, text in hostfiles.skills("antigravity").items():
        out["skills/%s/SKILL.md" % name] = text
    return out


def setup(project):
    """Returns the lines to print."""
    root = Path(project.root) / AGENTS
    state = read_json(root / MANIFEST, {}) or {}
    owned, dirs = dict(state.get("files") or {}), list(state.get("dirs") or [])
    wrote, skipped = [], []
    for rel, text in sorted(files().items()):
        path = root / rel
        if path.exists():
            if rel not in owned:
                skipped.append((rel, "exists and UCCIF did not write it"))
                continue
            if _hash(path) != owned[rel]:
                skipped.append((rel, "you edited it"))
                continue
        missing = [p for p in [path.parent] + list(path.parent.parents) if not p.exists()
                   and (p == root or root in p.parents)]
        for p in missing:
            rel_dir = "." if p == root else p.relative_to(root).as_posix()
            if rel_dir not in dirs:
                dirs.append(rel_dir)
        write_text_atomic(path, text)
        owned[rel] = _hash(path)
        wrote.append(rel)
    write_json(root / MANIFEST, {"files": owned, "dirs": dirs})
    lines = ["Wrote %d files under %s/ for the Antigravity IDE." % (len(wrote), AGENTS)]
    for rel, why in skipped:
        lines.append("Skipped %s/%s: %s." % (AGENTS, rel, why))
        if rel == MCP:
            lines.append("To get CodeGraph, add this server to it yourself:\n" +
                         json.dumps({"codegraph": hostfiles.codegraph_server()}, indent=2))
    lines.append("%s/%s holds this machine's path to `uccif`: do not commit it." % (AGENTS, RULE))
    lines.append("Using the CLI plugin in this project too? It brings the same CodeGraph server, so "
                 "its tools appear twice.")
    lines.append("Undo with `uccif setup antigravity --remove`.")
    return lines


def remove(project):
    """Delete only what setup wrote and the user has not edited. Returns the lines to print."""
    root = Path(project.root) / AGENTS
    state = read_json(root / MANIFEST)
    if not state:
        return ["Nothing to remove: %s/%s does not exist." % (AGENTS, MANIFEST)]
    removed, kept = 0, []
    for rel, digest in sorted((state.get("files") or {}).items()):
        path = root / rel
        if not path.exists():
            continue
        if _hash(path) != digest:
            kept.append(rel)
            continue
        path.unlink()
        removed += 1
    (root / MANIFEST).unlink()
    # deepest first; a directory holding anything else stays
    for rel_dir in sorted(state.get("dirs") or [], key=lambda d: (d == ".", -d.count("/"))):
        try:
            (root if rel_dir == "." else root / rel_dir).rmdir()
        except OSError:
            pass
    lines = ["Removed %d files from %s/." % (removed, AGENTS)]
    lines.extend("Kept %s/%s: you edited it." % (AGENTS, rel) for rel in kept)
    return lines
