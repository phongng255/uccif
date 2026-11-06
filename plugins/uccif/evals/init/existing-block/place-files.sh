#!/usr/bin/env bash
# Scaffold for this case: AGENTS.md already holds a UCCIF block.
set -eu
source "$(dirname "$0")/../../fixtures/setup.sh"
base
index
printf "Trip budget app.\n" | uccif agents-md write >/dev/null
g add -A
g commit -qm "uccif notes"
