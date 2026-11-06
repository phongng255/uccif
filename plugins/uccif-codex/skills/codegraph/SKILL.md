---
name: codegraph
description: "Configure or refresh CodeGraph for UCCIF in Codex. Use for $uccif:codegraph, indexing or reindexing a project. Ask before installing missing dependencies."
---

Use Python 3.8+ and the [bundled UCCIF entry point](../../core/scripts/uccif_main.py).
Resolve that link relative to this SKILL.md directory, not the project cwd.
In the commands below, `UCCIF` means the Python interpreter followed by that
resolved absolute script path, quoted separately for the current shell.
Run from the user's project directory. Do not run a literal executable named UCCIF.
This plugin does not install hooks or automatically track edits.

# CodeGraph for Codex

1. Run `UCCIF codegraph --host codex` and check `codegraph --version` if available.
2. If the CLI is missing, ask before installing `@colbymchenry/codegraph`. Never install the
   unrelated unscoped `codegraph` package. Never run `npx codegraph`.
3. If MCP is not configured, preview `UCCIF setup codex --with-codegraph --dry-run`,
   then apply the same setup without `--dry-run` within the user's authorized setup request.
   Preserve conflicts; do not register a second plugin/user/project server.
4. Run `codegraph init --yes` at the project root when indexing was requested and the CLI
   is available; then `UCCIF skills generate --host codex` and `codegraph status`.
5. A configured MCP entry is not proof the server or its tools loaded. Check the actual
   Codex tools; if not available, report this and use the verified CodeGraph CLI.
Do not change trust, install a language server, or promise a token footer.
