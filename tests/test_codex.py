"""Codex repository setup: real CLI execution, ownership, coexistence and honest diagnostics.

No live Codex model session is simulated by these tests. Client discovery/hooks need a
separate real-session gate before they can be advertised as working.
"""

import io
import json
import os
from pathlib import Path
import subprocess
import sys
import shutil
from concurrent.futures import ThreadPoolExecutor

import pytest

from conftest import PLUGIN
from uccif_lib import codegraph, codex_setup as setup, codex_workflows, hooks, hosts, task


@pytest.fixture(autouse=True)
def isolated_codex(tmp_path, monkeypatch):
    home = tmp_path / "codex-home"
    home.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(home))
    return home


def snapshot(root):
    return {p.relative_to(root).as_posix(): p.read_bytes()
            for p in root.rglob("*") if p.is_file() and ".git" not in p.relative_to(root).parts}


def cli(repo, *args):
    env = os.environ.copy()
    # macOS may redirect Python bytecode into ~/Library/Caches. Keep the
    # subprocess itself from changing the isolated HOME while we assert that a
    # Codex dry-run creates no project or user metadata.
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run([sys.executable, str(PLUGIN / "scripts" / "uccif_main.py")] + list(args),
                          cwd=str(repo), capture_output=True, text=True, env=env)


def test_dry_run_has_no_writes(project, isolated_codex):
    before = snapshot(project.root)
    lines = setup.run(project, dry_run=True, with_codegraph=True)
    assert any("Would write AGENTS.md" in x for x in lines)
    assert snapshot(project.root) == before
    assert not list(isolated_codex.iterdir())


def test_cli_dry_run_does_not_create_metadata(repo, data_dir):
    before = snapshot(repo), snapshot(data_dir.parent)
    r = cli(repo, "setup", "codex", "--dry-run", "--with-codegraph")
    assert r.returncode == 0, r.stderr
    assert (snapshot(repo), snapshot(data_dir.parent)) == before


@pytest.mark.skipif(setup._toml("") is None, reason="existing TOML requires tomllib or optional tomli")
def test_setup_idempotent_and_remove_restores_user_bytes(project):
    root = project.root
    original = b"# User instructions\r\nKeep this exact text.\r\n"
    (root / "AGENTS.md").write_bytes(original)
    (root / ".codex").mkdir()
    cfg = b'# keep comments\r\nmodel_reasoning_effort = "high"\r\n'
    (root / ".codex/config.toml").write_bytes(cfg)
    setup.run(project, with_codegraph=True)
    once = snapshot(root)
    setup.run(project, with_codegraph=True)
    assert snapshot(root) == once
    assert hosts.enabled(project) == ["codex"]
    assert (root / "AGENTS.md").read_bytes().startswith(original)
    data = setup._toml((root / ".codex/config.toml").read_text())
    assert data["model_reasoning_effort"] == "high"
    assert data["mcp_servers"]["codegraph"]["args"] == ["serve", "--mcp"]
    setup.run(project, remove_=True)
    assert (root / "AGENTS.md").read_bytes() == original
    assert (root / ".codex/config.toml").read_bytes() == cfg
    assert not (root / setup.MANIFEST).exists()


def test_default_setup_does_not_configure_mcp_or_hooks(project):
    setup.run(project)
    assert not (project.root / ".codex/config.toml").exists()
    assert not (project.root / ".codex/hooks.json").exists()
    text = (project.root / "AGENTS.md").read_text()
    assert "Task tracking is manual" in text and "Tasks are automatic" not in text
    for action in ("init", "resume", "codegraph", "status"):
        assert action in text


def test_unowned_skills_and_other_hosts_are_preserved(project):
    root = project.root
    for name in ("init", "resume", "uccif"):
        p = root / ".agents/skills" / name / "SKILL.md"
        p.parent.mkdir(parents=True)
        p.write_text("User-owned: " + name)
    before = snapshot(root)
    lines = setup.run(project)
    assert any("Skipped .agents/skills/uccif/SKILL.md" in x for x in lines)
    setup.run(project, remove_=True)
    assert snapshot(root) == before


@pytest.mark.parametrize("rel", ["AGENTS.md", ".agents/skills/uccif-codex-resume/SKILL.md",
                                 ".codex/config.toml"])
def test_edited_owned_content_survives_setup_and_remove(project, rel):
    setup.run(project, with_codegraph=True)
    p = project.root / rel
    # Edit inside the owned block, not merely surrounding text.
    text = p.read_text().replace("UCCIF", "MY-UCCIF", 1) if rel.endswith("SKILL.md") else p.read_text()
    if rel == "AGENTS.md":
        text = text.replace("## UCCIF for Codex", "## My UCCIF for Codex")
    elif rel.endswith("config.toml"):
        text = text.replace('command = "codegraph"', 'command = "my-codegraph"')
    p.write_text(text)
    setup.run(project, with_codegraph=True)
    assert p.read_text() == text
    setup.run(project, remove_=True)
    assert p.read_text() == text
    assert rel in json.loads((project.root / setup.MANIFEST).read_text())["files"]


