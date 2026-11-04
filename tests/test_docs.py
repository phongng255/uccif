"""Every `uccif ...` command the docs show must exist: docs once listed commands that did not run."""

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = [ROOT / "README.md", ROOT / "docs" / "GUIDE.md", ROOT / "docs" / "HUONG-DAN.md"]
MAIN = ROOT / "plugins" / "uccif" / "scripts" / "uccif_main.py"
INLINE = re.compile(r"`[^`\n]*`")
COMMAND = re.compile(r"\buccif ([a-z][a-z-]*)(?: ([a-z][a-z-]*))?((?: --[a-z-]+)*)")


def documented():
    found = set()
    for doc in DOCS:
        text = doc.read_text(encoding="utf-8")
        code = INLINE.findall(text) + re.findall(r"```.*?```", text, flags=re.S)
        for snippet in code:
            for sub, arg, flags in COMMAND.findall(snippet):
                found.add((sub, arg, flags.strip()))
    return sorted(found)


def run_help(*args):
    return subprocess.run([sys.executable, str(MAIN)] + list(args) + ["--help"], stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, universal_newlines=True, encoding="utf-8")


def test_documented_commands_exist():
    commands = documented()
    assert len(commands) >= 5  # the pattern still finds them
    for sub, arg, flags in commands:
        res = run_help(*[w for w in (sub, arg) if w])
        assert res.returncode == 0, "uccif %s %s: %s" % (sub, arg, res.stdout)
        for flag in flags.split():
            assert flag in res.stdout, "uccif %s %s has no %s" % (sub, arg, flag)


def test_launcher_is_never_shown_run_by_python():
    for doc in DOCS:
        for line in doc.read_text(encoding="utf-8").splitlines():
            if "`SyntaxError`" not in line:
                assert not re.search(r"python3? \S*bin/uccif", line), "%s: %s" % (doc.name, line)


def test_relative_links_resolve():
    for doc in DOCS:
        for target in re.findall(r"\]\((?!https?:)([^)#\s]+)", doc.read_text(encoding="utf-8")):
            assert (doc.parent / target).exists(), "%s links to missing %s" % (doc.name, target)
