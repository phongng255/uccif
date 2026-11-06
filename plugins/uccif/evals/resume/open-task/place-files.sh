#!/usr/bin/env bash
# Scaffold for this case: An open UCCIF task with a next step.
set -eu
source "$(dirname "$0")/../../fixtures/setup.sh"
base
index
uccif task start --type bug --goal "Transfers (Chuyển) must not count as spending" "Chuyển bị tính là Chi" >/dev/null
uccif task checkpoint --file src/domain/ledger.ts --decision "computeLedger: only Chi is expense" --next "add a test in tests/ledger.test.ts: a Chuyển entry changes neither income nor expense" >/dev/null
