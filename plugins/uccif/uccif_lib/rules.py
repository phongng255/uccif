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
