#!/usr/bin/env bash
# Scaffold for this case: An open task whose next step was already done in a later commit.
set -eu
source "$(dirname "$0")/../../fixtures/setup.sh"
base
index
uccif task start --type bug --goal "CSV export signs" "CSV export: Chuyển shows as spending" >/dev/null
uccif task checkpoint --file src/services/exportCsv.ts --next "in toCsv, give Chuyển rows no sign (neither + nor -)" >/dev/null
sleep 1
sed -i 's|const sign = e.kind === "Thu" ? "+" : "-";|const sign = e.kind === "Thu" ? "+" : e.kind === "Chi" ? "-" : "";|' src/services/exportCsv.ts
g commit -qam "csv: no sign for transfers"
