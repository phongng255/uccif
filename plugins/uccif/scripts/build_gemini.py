"""Build the Gemini CLI extension's skills (<repo>/skills/) from the Claude Code plugin's
skills (plugins/uccif/skills/): one source, never edited by hand.

Gemini CLI reads an extension's skills from skills/<name>/SKILL.md at the extension root, and
`gemini extensions install <github url>` only finds gemini-extension.json at the repo root, so
the copies live at the root. tests/test_gemini_extension.py fails when they are out of date.

Usage: python plugins/uccif/scripts/build_gemini.py [--check]
"""

import re
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent
REPO = PLUGIN.parent.parent
SRC, DST = PLUGIN / "skills", REPO / "skills"
HEADER = "<!-- generated from plugins/uccif/skills by plugins/uccif/scripts/build_gemini.py; edit the source -->\n"

# (pattern, replacement): plain-text substitutions, applied in order to every skill
COMMON = [
    (r"^argument-hint:.*\n", ""),  # Claude Code frontmatter only
    (r"`uccif:(\w+)` skill", r"`\1` skill"),
    (r"uccif:(codegraph|resume|init)\b", r"\1"),
    (r"Never use Write/Edit under `\.claude/`\.", "Write under `.claude/uccif/` only through these `uccif` commands."),
    (r"\(Claude Code loads those anyway\)", "(the agent reads those anyway)"),
    (r"restart Claude Code", "restart Gemini CLI"),
    (r"restarts Claude Code", "restarts Gemini CLI"),
    (r"in Bash\b", "with run_shell_command"),
    (r"`\.claude/skills/<project>-map`", "`.agents/skills/<project>-map`"),
]
PER_SKILL = {
    "codegraph": [
        (r"`\$ARGUMENTS` = `reindex`", "The user asked to re-index"),
        (r"3\. \*\*MCP tool\.\*\*.*?(?=\n4\. )",
         "3. **MCP tool.** Nothing to run: the extension declares the server itself\n"
         "   (`gemini-extension.json`: `codegraph serve --mcp`). It starts once the CLI is on PATH, after\n"
         "   a restart of Gemini CLI. Do **not** run `codegraph install`: it would register a second\n"
         "   server with the same tools."),
        (r"the plugin's MCP server starts", "the extension's MCP server starts"),
        (r"the\n  plugin's MCP server starts", "the\n  extension's MCP server starts"),
    ],
    "init": [
        (r"\n7\. UCCIF v2 .*?(?=\n\n|\Z)", ""),  # Claude Code settings only
    ],
}


def render(name, text):
    for pat, rep in COMMON + PER_SKILL.get(name, []):
        text = re.sub(pat, rep, text, flags=re.M | re.S if "*?" in pat else re.M)
    head, sep, body = text.partition("\n---\n")
    return head + sep + HEADER + body


def build(check=False):
    stale = []
    for src in sorted(SRC.glob("*/SKILL.md")):
        name = src.parent.name
        out = render(name, src.read_text(encoding="utf-8"))
        dst = DST / name / "SKILL.md"
        try:
            old = dst.read_text(encoding="utf-8")
        except OSError:
            old = None
        if old != out:
            stale.append(name)
            if not check:
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_text(out, encoding="utf-8", newline="\n")
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
