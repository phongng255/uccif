#!/usr/bin/env bash
# Shared scaffold for the UCCIF eval cases: builds the trip-budget project in the current
# directory. Sourced by each case's place-files.sh, which then adds its own state.
# Needs git, python3 and, for `index`, the CodeGraph CLI (`npm install -g @colbymchenry/codegraph`).
set -eu
EVALS="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLUGIN="${UCCIF_EVAL_PLUGIN:-$(cd "$EVALS/.." && pwd)}"   # the plugin under test
uccif() { "$PLUGIN/bin/uccif" "$@"; }
g() { git -c user.email=eval@uccif -c user.name=eval "$@"; }

base() {
  cp -R "$EVALS/fixtures/trip-budget/." .
  mv dot-env .env
  g init -q
  g add -A
  g commit -qm "trip budget: ledger, stores, services"
}

index() {
  codegraph init --yes >/dev/null 2>&1
  uccif skills generate >/dev/null
}
