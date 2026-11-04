"""CORE RULES: the single source, injected by SessionStart (startup/clear/compact).

The project's CLAUDE.md UCCIF block holds only project-specific facts
(summary, commands, doc paths) and never repeats these rules.
"""

CORE_RULES = """\
UCCIF CORE RULES
1. Do the work yourself: run commands, read logs, start processes. Ask the user only for GUI/device/login/secret steps, and before installing packages, deploy, git push, external-service calls, deleting data.
2. Find code with CodeGraph, not Grep/Read. Flow, "where is X / how does X work" -> MCP `codegraph_explore`. One symbol -> `codegraph_node`, `codegraph_callers`, `codegraph_impact` (same as Bash `codegraph node|callers|impact <sym> [--depth 2]`). Tests to run after a change -> `git diff --name-only | codegraph affected --stdin --quiet`. Grep/Glob only for literals and config, scoped to a module dir. Skills `<project>-map`, `-mod-*`, `-bugfix` say where things live.
3. Evidence: never claim how code behaves or that something is fixed without checking it in this task (file:line, command output); report the user's stated constraints as met/not met. Stuck after 2 failed fixes -> gather logs/repro first.
4. Tasks are automatic (the first edit opens one, the end of the turn closes it). Only to keep a decision or open issue: `uccif task checkpoint --decision|--issue "<text>"`. The user never runs `uccif`; map plain requests yourself (`uccif task show`, `uccif log hooks --today`).
5. Reply in {reply_language}; code, comments, commits and framework files in English. Never state token counts."""


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
