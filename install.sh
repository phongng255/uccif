#!/bin/sh
# UCCIF One-line Installer & Updater (for Antigravity and Claude Code)
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/phongng255/uccif/feature/gemini-antigravity-support/install.sh | sh
# Or locally:
#   ./install.sh [install|update|uninstall|status]

set -e

REPO_URL="https://github.com/phongng255/uccif.git"
BRANCH="feature/gemini-antigravity-support"
INSTALL_DIR="${HOME}/.uccif-app"

ACTION="${1:-install}"

echo "==> UCCIF Plugin & CLI Manager"

# Check Python 3.8+
has_python=0
for cand in python3 python "py -3"; do
  if $cand -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' >/dev/null 2>&1; then
    PYTHON_CMD="$cand"
    has_python=1
    break
  fi
done

if [ "$has_python" -ne 1 ]; then
  echo "Error: Python 3.8+ is required but was not found on PATH." >&2
  exit 1
fi

# Detect if running from inside the cloned repo
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if [ -f "$HERE/plugins/uccif/bin/uccif" ]; then
  APP_DIR="$HERE"
else
  APP_DIR="$INSTALL_DIR"
  if [ ! -d "$APP_DIR/.git" ]; then
    echo "==> Cloning UCCIF repository into $APP_DIR..."
    git clone --depth 1 --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
  fi
fi

# Run requested action
case "$ACTION" in
  install)
    echo "==> Installing UCCIF..."
    sh "$APP_DIR/plugins/uccif/bin/uccif" install
    ;;
  update)
    echo "==> Updating UCCIF..."
    sh "$APP_DIR/plugins/uccif/bin/uccif" update
    ;;
  uninstall)
    echo "==> Uninstalling UCCIF..."
    sh "$APP_DIR/plugins/uccif/bin/uccif" uninstall
    ;;
  status)
    sh "$APP_DIR/plugins/uccif/bin/uccif" status
    ;;
  *)
    echo "Usage: ./install.sh [install|update|uninstall|status]"
    exit 1
    ;;
esac

# Create global symlink in ~/.local/bin or ~/.gemini/bin if writable
BIN_DIR="${HOME}/.local/bin"
if [ ! -d "$BIN_DIR" ]; then
  BIN_DIR="${HOME}/.gemini/bin"
fi

if [ -d "$BIN_DIR" ] && [ -w "$BIN_DIR" ]; then
  ln -sf "$APP_DIR/plugins/uccif/bin/uccif" "$BIN_DIR/uccif"
  echo "✔ Global command 'uccif' linked to $BIN_DIR/uccif"
fi

echo "✔ Done!"
