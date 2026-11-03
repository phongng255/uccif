---
name: code-impact-analysis
description: Use before a refactor, rename, or any change to a shared interface, API, props, store, type or util — lists every dependent, the risk of each, and the tests to run.
---

# Code impact analysis

## Steps

1. Name the change precisely: file, symbol, kind (rename / signature / behaviour / removal).
2. Find dependents: start with `codegraph impact <symbol> --depth 3` (or the
   `codegraph_explore` tool: "what breaks if I change <symbol>"), `codegraph callers <symbol>`
   for direct call sites, and `codegraph affected <file>` for the tests to run. Then LSP
   references when active, and string references (events, config keys, routes) with a bounded
   Grep — a code graph cannot see those.
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
