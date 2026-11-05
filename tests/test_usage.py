from conftest import assistant, prompt, tool_result, write_transcript
from uccif_lib import usage


def test_dedupes_by_message_id_and_splits_turns(tmp_path):
    t = write_transcript(tmp_path / "t.jsonl", [
        prompt(), assistant("a", 10, 1000, 0, 50), assistant("a", 10, 1000, 0, 50),
        prompt(), assistant("b", 5, 2000, 100, 20), tool_result(), assistant("c", 1, 3000, 0, 30),
        assistant("s", 999999, 0, 0, 1, sidechain=True),
    ])
    s = usage.summarize(t)
    assert s["messages"] == 3 and s["turns"] == 2
    assert s["turn"]["in"] == (5 + 2000 + 100) + (1 + 3000)
    assert s["turn"]["output_tokens"] == 50
    assert s["session"]["in"] == 1010 + 2105 + 3001
    assert s["ctx"] == 3001
    assert s["window"] is None
    assert "(" not in usage.token_line(s).split("Context now:")[1]  # no % when window unknown


def test_window_inferred_after_200k(tmp_path):
    t = write_transcript(tmp_path / "t.jsonl", [
        prompt(), assistant("a", 0, 250000, 0, 1), assistant("b", 0, 128000, 0, 1)])
    s = usage.summarize(t)
    assert s["window"] == 1000000
    assert usage.token_line(s).endswith("Context now: 128.0k (13%)")


def test_configured_window(tmp_path):
    t = write_transcript(tmp_path / "t.jsonl", [prompt(), assistant("a", 0, 128000, 0, 1)])
    assert usage.token_line(usage.summarize(t, 200000)).endswith("Context now: 128.0k (64%)")


def test_unreadable_transcript_is_na(tmp_path):
    assert usage.token_line(usage.summarize(tmp_path / "missing.jsonl")) == "Token: n/a"
    bad = tmp_path / "bad.jsonl"
    bad.write_text("not json\n{\"type\":\"assistant\"}\n")
    assert usage.token_line(usage.summarize(bad)) == "Token: n/a"
    assert usage.token_line(usage.summarize(None)) == "Token: n/a"


def test_agent_tokens(tmp_path):
    t = write_transcript(tmp_path / "a.jsonl", [
        assistant("x", 1, 2, 3, 4, sidechain=True), assistant("x", 1, 2, 3, 4, sidechain=True)])
    assert usage.agent_tokens(t) == 10
    assert usage.agent_tokens(tmp_path / "none") is None


def test_fmt():
    assert usage.fmt(999) == "999"
    assert usage.fmt(12400) == "12.4k"
    assert usage.fmt(5690000) == "5.69M"


def test_fmt_billions():
    assert usage.fmt(2401440000) == "2.40B"
