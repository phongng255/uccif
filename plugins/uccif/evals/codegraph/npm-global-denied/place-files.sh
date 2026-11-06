#!/usr/bin/env bash
# Scaffold for this case: The CodeGraph CLI is not on PATH and `npm install -g` fails with EACCES.
set -eu
source "$(dirname "$0")/../../fixtures/setup.sh"
base
