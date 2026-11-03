"""Static checks on the plugin's files (claude plugin validate runs in CI too)."""

import json
import re

import pytest

from conftest import PLUGIN, REPO
from uccif_lib import hooks, rules

EVENT_TO_HANDLER = {
    "SessionStart": "session-start", "UserPromptSubmit": "user-prompt-submit",
    "PreToolUse": "pre-tool-use", "PostToolUse": "post-tool-use",
    "PostToolUseFailure": "post-tool-use-failure", "SubagentStart": "subagent-start",
    "SubagentStop": "subagent-stop", "Stop": "stop", "PreCompact": "pre-compact",
    "PostCompact": "post-compact", "SessionEnd": "session-end",
    "InstructionsLoaded": "instructions-loaded",
}


def frontmatter(path):
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    assert m, "%s has no frontmatter" % path
    fields = dict(re.findall(r"^([A-Za-z-]+):\s*(.*)$", m.group(1), re.M))
    return fields, text


def test_manifests_parse_and_versions_match():
    from uccif_lib import __version__
    market = json.loads((REPO / ".claude-plugin" / "marketplace.json").read_text())
    plugin = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text())
    assert market["plugins"][0]["source"] == "./plugins/uccif"
    assert plugin["name"] == "uccif" and plugin["version"] == __version__


def test_hooks_json_uses_exec_form_and_known_handlers():
    cfg = json.loads((PLUGIN / "hooks" / "hooks.json").read_text())["hooks"]
    assert set(cfg) == set(EVENT_TO_HANDLER)
    for event, groups in cfg.items():
        for g in groups:
            for h in g["hooks"]:
                assert h["command"] == "${CLAUDE_PLUGIN_ROOT}/bin/uccif"
                assert h["args"] == ["hook", EVENT_TO_HANDLER[event]]
                assert h["args"][1] in hooks.HANDLERS
                assert 0 < h["timeout"] <= 10


SKILLS = sorted((PLUGIN / "skills").glob("*/SKILL.md"))
AGENTS = sorted((PLUGIN / "agents").glob("*.md"))


def test_expected_components_exist():
    assert {p.parent.name for p in SKILLS} == {
        "init", "task-context", "smart-code-search", "code-impact-analysis", "code-review", "resume"}
    assert {p.stem for p in AGENTS} == {"project-analyst", "code-impact-analyzer", "change-reviewer"}


@pytest.mark.parametrize("path", SKILLS, ids=lambda p: p.parent.name)
def test_skill_frontmatter_and_size(path):
    fields, text = frontmatter(path)
    assert fields["name"] == path.parent.name
    assert 50 < len(fields["description"]) <= 1536
    assert len(text.splitlines()) <= 80


@pytest.mark.parametrize("path", AGENTS, ids=lambda p: p.stem)
def test_agents_are_read_only(path):
    fields, text = frontmatter(path)
    assert fields["name"] == path.stem
    tools = {t.strip() for t in fields["tools"].split(",")}
    banned = {t.strip() for t in fields["disallowedTools"].split(",")}
    assert not tools & {"Write", "Edit", "MultiEdit", "NotebookEdit"}
    assert {"Write", "Edit", "MultiEdit", "NotebookEdit"} <= banned
    for unsupported in ("hooks", "mcpServers", "permissionMode"):  # ignored for plugin agents
        assert unsupported not in fields
    assert path.stem in hooks.AGENT_BASH
    assert len(text.splitlines()) <= 80


def test_core_rules_at_most_8():
    numbered = re.findall(r"^\d+\. ", rules.CORE_RULES, re.M)
    assert len(numbered) == 8
    assert "{reply_language}" not in rules.core_rules("vi")


def test_no_claude_md_at_plugin_root():
    assert not (PLUGIN / "CLAUDE.md").exists()  # never loaded as context
