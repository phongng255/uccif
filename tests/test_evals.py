"""The eval cases under plugins/uccif/evals/ keep the layout `claude plugin eval` loads."""
import os
import re

import pytest

from conftest import PLUGIN

EVALS = PLUGIN / "evals"
CASES = sorted(p.parent for p in EVALS.glob("*/*/case.yaml"))
SETTINGS = {"tags", "max_turns", "timeout_seconds", "allowed_tools"}


def test_every_skill_group_has_cases():
    assert {c.parent.name for c in CASES} == {"codegraph", "init", "resume", "project-skills"}
    assert len({c.name for c in CASES}) == len(CASES)  # case names are unique across groups


@pytest.mark.parametrize("case", CASES, ids=lambda p: "%s/%s" % (p.parent.name, p.name))
def test_case_layout(case):
    assert re.fullmatch(r"[a-z][a-z0-9-]*", case.name)
    prompt = (case / "prompt.md").read_text(encoding="utf-8")
    m = re.match(r"---\n(.*?)\n---\n\n(.+)", prompt, re.S)
    assert m and m.group(2).strip()
    keys = {line.split(":")[0] for line in m.group(1).splitlines()}
    assert keys <= SETTINGS
    yaml = (case / "case.yaml").read_text(encoding="utf-8")
    assert 'schema_version: "1.1"' in yaml and "\nname: %s\n" % case.name in yaml
    assert "scaffold_script: place-files.sh" in yaml
    graders = sorted((case / "graders").glob("*.md"))
    assert graders
    for g in graders:
        assert re.match(r"\d\d-[a-z0-9-]+\.md$", g.name)
        assert g.read_text(encoding="utf-8").startswith("---\ntype: llm\nfocus: trace\nweight: 1\n---\n\n")
    script = case / "place-files.sh"
    assert os.access(str(script), os.X_OK) or os.name == "nt"
    assert 'source "$(dirname "$0")/../../fixtures/setup.sh"' in script.read_text(encoding="utf-8")


def test_fixture_has_no_real_dotenv():
    """The fake secret ships as dot-env: a real .env would be ignored by git and never reach CI."""
    fx = EVALS / "fixtures" / "trip-budget"
    assert (fx / "dot-env").is_file() and not (fx / ".env").exists()
