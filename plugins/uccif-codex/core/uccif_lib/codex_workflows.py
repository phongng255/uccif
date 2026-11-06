"""Codex chat workflows. Repository setup supplies a machine-local core command.

These are source templates, not personal ChatGPT skill installations. Codex discovers the
rendered files in the target repository's .agents/skills directory.
"""

import json

WORKFLOWS = {
    "uccif": (
        "Use UCCIF in Codex chat: initialize project notes, resume saved work, or set up "
        "CodeGraph. Use when the user mentions $uccif, uccif init/resume/codegraph, or asks "
        "for the UCCIF menu. Not for unrelated coding requests.",
        """# UCCIF for Codex

Read the request after the skill mention as normal user text, not shell code.
- init / initialize project notes: follow the `uccif-codex-init` skill.
- resume / continue saved work: follow `uccif-codex-resume`.
- codegraph / index / reindex: follow `uccif-codex-codegraph`.
- status: run `UCCIF_COMMAND task show`, then `UCCIF_COMMAND doctor --host codex`.
If no action is supplied, show these four choices in the user's language and wait.
Do not invent a slash command or silently execute an unknown action.
"""),
    "uccif-codex-init": (
        "Initialize or refresh UCCIF project notes in Codex. Use for $uccif init, "
        "initializing UCCIF, or updating project purpose and conventions. Not source changes.",
        """# Initialize UCCIF notes

1. Run `UCCIF_COMMAND detect` from the project working directory.
2. Read README, the main manifest, AGENTS.md and existing `.claude/uccif/summary.md` if present.
   Read at most four relevant files; never read secrets or real .env files.
3. Record only verified purpose, unusual conventions and named external services, at most
   20 lines. Cite each claim with `[src: path]`; do not invent facts or duplicate the code map.
4. Send the text on stdin to `UCCIF_COMMAND summary write`. If notes exist, show the merged
   change before using `--replace`; preserve user edits. Do not write CLAUDE.md.
5. Run `UCCIF_COMMAND verify-tests` once; report unverified commands honestly.
6. If CodeGraph is already indexed, run `UCCIF_COMMAND skills generate --host codex`.
   Otherwise offer the CodeGraph workflow separately; notes do not require installing it.
Reply in the user's language with the files written and facts needing confirmation.
"""),
    "uccif-codex-resume": (
        "Resume work saved in UCCIF task memory in Codex. Use for $uccif resume or a "
        "request to continue a recorded UCCIF task; recheck stale progress before editing.",
        """# Resume a saved task

1. Run `UCCIF_COMMAND task show`. If no task exists, say so; do not invent prior work.
2. Check `git status --short`, relevant history since the checkpoint and the recorded files.
3. Recheck only facts that may be stale, then continue the recorded next step. If it is
   already done, update it with `UCCIF_COMMAND task checkpoint --next "..."` first.
4. Hooks are not enabled by this setup. After actual changes, checkpoint the modified files
   with repeated `--file` arguments, actual test results with `--test`, and the next step.
   Start a task with `task start "title" --type <supported-type>` only if needed; consult
   `UCCIF_COMMAND task start --help` instead of guessing the type.
5. Close only when work is done, recording decisions/issues or `--no-findings` explicitly.
Summarize verified progress in the user's language. Do not claim automatic tracking.
"""),
    "uccif-codex-codegraph": (
        "Configure or refresh CodeGraph for UCCIF in Codex. Use for $uccif codegraph, "
        "indexing or reindexing a project. Ask before installing missing dependencies.",
        """# CodeGraph for Codex

1. Run `UCCIF_COMMAND codegraph --host codex` and check `codegraph --version` if available.
2. If the CLI is missing, ask before installing `@colbymchenry/codegraph`. Never install the
   unrelated unscoped `codegraph` package. Never run `npx codegraph`.
3. If MCP is not configured, preview `UCCIF_COMMAND setup codex --with-codegraph --dry-run`,
   then apply the same setup without `--dry-run` within the user's authorized setup request.
   Preserve conflicts; do not register a second plugin/user/project server.
4. Run `codegraph init --yes` at the project root when indexing was requested and the CLI
   is available; then `UCCIF_COMMAND skills generate --host codex` and `codegraph status`.
5. A configured MCP entry is not proof the server or its tools loaded. Check the actual
   Codex tools; if not available, report this and use the verified CodeGraph CLI.
Do not change trust, install a language server, or promise a token footer.
"""),
}


def skills(command):
    """Render dedicated names so Gemini/Antigravity's init/resume skills survive setup."""
    return {name: "---\nname: %s\ndescription: %s\n---\n\n" % (name, json.dumps(desc))
            + "Run UCCIF from the project directory using `%s`. This path is machine-local.\n"
            % command + body.replace("UCCIF_COMMAND", command)
            for name, (desc, body) in WORKFLOWS.items()}


def packaged_skills():
    """Portable package: resolve the entry point from the skill's actual installed path.

    PLUGIN_ROOT expansion is guaranteed for hooks, not Markdown skills. Use a normal
    relative resource link instead of pretending an environment placeholder expands.
    """
    note = ("Use Python 3.8+ and the [bundled UCCIF entry point](../../core/scripts/uccif_main.py).\n"
            "Resolve that link relative to this SKILL.md directory, not the project cwd.\n"
            "In the commands below, `UCCIF` means the Python interpreter followed by that\n"
            "resolved absolute script path, quoted separately for the current shell.\n"
            "Run from the user's project directory. Do not run a literal executable named UCCIF.\n"
            "This plugin does not install hooks or automatically track edits.\n\n")
    result = {}
    for name, (desc, body) in WORKFLOWS.items():
        native = name.replace("uccif-codex-", "")
        for action in ("init", "resume", "codegraph"):
            desc = desc.replace("$uccif " + action, "$uccif:" + action)
            body = body.replace("`uccif-codex-%s`" % action, "`uccif:%s`" % action)
        if name == "uccif":
            desc = desc.replace("$uccif,", "$uccif:uccif,")
        result[native] = "---\nname: %s\ndescription: %s\n---\n\n" % (native, json.dumps(desc)) \
            + note + body.replace("UCCIF_COMMAND", "UCCIF")
    return result
