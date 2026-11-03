---
name: code-impact-analysis
description: Use before a refactor, rename, or any change to a shared interface, API, props, store, type or util — lists every dependent, the risk of each, and the tests to run.
---

# Code impact analysis

## Steps

1. Name the change precisely: file, symbol, kind (rename / signature / behaviour / removal).
2. Find dependents: start with `uccif index query --impact <file>` (importers and callers,
   up to 3 levels, each with `file:line`, plus the tests to run; `--depth 5` for core
   modules). Add `--symbol <name>` (callers of that symbol, files that mention it) and
   `--path <A> <B>` to explain how two distant files connect. Then LSP references when active,
   and string references (routes, events, config keys) with a bounded Grep. Import/call
   edges are exact only for files parsed with tree-sitter; unresolved calls are listed as
   "possibly".
3. Small and clear (≤ 4 dependents, one module) → do it yourself.
   Otherwise delegate to the `uccif:code-impact-analyzer` agent with the file, symbol and kind,
   then **re-read every H/M row's `file:line` yourself** before editing — agent output is a
   lead, not a fact.
4. While the agent runs you may read code or prepare a reproduction; do not edit dependents
   or adjust tests to an unanalysed change.
5. Record the conclusion: `uccif task checkpoint --decision "impact: <1 line>"`.

## Output (≤ 40 lines)

| file:line | how it uses the symbol | risk H/M/L | test to run |
|---|---|---|---|

End with `Not checked: …` (dynamic access, other repos, generated code).
