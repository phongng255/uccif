"""Check a smoke run: python3 smoke_check.py <out-dir> <repo>. Prints PASS/FAIL/INFO lines."""

import json
import sys
from pathlib import Path

out, repo = Path(sys.argv[1]), sys.argv[2]
where = dict(l.split(":", 1) for l in (out / "where.txt").read_text().splitlines() if ":" in l)
data = Path(where.get("data", "").strip())
hooks = [json.loads(l) for l in (data / "metrics" / "hooks.jsonl").read_text().splitlines()] \
    if (data / "metrics" / "hooks.jsonl").exists() else []
stream = []
for line in (out / "stream.jsonl").read_text().splitlines():
    try:
        stream.append(json.loads(line))
    except ValueError:
        pass
raw = (out / "stream.jsonl").read_text()
result = next((e for e in reversed(stream) if e.get("type") == "result"), {})
failed = 0


def check(name, ok, detail=""):
    global failed
    failed += not ok
    print("%s  %s%s" % ("PASS" if ok else "FAIL", name, (" — " + detail) if detail else ""))


def info(name, detail):
    print("INFO  %s — %s" % (name, detail))


events = {h.get("event") for h in hooks}
info("data dir", str(data))
info("result", "%s, cost $%s, turns %s" % (result.get("subtype"), result.get("total_cost_usd"), result.get("num_turns")))
check("hooks.jsonl written", bool(hooks), "%d lines" % len(hooks))
for ev in ("session-start", "user-prompt-submit", "pre-tool-use", "stop", "subagent-start", "subagent-stop"):
    check("hook %s ran" % ev, ev in events)
check("no hook errors", not [h for h in hooks if h.get("decision") == "error"],
      "; ".join(h.get("error", "") for h in hooks if h.get("decision") == "error"))
check("uccif on PATH (task started)",  # task state lives in the project, not the data dir
      (Path(repo) / ".claude" / "uccif" / ".local" / "tasks" / "current.json").exists())
check("CLAUDE_ENV_FILE reaches Bash (UCCIF_DATA_DIR set)",
      "SOURCE=UCCIF_DATA_DIR" in (result.get("result") or ""), (result.get("result") or "")[:160])
sub_pre = [h for h in hooks if h.get("event") == "pre-tool-use" and h.get("agent_id")]
check("PreToolUse fires inside subagent (agent_id present)", bool(sub_pre),
      ", ".join("%s %s" % (h.get("decision"), h.get("target")) for h in sub_pre))
check("SessionStart context reached Claude", "UCCIF CORE RULES" in raw)
stop = [h for h in hooks if h.get("event") == "stop"]
check("Stop produced token line", any(h.get("rule") == "token-line" for h in stop))
info("token line visible in stream-json", "yes" if "Turn: in" in raw else "no (systemMessage not in SDK stream)")
info("session-end ran in -p", "yes" if "session-end" in events else "no")
slow = [h for h in hooks if h.get("slow")]
ms = sorted(h.get("ms", 0) for h in hooks)
info("hook timing", "median %sms, max %sms, slow %d" % (ms[len(ms) // 2] if ms else "?", ms[-1] if ms else "?", len(slow)))
print("FAILED %d" % failed if failed else "ALL PASS")
sys.exit(1 if failed else 0)
