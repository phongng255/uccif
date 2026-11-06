#!/usr/bin/env bash
# Scaffold for this case: CodeGraph CLI installed and the project already indexed.
set -eu
source "$(dirname "$0")/../../fixtures/setup.sh"
base
index
