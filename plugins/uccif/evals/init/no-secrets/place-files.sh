#!/usr/bin/env bash
# Scaffold for this case: The project has a .env holding a live API key and a .env.example without values.
set -eu
source "$(dirname "$0")/../../fixtures/setup.sh"
base
index