def test_user_text_added_around_block_survives_removal(project):
    setup.run(project)
    p = project.root / "AGENTS.md"
    p.write_text("Before\n" + p.read_text() + "After\n")
    setup.run(project, remove_=True)
    assert p.read_text() == "Before\nAfter\n"


def test_line_ending_normalization_does_not_make_owned_block_unremovable(project):
    setup.run(project)
    p = project.root / "AGENTS.md"
    normalized = p.read_bytes().decode("utf-8").replace("\n", "\r\n")
    p.write_bytes(("Before\r\n" + normalized + "After\r\n").encode("utf-8"))
    setup.run(project, remove_=True)
    assert p.read_bytes() == b"Before\r\nAfter\r\n"


def test_task_history_is_never_removed(project):
    tk = task.start(project, "shared task", "bug")
    setup.run(project)
    setup.run(project, remove_=True)
    assert task.load_current(project)["id"] == tk["id"]


@pytest.mark.parametrize("location", ["project", "user", "parent"])
@pytest.mark.parametrize("enabled", [True, False])
@pytest.mark.skipif(setup._toml("") is None, reason="existing TOML requires tomllib or optional tomli")
def test_existing_mcp_is_not_duplicated(project, isolated_codex, location, enabled):
    root = project.root
    cfg = (root / ".codex/config.toml" if location == "project" else
           isolated_codex / "config.toml" if location == "user" else
           root.parent / ".codex/config.toml")
    cfg.parent.mkdir(parents=True, exist_ok=True)
    original = '[mcp_servers.existing]\ncommand = "codegraph"\nenabled = %s\n' % str(enabled).lower()
    cfg.write_text(original)
    lines = setup.run(project, with_codegraph=True)
    assert cfg.read_text() == original
    assert any("Skipped MCP" in x for x in lines)
    assert ".codex/config.toml" not in json.loads((root / setup.MANIFEST).read_text())["files"]
    status = setup.mcp_status(project)
    assert status["configured"] is enabled and status["verified"] is False


@pytest.mark.parametrize("text", ['this is not TOML', '[plugins."uccif@example"]\nenabled = true\n'])
def test_unknown_config_or_plugin_does_not_get_mcp_added(project, isolated_codex, text):
    (isolated_codex / "config.toml").write_text(text)
    setup.run(project, with_codegraph=True)
    assert not (project.root / ".codex/config.toml").exists()
    assert setup.mcp_status(project)["unknown"]


def test_no_toml_reader_preserves_existing_config(project, monkeypatch):
    p = project.root / ".codex/config.toml"
    p.parent.mkdir()
    p.write_text('model = "existing-model"\n')
    monkeypatch.setattr(setup, "_toml", lambda text: None)
    setup.run(project, with_codegraph=True)
    assert p.read_text() == 'model = "existing-model"\n'


def test_claude_manifest_does_not_claim_codex_mcp(project):
    assert codegraph.plugin_mcp()
    state = codegraph.state(project, host="codex")
    assert not state["mcp"] and state["mcp_via"] is None and not state["mcp_verified"]


def test_codex_hooks_are_not_a_claude_fallback(project):
    out = io.StringIO()
    assert hooks.run("UserPromptSubmit", stdin=io.StringIO(json.dumps({
        "cwd": str(project.root), "prompt": "do not process"})), stdout=out, host="codex") == 0
    assert out.getvalue() == ""
    assert not (project.local_dir / "hosts.json").exists()


def test_shared_skill_directory_is_deduplicated(project):
    assert hosts.skill_dirs(project, ["gemini", "antigravity", "codex"]) == [
        project.root / ".agents/skills"]


def test_corrupt_manifest_is_not_overwritten(project):
    p = project.root / setup.MANIFEST
    p.parent.mkdir()
    p.write_text("invalid json")
    with pytest.raises(ValueError):
        setup.run(project)
    assert p.read_text() == "invalid json" and not (project.root / "AGENTS.md").exists()


def test_tampered_manifest_cannot_remove_other_files(project):
    p = project.root / setup.MANIFEST
    p.parent.mkdir()
    p.write_text(json.dumps({"files": {"../valuable.txt": {"sha256": "x"}}}))
    with pytest.raises(ValueError, match="owned path"):
        setup.run(project, remove_=True)


@pytest.mark.skipif(os.name == "nt", reason="creating symlinks needs Windows privileges")
@pytest.mark.parametrize("rel", ["AGENTS.md", ".agents", ".codex", ".codex/.uccif-setup.json"])
def test_symlinks_are_not_followed(project, tmp_path, rel):
    dest = tmp_path / "outside"
    if rel.endswith(".md") or rel.endswith(".json"):
        dest.write_text("do not touch")
    else:
        dest.mkdir()
    p = project.root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.symlink_to(dest, target_is_directory=dest.is_dir())
    with pytest.raises(ValueError, match="symlink"):
        setup.run(project)
    if dest.is_file():
        assert dest.read_text() == "do not touch"
    else:
        assert not list(dest.iterdir())


