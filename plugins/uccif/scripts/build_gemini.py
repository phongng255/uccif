"""Build the Gemini CLI extension's skills (<repo>/skills/) from the Claude Code plugin's
skills (plugins/uccif/skills/): one source, never edited by hand.

Gemini CLI reads an extension's skills from skills/<name>/SKILL.md at the extension root, and
`gemini extensions install <github url>` only finds gemini-extension.json at the repo root, so
the copies live at the root. tests/test_gemini_extension.py fails when they are out of date.
The substitutions live in uccif_lib/hostfiles.py, shared with the Antigravity plugin.

Usage: python plugins/uccif/scripts/build_gemini.py [--check]
"""

import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN))

from uccif_lib import hostfiles  # noqa: E402

REPO = PLUGIN.parent.parent
SRC, DST = hostfiles.SKILLS, REPO / "skills"


def build(check=False):
    files = {"%s/SKILL.md" % name: text for name, text in hostfiles.skills("gemini").items()}
    stale = [rel.split("/")[0] for rel in hostfiles.write_tree(files, DST, check)]
    names = {p.parent.name for p in SRC.glob("*/SKILL.md")}
    extra = [p.parent.name for p in DST.glob("*/SKILL.md") if p.parent.name not in names] if DST.is_dir() else []
    return stale, extra


if __name__ == "__main__":
    check = "--check" in sys.argv
    stale, extra = build(check)
    if check and (stale or extra):
        print("out of date: %s; run python plugins/uccif/scripts/build_gemini.py" % ", ".join(stale + extra))
        sys.exit(1)
    print("skills: %s" % (", ".join(stale) + " written" if stale else "up to date"))
