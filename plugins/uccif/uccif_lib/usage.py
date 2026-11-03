"""Real token usage read from the session transcript (JSONL).

Facts the parser relies on (checked against Claude Code 2.1.309):
- assistant entries carry message.usage with input_tokens,
  cache_read_input_tokens, cache_creation_input_tokens, output_tokens;
- one API message is written as several lines sharing message.id, so usage is
  de-duplicated by id (last line wins);
- a user entry whose content holds a tool_result is not a new prompt;
- isSidechain entries belong to subagents and are excluded.
Anything unreadable yields None, and the token line prints "Token: n/a".
"""

import json

USAGE_KEYS = ("input_tokens", "cache_read_input_tokens",
              "cache_creation_input_tokens", "output_tokens")


def _is_prompt(entry):
    if entry.get("type") != "user" or entry.get("isMeta") or entry.get("isSidechain"):
        return False
    content = (entry.get("message") or {}).get("content")
    if isinstance(content, list):
        return not any(isinstance(c, dict) and c.get("type") == "tool_result" for c in content)
    return isinstance(content, str)


def read_messages(transcript_path):
    """Return ordered list of (turn_index, model, usage) per unique assistant message."""
    order, by_id = [], {}
    turn = 0
    try:
        f = open(str(transcript_path), encoding="utf-8")
    except (OSError, TypeError):
        return None
    with f:
        for line in f:
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if _is_prompt(entry):
                turn += 1
                continue
            if entry.get("type") != "assistant" or entry.get("isSidechain"):
                continue
            msg = entry.get("message") or {}
            usage = msg.get("usage")
            if not isinstance(usage, dict):
                continue
            mid = msg.get("id") or entry.get("uuid")
            if mid not in by_id:
                order.append(mid)
            by_id[mid] = (turn, msg.get("model"), {k: int(usage.get(k) or 0) for k in USAGE_KEYS})
    return [by_id[m] for m in order]


def _sum(msgs):
    tot = dict.fromkeys(USAGE_KEYS, 0)
    for _, _, u in msgs:
        for k in USAGE_KEYS:
            tot[k] += u[k]
    tot["in"] = tot["input_tokens"] + tot["cache_read_input_tokens"] + tot["cache_creation_input_tokens"]
    return tot


def summarize(transcript_path, context_window="auto"):
    msgs = read_messages(transcript_path)
    if not msgs:
        return None
    last_turn = msgs[-1][0]
    turn = _sum([m for m in msgs if m[0] == last_turn])
    session = _sum(msgs)
    last = msgs[-1][2]
    ctx = last["input_tokens"] + last["cache_read_input_tokens"] + last["cache_creation_input_tokens"]

    # Context window: only show % when known. Configured value wins; otherwise,
    # if the current model's run has exceeded 200k, the window must be 1M.
    model = msgs[-1][1]
    window = None
    if isinstance(context_window, int) and context_window > 0:
        window = context_window
    else:
        same_model = [m for m in msgs if m[1] == model]
        peak = max(u["input_tokens"] + u["cache_read_input_tokens"] + u["cache_creation_input_tokens"]
                   for _, _, u in same_model)
        if peak > 200000:
            window = 1000000
    return {
        "turn": turn, "session": session, "ctx": ctx, "window": window,
        "model": model, "messages": len(msgs), "turns": last_turn,
    }


def fmt(n):
    if n >= 1000000:
        return "%.2fM" % (n / 1e6)
    if n >= 1000:
        return "%.1fk" % (n / 1e3)
    return str(n)


def token_line(summary):
    if not summary:
        return "Token: n/a"
    t, s = summary["turn"], summary["session"]
    ctx = "Ctx %s" % fmt(summary["ctx"])
    if summary["window"]:
        ctx += " (%d%%)" % round(100.0 * summary["ctx"] / summary["window"])
    return "Turn: in %s (cache %s) · out %s · Session %s · %s" % (
        fmt(t["in"]), fmt(t["cache_read_input_tokens"]), fmt(t["output_tokens"]),
        fmt(s["in"] + s["output_tokens"]), ctx,
    )


def agent_tokens(agent_transcript_path):
    """Total tokens of a subagent transcript (its entries are all sidechain)."""
    try:
        f = open(str(agent_transcript_path), encoding="utf-8")
    except (OSError, TypeError):
        return None
    by_id = {}
    with f:
        for line in f:
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            msg = entry.get("message") or {}
            if entry.get("type") == "assistant" and isinstance(msg.get("usage"), dict):
                by_id[msg.get("id") or entry.get("uuid")] = msg["usage"]
    if not by_id:
        return None
    return sum(int(u.get(k) or 0) for u in by_id.values() for k in USAGE_KEYS)
