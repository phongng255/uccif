"""Generated Codex package stays portable, current and separate from other hosts."""

import json
from pathlib import Path
import subprocess
import sys

from conftest import PLUGIN, REPO
from uccif_lib import __version__, codex_workflows

sys.path.insert(0, str(PLUGIN / "scripts"))
import build_codex  # noqa: E402


def test_generated_codex_package_is_current():
    assert build_codex.build(check=True) == ([], [])


def test_codex_manifest_and_separate_marketplace():
    manifest = json.loads((build_codex.DST / "plugin.json").read_text())
    assert manifest["name"] == "uccif" and manifest["version"] == __version__
    catalog = json.loads(build_codex.MARKETPLACE.read_text())
    entry = catalog["plugins"][0]
    assert entry["name"] == manifest["name"]
    assert (REPO / entry["source"]["path"]).resolve() == build_codex.DST
    assert entry["policy"]["installation"] == "AVAILABLE"
    # Claude's marketplace still selects its original core plugin.
    claude = json.loads((REPO / ".claude-plugin/marketplace.json").read_text())
    assert claude["plugins"][0]["source"] == "./plugins/uccif"


def test_packaged_skills_have_local_resource_links_and_native_names():
    assert set(codex_workflows.packaged_skills()) == {"uccif", "init", "resume", "codegraph"}
    for name in codex_workflows.packaged_skills():
        path = build_codex.DST / "skills" / name / "SKILL.md"
        text = path.read_text()
        assert "name: %s\n" % name in text
        assert "/workspace/" not in text and "${PLUGIN_ROOT}" not in text
        target = (path.parent / "../../core/scripts/uccif_main.py").resolve()
        assert build_codex.DST in target.parents and target.is_file()
    router = (build_codex.DST / "skills/uccif/SKILL.md").read_text()
    assert "`uccif:init`" in router and "`uccif:resume`" in router


def test_packaged_core_runs_without_the_original_checkout(tmp_path):
    import shutil
    package = tmp_path / "installed plugin with spaces"
    shutil.copytree(build_codex.DST, package, ignore=shutil.ignore_patterns("__pycache__"))
    proc = subprocess.run([sys.executable, str(package / "core/scripts/uccif_main.py"), "version"],
                          cwd=tmp_path, capture_output=True, text=True)
    assert proc.returncode == 0 and proc.stdout.startswith("uccif %s " % __version__)
    doctor = subprocess.run([sys.executable, str(package / "core/scripts/uccif_main.py"),
                             "doctor", "--host", "codex"], cwd=tmp_path, capture_output=True, text=True)
    assert doctor.returncode == 0 and "packaged core" in doctor.stdout
    assert not any(p.is_symlink() for p in package.rglob("*"))


def test_workflow_preview_does_not_install_hooks_or_autostart_mcp():
    assert not (build_codex.DST / "hooks").exists()
    assert not (build_codex.DST / "mcp.json").exists()
    # Server definition is a core template for an explicit project setup request.
    assert (build_codex.DST / "core/.mcp.json").is_file()
