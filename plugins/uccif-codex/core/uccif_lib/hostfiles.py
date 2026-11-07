"""Text each host reads, built from one source: plugins/uccif/skills/ and gemini/CONTEXT.md.

Used by the build scripts (the checked-in Gemini extension and Antigravity plugin) and at run time
by `uccif setup antigravity`, which has only the core plugin directory to read from. Generated
files are never edited by hand; tests and CI fail when a checked-in copy is out of date.
"""

import json
import re
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent
SKILLS = PLUGIN / "skills"
HEADER = "<!-- generated from plugins/uccif/skills by plugins/uccif/scripts/%s; edit the source -->\n"
BUILD_SCRIPT = {"gemini": "build_gemini.py", "antigravity": "build_antigravity.py"}

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
# Antigravity text is the Gemini text with these names changed: Gemini's and Antigravity's skills
# differ only in the host's name, its shell tool and the file that declares the MCP server.
ANTIGRAVITY = [
    ("Gemini CLI", "Antigravity"),
    ("run_shell_command", "run_command"),
    ("gemini-extension.json", "mcp_config.json"),
    ("the extension's", "the plugin's"),
    ("the\n  extension's", "the\n  plugin's"),
    ("the extension declares", "the plugin declares"),
    (".claude/uccif", ".agents/uccif"),
    ("uccif skills generate", "uccif skills generate --host antigravity"),
]


def render_skill(name, text, host):
    """A SKILL.md for `host` ("gemini" or "antigravity") from the Claude Code plugin's text."""
    for pat, rep in COMMON + PER_SKILL.get(name, []):
        text = re.sub(pat, rep, text, flags=re.M | re.S if "*?" in pat else re.M)
    if host == "antigravity":
        for old, new in ANTIGRAVITY:
            text = text.replace(old, new)
        text = re.sub(r"^name:\s*%s\b" % name, "name: uccif-%s" % name, text, count=1, flags=re.M)
        text = re.sub(r"/(codegraph|resume|init)\b", r"/uccif-\1", text)
        text = re.sub(r"`(codegraph|resume|init)` skill", r"`uccif-\1` skill", text)
        text = re.sub(r"\b(codegraph|resume|init) skill\b", r"uccif-\1 skill", text)
    head, sep, body = text.partition("\n---\n")
    return head + sep + HEADER % BUILD_SCRIPT[host] + body


def skill_sources():
    return sorted(SKILLS.glob("*/SKILL.md"))


def skills(host):
    """{skill name: SKILL.md text} for `host`."""
    out = {}
    for p in skill_sources():
        src_name = p.parent.name
        name = ("uccif-%s" % src_name) if host == "antigravity" else src_name
        out[name] = render_skill(src_name, p.read_text(encoding="utf-8"), host)
    return out


def context_text(host):
    """The always-on note that tells a user when UCCIF's hooks are not running."""
    text = (PLUGIN / "gemini" / "CONTEXT.md").read_text(encoding="utf-8")
    if host == "antigravity":
        text = re.sub(r"`/hooks` and\s+`gemini extensions list`", "`agy plugin list`", text)
    return text


def codegraph_server():
    """The CodeGraph MCP entry for hosts other than Claude Code: same command and env, without the
    fields only Claude Code reads."""
    cfg = json.loads((PLUGIN / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]["codegraph"]
    return {k: cfg[k] for k in ("command", "args", "env")}


def mcp_config_text():
    return json.dumps({"mcpServers": {"codegraph": codegraph_server()}}, indent=2) + "\n"


def write_tree(files, dst, check=False):
    """Bring `dst` in line with {relative path: text}. Returns the stale paths."""
    stale = []
    for rel, text in sorted(files.items()):
        path = Path(dst) / rel
        try:
            old = path.read_text(encoding="utf-8")
        except OSError:
            old = None
        if old != text:
            stale.append(rel)
            if not check:
                path.parent.mkdir(parents=True, exist_ok=True)
                with open(str(path), "w", encoding="utf-8", newline="\n") as f:
                    f.write(text)
    return stale
