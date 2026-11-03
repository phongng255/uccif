"""The user's own rules: ~/.claude/uccif/rules.md and <repo>/.claude/uccif/rules.md, appended after
the CORE RULES by SessionStart."""
from pathlib import Path

from conftest import run_hook
from uccif_lib import detect, rules


def ctx(out):
    return out["hookSpecificOutput"]["additionalContext"]


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _global():
    return Path.home() / ".claude" / "uccif" / "rules.md"


def _start(project, source="startup"):
    return run_hook("session-start", {"session_id": "S1", "cwd": str(project.root), "source": source})


def test_no_files_output_unchanged(project):
    _, out = _start(project)
    assert "USER RULES" not in ctx(out)
    assert rules.user_rules(project) == "" and rules.load_user_rules(project) == []


def test_both_files_loaded_after_core_rules(project):
    _write(_global(), "Always answer briefly.\n")
    _write(project.docs_dir / "rules.md", "<!-- example: ignored -->\n\nRun `make check` before a commit.\n")
    for source in ("startup", "clear", "compact"):
        text = ctx(_start(project, source)[1])
        core = text.index("UCCIF CORE RULES")
        g = text.index("USER RULES (all projects: ")
        p = text.index("USER RULES (this project: ")
        assert core < g < p  # core, then every-project rules, then this project's
        assert "Always answer briefly." in text and "Run `make check` before a commit." in text
        assert "example: ignored" not in text
    assert "USER RULES" not in ctx(_start(project, "resume")[1])  # same moments as the core rules


def test_long_file_is_cut(project):
    f = _write(project.docs_dir / "rules.md", "".join("rule %d\n\n" % i for i in range(40)) + "x" * 1000 + "\n")
    text = rules.user_rules(project)
    assert "rule 0" in text and "rule 14" in text and "rule 15" not in text
    assert "(+26 more lines, see %s)" % f.as_posix() in text
    assert len(text.splitlines()) == 1 + 15 + 1


def test_long_line_is_cut(project):
    _write(project.docs_dir / "rules.md", "y" * 5000 + "\n")
    text = rules.user_rules(project)
    assert len(text) < 500 and text.endswith(" …")


def test_broken_file_never_fails_the_hook(project):
    (project.docs_dir / "rules.md").mkdir(parents=True)  # a directory where the file should be
    _write(_global(), "")  # empty: nothing to add
    code, out = _start(project)
    assert code == 0 and "UCCIF CORE RULES" in ctx(out) and "USER RULES" not in ctx(out)
    bad = _write(project.docs_dir.parent / "x" / "rules.md", "ok")
    bad.write_bytes(b"\xff\xfe\x00 not utf-8 \x80 still read\n")
    assert rules._rule_lines(bad.read_text(encoding="utf-8", errors="replace"))


def test_doctor_lists_rule_files(project):
    _write(project.docs_dir / "rules.md", "a\nb\n")
    _, lines = detect.doctor(project)
    text = "\n".join(lines)
    assert "user rules loaded (this project): %s, 2 lines" % (project.docs_dir / "rules.md").as_posix() in text
    assert "no user rules for all projects" in text
