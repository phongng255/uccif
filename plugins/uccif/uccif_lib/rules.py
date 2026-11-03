"""CORE RULES: the single source, injected by SessionStart (startup/clear/compact).

The project's CLAUDE.md UCCIF block holds only project-specific facts
(summary, commands, doc paths) and never repeats these rules.
"""

CORE_RULES = """\
UCCIF CORE RULES
1. Do the work yourself. Run commands, read output and logs, start/stop processes (long-running ones in the background), write data files. Hand the user only what needs their hands or eyes: GUI actions in other apps, device testing, logins, typing secrets. Never ask the user to run a command you can run.
2. Two kinds of work. Ops (run, inspect, configure, read logs; no source edits) -> just do it. Code changes -> matching uccif skill -> `uccif task start "<title>" --type <type>` -> find code (`uccif index query`, LSP when active, then bounded Grep/Glob, then read only the needed range) -> Edit -> related tests -> `uccif task checkpoint` / `uccif task close`. The flow saves tokens and survives /clear and compaction; it is never a gate.
3. Evidence: never claim how code behaves, or that something is fixed/deployed/missing, without something you checked in this task (file:line, command output, git status).
4. Ask first only for: installing packages, deploy, git push, calls to external services, deleting user data. One "yes" = one action.
5. Stuck after 2 failed fixes -> gather evidence (logs, repro) before trying again.
6. Reply to the user in {reply_language}, always, including after hook messages. Code, comments, commits and framework files stay English.
7. The user never runs `uccif` or names skills/agents; map plain requests to commands yourself (e.g. "what was I doing" -> `uccif task show`, "did hooks run today" -> `uccif log hooks --today`). Never state token counts; the hook reports them.
8. `#quick` in the user's prompt skips task start/close for a tiny edit. Evidence and ask-first still apply."""


def core_rules(reply_language):
    return CORE_RULES.replace("{reply_language}", reply_language)


# ---- user rules: the user's own extension point -------------------------------------
# Two optional Markdown files, read by SessionStart (startup / clear / compact, the same moments as
# the CORE RULES) and appended after them. The plugin never writes them (uccif:init may create an
# empty project file with commented examples, only when it does not exist).

USER_RULES_NAME = "rules.md"
USER_RULES_MAX_LINES = 15
USER_RULES_MAX_CHARS = 300  # per line: a pasted blob must not flood the context


def user_rule_files(project):
    """[(scope, path)]: every project first (~/.claude/uccif/rules.md), then this project
    (<repo>/.claude/uccif/rules.md), so the more specific file comes last."""
    from pathlib import Path
    out = []
    try:
        out.append(("all projects", Path.home() / ".claude" / "uccif" / USER_RULES_NAME))
    except (RuntimeError, KeyError, OSError):  # no home directory
        pass
    out.append(("this project", project.docs_dir / USER_RULES_NAME))
    return out


def _rule_lines(text):
    """Non-empty lines outside <!-- --> comments."""
    import re
    text = re.sub(r"<!--.*?(-->|\Z)", "", text, flags=re.S)
    return [ln.rstrip() for ln in text.splitlines() if ln.strip()]


def load_user_rules(project):
    """[(scope, path, lines, hidden)] for the rule files that exist and have content. A file that
    cannot be read is skipped: hooks never fail over it."""
    out = []
    for scope, path in user_rule_files(project):
        try:
            if not path.is_file():
                continue
            lines = _rule_lines(path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, ValueError):
            continue
        if not lines:
            continue
        shown = [ln if len(ln) <= USER_RULES_MAX_CHARS else ln[:USER_RULES_MAX_CHARS] + " …"
                 for ln in lines[:USER_RULES_MAX_LINES]]
        out.append((scope, path, shown, len(lines) - len(shown)))
    return out


def user_rules(project):
    """Text appended after the CORE RULES, or "" when the user has no rule files."""
    parts = []
    for scope, path, lines, hidden in load_user_rules(project):
        block = ["USER RULES (%s: %s)" % (scope, path.as_posix())] + lines
        if hidden:
            block.append("(+%d more lines, see %s)" % (hidden, path.as_posix()))
        parts.append("\n".join(block))
    return "\n\n".join(parts)
