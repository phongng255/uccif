"""Measure what UCCIF injects into Claude Code's context, in characters (exact) and an
approximate token count (chars / 4). Runs the real hook handlers in-process on a throwaway
repo; no API call. Usage: python tests/measure_context.py [--host claude]

Rows:
- SessionStart context: hookSpecificOutput.additionalContext at startup
- UserPromptSubmit context: what one prompt adds (stale notes only; normally 0)
- instructions as loaded: CLAUDE.md with every `@file` import line expanded, the way Claude Code
  loads it (the UCCIF block lives in AGENTS.md from 1.2 on, imported by CLAUDE.md)
"""

import io
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "plugins" / "uccif"))


def expand(path, seen=None):
    seen = seen or set()
    real = os.path.realpath(str(path))
    if real in seen or not os.path.exists(real):
        return ""
    seen.add(real)
    out = []
    for line in Path(real).read_text(encoding="utf-8").splitlines():
        m = re.match(r"^@(\S+)\s*$", line.strip())
        out.append(expand(Path(real).parent / m.group(1), seen) if m else line)
    return "\n".join(out)


def main():
    host = sys.argv[sys.argv.index("--host") + 1] if "--host" in sys.argv else "claude"
    work = Path(tempfile.mkdtemp(prefix="uccif-measure-"))
    repo = work / "demo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "math.js").write_text("export const add = (a, b) => a + b;\n")
    (repo / "package.json").write_text(json.dumps({"name": "demo", "scripts": {
        "test": "vitest", "build": "vite build", "lint": "eslint ."}}))
    g = ["git", "-c", "user.email=t@t", "-c", "user.name=t"]
    subprocess.run(g + ["init", "-q"], cwd=str(repo), check=True)
    subprocess.run(g + ["add", "-A"], cwd=str(repo), check=True)
    subprocess.run(g + ["commit", "-qm", "init"], cwd=str(repo), check=True)
    for var in list(os.environ):
        if var.startswith(("CLAUDE_", "UCCIF_", "GEMINI_")):
            del os.environ[var]
    os.environ.update(UCCIF_DATA_DIR=str(work / "data"), UCCIF_SYNC="1", HOME=str(work / "home"),
                      CLAUDE_PLUGIN_OPTION_AUTO_SETUP="false")
    (work / "home").mkdir()
    os.chdir(str(repo))
    from uccif_lib import cli, hooks

    def hook(event, data):
        out = io.StringIO()
        kw = {"host": host} if "host" in hooks.run.__code__.co_varnames else {}
        hooks.run(event, stdin=io.StringIO(json.dumps(data)), stdout=out, **kw)
        text = out.getvalue()
        return ((json.loads(text).get("hookSpecificOutput") or {}).get("additionalContext") or "") if text else ""

    base = {"session_id": "s1", "cwd": str(repo)}
    if host == "claude":
        ss = hook("session-start", dict(base, source="startup"))
    sys.stdin = io.StringIO("A demo lib.\nAdds numbers.")
    real_stdout, sys.stdout = sys.stdout, io.StringIO()
    cli.main(["claude-md", "write"])
    sys.stdout = real_stdout
    if host != "claude":  # the AGENTS.md block reaches Gemini through SessionStart
        ss = hook("session-start", dict(base, source="startup"))
    ups = hook("user-prompt-submit", dict(base, prompt="fix the add function"))
    if host == "claude":
        instr, label = expand(repo / "CLAUDE.md"), "instructions as loaded (CLAUDE.md + imports)"
    else:  # Gemini loads the extension's context file; it reads no AGENTS.md / CLAUDE.md by default
        ctx_file = json.loads((HERE.parent / "gemini-extension.json").read_text(encoding="utf-8"))["contextFileName"]
        instr, label = (HERE.parent / ctx_file).read_text(encoding="utf-8"), "extension context file"
    rows = [("SessionStart context", ss), ("UserPromptSubmit context", ups), (label, instr)]
    print("| what | chars | ~tokens (chars/4) |\n|---|---:|---:|")
    for name, text in rows:
        print("| %s | %d | %d |" % (name, len(text), round(len(text) / 4)))
    print("| total | %d | %d |" % (sum(len(t) for _, t in rows), round(sum(len(t) for _, t in rows) / 4)))


if __name__ == "__main__":
    main()
