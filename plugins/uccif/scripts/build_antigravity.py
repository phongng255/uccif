"""Build the Antigravity plugin (plugins/uccif-antigravity/) from the core plugin: one source,
never edited by hand. Only `core`, a symlink to ../uccif, is not generated; `agy plugin install`
copies its target into the installed plugin.

The plugin has its own directory because Antigravity warns about a hooks/hooks.json at a plugin
root ("never loaded"), which fails `agy plugin validate --strict`, and the repo root needs that
file for the Gemini extension. tests/test_antigravity.py fails when the files are out of date.

Usage: python plugins/uccif/scripts/build_antigravity.py [--check]
"""

import json
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN))

from uccif_lib import hostfiles  # noqa: E402

DST = PLUGIN.parent / "uccif-antigravity"
# Tools that change a file. Antigravity 1.4.12 names; hooks.py tracks these in the task.
EDIT_MATCHER = "edit_file|write_file|write_to_file|replace_file_content|multi_replace_file_content"


def _handler(event, timeout):
    # hooks run with the plugin root as cwd; their paths must be relative (Build plugins docs)
    return {"type": "command", "command": "./core/bin/uccif hook --host antigravity %s" % event,
            "timeout": timeout}


def hooks_config():
    """PreToolUse is left out on purpose: its required `decision` can only allow, deny or ask, and
    "allow" skips the user's permission prompt. UCCIF must never change what a tool may do."""
    return {"uccif": {
        "SessionStart": [_handler("SessionStart", 10)],
        "PreInvocation": [_handler("PreInvocation", 5)],
        "PostToolUse": [{"matcher": EDIT_MATCHER, "hooks": [_handler("PostToolUse", 5)]}],
        "Stop": [_handler("Stop", 10)],
    }}


def manifest():
    src = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    return {
        "$schema": "https://antigravity.google/schemas/v1/plugin.json",
        "name": src["name"],
        "displayName": src["displayName"],
        "version": src["version"],
        "description": "Task memory, project notes and CodeGraph setup for any repository. "
                       "Same core as the UCCIF Claude Code plugin. Never blocks.",
        "author": src["author"],
        "homepage": src["homepage"],
        "repository": src["repository"],
        "license": src["license"],
    }


def _json(data):
    return json.dumps(data, indent=2) + "\n"


def files():
    out = {"plugin.json": _json(manifest()), "hooks.json": _json(hooks_config()),
           "mcp_config.json": hostfiles.mcp_config_text(),
           "rules/AGENTS.md": hostfiles.context_text("antigravity")}
    for name, text in hostfiles.skills("antigravity").items():
        out["skills/%s/SKILL.md" % name] = text
    return out


def build(check=False):
    want = files()
    stale = hostfiles.write_tree(want, DST, check)
    extra = [p.relative_to(DST).as_posix() for p in (DST / "skills").glob("*/SKILL.md")
             if p.relative_to(DST).as_posix() not in want]
    return stale, extra


if __name__ == "__main__":
    check = "--check" in sys.argv
    stale, extra = build(check)
    if check and (stale or extra):
        print("out of date: %s; run python plugins/uccif/scripts/build_antigravity.py" % ", ".join(stale + extra))
        sys.exit(1)
    print("antigravity plugin: %s" % (", ".join(stale) + " written" if stale else "up to date"))
