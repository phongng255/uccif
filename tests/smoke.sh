#!/bin/sh
# End-to-end smoke test: runs Claude Code headless with the plugin loaded on a
# throwaway repo, then checks what the hooks logged. Uses the API (small cost,
# capped by --max-budget-usd). Usage: tests/smoke.sh [path-to-claude]
set -eu
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
root=$(dirname -- "$here")
claude=${1:-${CLAUDE_BIN:-claude}}
out="$root/tests/.smoke"
rm -rf "$out"
mkdir -p "$out"

work=$(mktemp -d "${TMPDIR:-/tmp}/uccif-smoke.XXXXXX")
repo="$work/demo"
mkdir -p "$repo/src"
printf 'export function add(a, b) {\n  return a + b;\n}\n' > "$repo/src/math.js"
printf '{"name":"demo","scripts":{"test":"node -e 1"}}\n' > "$repo/package.json"
git -C "$repo" init -q
git -C "$repo" add -A
git -C "$repo" -c user.email=t@t -c user.name=t commit -qm init

prompt='This is an automated plugin smoke test. Do exactly these steps, nothing else:
1. Run the Bash command: uccif task start "Smoke test" --type explore
2. Run the Bash command: uccif where
3. Use the Agent tool with subagent_type "uccif:change-reviewer" and prompt "Run git status and report it. Constraint: none." and wait for it.
4. Reply with one line: SOURCE=<the value after "source:" in step 2>, then the word DONE.'

started=$(date +%s)
( cd "$repo" && "$claude" -p "$prompt" \
    --plugin-dir "$root/plugins/uccif" \
    --setting-sources project \
    --model sonnet \
    --max-turns 15 \
    --max-budget-usd 1 \
    --allowedTools "Bash(uccif *)" "Bash(echo *)" "Bash(git status*)" "Bash(git diff*)" "Agent" "Read" \
    --output-format stream-json --verbose --include-hook-events \
    > "$out/stream.jsonl" 2> "$out/stderr.txt" ) || echo "claude exited $?"
echo "claude ran $(( $(date +%s) - started ))s; output in $out"

cd "$repo"
env -u UCCIF_DATA_DIR -u CLAUDE_PLUGIN_DATA "$root/plugins/uccif/bin/uccif" where > "$out/where.txt" || true
python3 -I "$here/smoke_check.py" "$out" "$repo"
