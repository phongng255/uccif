"""Generate the Codex workflow plugin and its separate local marketplace.

The package contains a materialized core, never links outside its root. Native hooks
remain gated on real-client event verification. Run with --check to detect stale copies.
"""

import json
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN))
from uccif_lib import __version__, codex_workflows  # noqa: E402

REPO = PLUGIN.parent.parent
DST = REPO / "plugins" / "uccif-codex"
MARKETPLACE = REPO / ".agents" / "plugins" / "marketplace.json"


def _json(value):
    return json.dumps(value, indent=2) + "\n"


def files():
    manifest = {"$schema": "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json",
                "name": "uccif", "version": __version__,
                "description": "UCCIF project notes, task resume and CodeGraph workflows for Codex. "
                               "Workflow preview; no lifecycle hooks."}
    out = {"plugin.json": _json(manifest)}
    for name, text in codex_workflows.packaged_skills().items():
        out["skills/%s/SKILL.md" % name] = text
    for path in sorted((PLUGIN / "uccif_lib").glob("*.py")):
        out["core/uccif_lib/" + path.name] = path.read_text(encoding="utf-8")
    out["core/scripts/uccif_main.py"] = (PLUGIN / "scripts/uccif_main.py").read_text(encoding="utf-8")
    # Core setup reads this canonical server definition when the user opts into MCP.
    # This is deliberately not a bundled auto-starting server in the workflow-only preview.
    out["core/.mcp.json"] = (PLUGIN / ".mcp.json").read_text(encoding="utf-8")
    out["LICENSE"] = (REPO / "LICENSE").read_text(encoding="utf-8")
    return out


def marketplace():
    return _json({"name": "uccif-codex-local", "interface": {"displayName": "UCCIF for Codex"},
                  "plugins": [{"name": "uccif", "source": {
                      "source": "local", "path": "./plugins/uccif-codex"},
                      "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
                      "category": "Productivity"}]})


def build(check=False):
    expected = {DST / rel: text for rel, text in files().items()}
    expected[MARKETPLACE] = marketplace()
    stale = []
    for path, text in expected.items():
        old = path.read_bytes().decode("utf-8") if path.exists() else None
        if old != text:
            stale.append(path.relative_to(REPO).as_posix())
            if not check:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(text.encode("utf-8"))
    # Never silently delete package resources. Extra files require a deliberate review.
    extra = [p.relative_to(REPO).as_posix() for p in DST.rglob("*") if p.is_file()
             and p not in expected and "__pycache__" not in p.parts] if DST.exists() else []
    return stale, extra


if __name__ == "__main__":
    checking = "--check" in sys.argv
    stale, extra = build(checking)
    if extra or (checking and stale):
        print("Codex package out of date: %s" % ", ".join(stale + extra))
        sys.exit(1)
    print("Codex workflow plugin: %s" % ("up to date" if not stale else "%d files written" % len(stale)))
