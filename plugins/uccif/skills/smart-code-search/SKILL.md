---
name: smart-code-search
description: Use to find where a function, class, component, style or config is defined or used, its call sites or related tests, or before concluding that something is missing — searches with the cheapest precise source and verifies against the code.
---

# Smart code search

## Order (cheapest precise source first)

1. **CodeGraph** — the `codegraph_explore` MCP tool (in Bash / subagents:
   `codegraph explore "<question>"`). One call answers "where is X", "how does X work", "what
   calls X", "how does A reach B": the relevant symbols' source with line numbers, call paths
   and blast radius. Treat the returned source as already read. Narrower CLI:
   `codegraph node <symbol|file>`, `codegraph callers|callees <symbol>`, `codegraph query <name>`.
   No `.codegraph/` index or no CLI → run the `uccif:codegraph` skill first.
2. **LSP** (go to definition / find references) when a language server is active for the
   file — exact for overloads and same-name symbols.
3. **Docs map**: `.claude/uccif/architecture.md` — which module owns a concept the graph has
   no name for.
4. **Grep / Glob tools**, bounded: a path or glob parameter, a type filter, and a result limit.
   Put exclusions in the tool parameters, never inside the regex. If those tools do not
   exist in this session, use `rg -n --glob '!node_modules' --glob '!dist' '<pattern>' <dir> | head -40`
   (quote globs; zsh fails on unquoted ones).
5. **Read** only the needed range (offset/limit), never a whole large file for one function.

## Rules

- One search per call. A failed command (error, bad option, missing path) is not
  "no matches": fix it and rerun, or report it.
- Before saying "X is missing / not implemented": search by name **and** by behaviour (shared
  CSS, config, util, generated code), not only the open file.
- Do not re-read a file already read in this session unless it changed.
- Wide conceptual search across many dirs ("where is scroll locking handled") → the built-in
  Explore agent; take only its summary.
- Never read `node_modules`, build output, lockfiles or minified files to answer a question;
  run the project's test/build command instead.

## Output

`file:line` + the minimal excerpt that proves the answer. Say what was not checked.
