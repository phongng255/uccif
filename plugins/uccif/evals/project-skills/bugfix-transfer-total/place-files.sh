#!/usr/bin/env bash
# Scaffold for this case: Indexed project with generated project skills; no node_modules (tests cannot run offline).
set -eu
source "$(dirname "$0")/../../fixtures/setup.sh"
base
index