def test_ambiguous_markers_fail_before_other_writes(project):
    p = project.root / "AGENTS.md"
    p.write_text(setup.AGENTS_BEGIN + "\n")
    with pytest.raises(ValueError, match="ambiguous"):
        setup.run(project)
    assert not (project.root / ".agents").exists()


def test_real_cli_setup_status_and_removal_in_path_with_spaces(repo):
    path = repo / "project with spaces"
    path.mkdir()
    result = cli(path, "setup", "codex")
    # git discovery resolves a subdirectory back to the repository root.
    assert result.returncode == 0, result.stderr
    assert "No hooks installed" in result.stdout
    doctor = cli(path, "doctor", "--host", "codex")
    assert doctor.returncode == 0 and "unverified" in doctor.stdout
    assert cli(path, "setup", "codex", "--remove").returncode == 0
    assert not (repo / setup.MANIFEST).exists()


def test_rendered_core_command_really_runs(project):
    r = subprocess.run(setup.command() + " version", shell=True, cwd=str(project.root),
                       capture_output=True, text=True)
    assert r.returncode == 0 and r.stdout.startswith("uccif ")
    for name, text in codex_workflows.skills(setup.command()).items():
        assert "name: %s\n" % name in text and "description:" in text
        description = next(line for line in text.splitlines() if line.startswith("description: "))
        assert json.loads(description[len("description: "):]) == codex_workflows.WORKFLOWS[name][0]
        assert "UCCIF_COMMAND" not in text and "/uccif:" not in text
        assert len(text.splitlines()) < 100


def test_missing_manifest_remove_dry_run_is_noop(project):
    before = snapshot(project.root)
    setup.run(project, remove_=True, dry_run=True)
    assert snapshot(project.root) == before


def test_core_path_with_spaces_is_executable(project, tmp_path, monkeypatch):
    core = tmp_path / "plugin with spaces"
    (core / "scripts").mkdir(parents=True)
    shutil.copy(PLUGIN / "scripts/uccif_main.py", core / "scripts/uccif_main.py")
    shutil.copytree(PLUGIN / "uccif_lib", core / "uccif_lib", ignore=shutil.ignore_patterns("__pycache__"))
    monkeypatch.setattr(setup, "__file__", str(core / "uccif_lib/codex_setup.py"))
    result = subprocess.run(setup.command() + " version", shell=True, cwd=str(project.root),
                            text=True, capture_output=True)
    assert result.returncode == 0 and result.stdout.startswith("uccif ")


def test_failed_later_write_restores_user_files(project, monkeypatch):
    original = "User instructions\n"
    (project.root / "AGENTS.md").write_text(original)
    atomic = setup.write_text_atomic

    def fail_skill(path, text):
        if str(path).endswith("SKILL.md"):
            raise PermissionError("read-only destination")
        atomic(path, text)

    monkeypatch.setattr(setup, "write_text_atomic", fail_skill)
    with pytest.raises(PermissionError):
        setup.run(project)
    assert (project.root / "AGENTS.md").read_text() == original
    assert not (project.root / setup.MANIFEST).exists()
    assert not list(project.root.rglob("SKILL.md"))


def test_mcp_creation_does_not_require_a_toml_parser(project, monkeypatch):
    monkeypatch.setattr(setup, "_toml", lambda text: None)
    setup.run(project, with_codegraph=True)
    assert '[mcp_servers.codegraph]' in (project.root / ".codex/config.toml").read_text()


def test_remove_preview_preserves_installed_files(project):
    setup.run(project, with_codegraph=True)
    before = snapshot(project.root)
    setup.run(project, remove_=True, dry_run=True)
    assert snapshot(project.root) == before


def test_manual_task_workflow_through_real_cli(repo):
    assert cli(repo, "setup", "codex").returncode == 0
    assert cli(repo, "task", "start", "Codex workflow", "--type", "feature").returncode == 0
    (repo / "example.py").write_text("value = 1\n")
    assert cli(repo, "task", "checkpoint", "--file", "example.py", "--next", "Review example").returncode == 0
    shown = cli(repo, "task", "show")
    assert shown.returncode == 0 and "example.py" in shown.stdout and "Review example" in shown.stdout
    assert cli(repo, "setup", "codex", "--remove").returncode == 0
    assert "Review example" in cli(repo, "task", "show").stdout
    assert cli(repo, "task", "close", "--no-findings").returncode == 0


def test_setup_works_without_git(tmp_path):
    from uccif_lib.paths import resolve_project
    root = tmp_path / "non-git project"
    root.mkdir()
    project = resolve_project(root, create=False)
    setup.run(project)
    assert (root / "AGENTS.md").is_file()
    setup.run(project, remove_=True)
    assert not (root / "AGENTS.md").exists()


def test_concurrent_setup_keeps_single_owned_block(project):
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: setup.run(project), range(2)))
    assert len(results) == 2
    assert (project.root / "AGENTS.md").read_text().count(setup.AGENTS_BEGIN) == 1
    manifest = json.loads((project.root / setup.MANIFEST).read_text())
    assert len(manifest["files"]) == len(codex_workflows.WORKFLOWS) + 1
