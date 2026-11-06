"""Verify discovery and local plugin installation with a real, pinned Codex binary.

No model turn, API key, trust bypass or user configuration is used. Every mutation is
scoped to a temporary HOME/CODEX_HOME and temporary Git projects. This checks the real
host's discovery protocol, not the behavior of a language model executing a workflow.
"""

import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import time

REPO = Path(__file__).resolve().parent.parent
PINNED_VERSION = "codex-cli 0.167.0"


def run(argv, cwd, env):
    result = subprocess.run(list(map(str, argv)), cwd=str(cwd), env=env, capture_output=True,
                            text=True, encoding="utf-8", timeout=30)
    if result.returncode:
        raise RuntimeError("%s failed: %s" % (argv[0], result.stderr[-1500:]))
    return result.stdout


@contextmanager
def server(binary, cwd, env):
    messages = queue.Queue()
    # Keep local plugins enabled, but avoid optional remote catalog/auth requests.
    with tempfile.TemporaryFile(mode="w+") as errors:
        proc = subprocess.Popen([str(binary), "app-server", "--listen", "stdio://",
                                 "--disable", "remote_plugin", "--disable", "plugin_discovery_prefetch"],
                                cwd=str(cwd), env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=errors, text=True, encoding="utf-8", bufsize=1)

        def read():
            for line in proc.stdout:
                try:
                    messages.put(json.loads(line))
                except ValueError:
                    pass

        reader = threading.Thread(target=read, daemon=True)
        reader.start()
        request_id = 0

        def rpc(method, params, notify=False):
            nonlocal request_id
            request_id += 1
            payload = {"method": method, "params": params}
            if not notify:
                payload["id"] = request_id
            proc.stdin.write(json.dumps(payload) + "\n")
            proc.stdin.flush()
            if notify:
                return None
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                try:
                    message = messages.get(timeout=max(.01, deadline - time.monotonic()))
                except queue.Empty:
                    break
                if message.get("id") == request_id:
                    if "error" in message:
                        raise RuntimeError("%s: %s" % (method, message["error"]))
                    return message["result"]
            raise RuntimeError("Codex RPC timed out: %s (not counted as verified)" % method)

        try:
            rpc("initialize", {"clientInfo": {"name": "uccif_cloud_verifier", "version": "0.1.0"},
                               "capabilities": {"experimentalApi": True}})
            rpc("initialized", {}, notify=True)
            yield rpc
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
            reader.join(timeout=2)
            proc.stdin.close()
            proc.stdout.close()


def discover(binary, project, env):
    with server(binary, project, env) as rpc:
        result = rpc("skills/list", {"cwds": [str(project)], "forceReload": True})
        assert len(result["data"]) == 1
        group = result["data"][0]
        assert not group["errors"], group["errors"]
        return [skill for skill in group["skills"] if "uccif" in skill["name"]]


def verify(binary):
    with tempfile.TemporaryDirectory(prefix="uccif-codex-runtime-") as temp:
        root = Path(temp)
        home = root / "home"
        codex_home = home / ".codex"
        codex_home.mkdir(parents=True)
        # Carry only process/platform/proxy plumbing, never account or service credentials.
        keep = ("PATH", "SystemRoot", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP",
                "TMPDIR", "LANG", "LC_ALL", "LC_CTYPE", "TERM", "NO_COLOR", "HTTP_PROXY", "HTTPS_PROXY",
                "ALL_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "all_proxy", "no_proxy",
                "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE", "NODE_EXTRA_CA_CERTS", "CODEX_PROXY_CERT")
        env = {key: os.environ[key] for key in keep if key in os.environ}
        env.update(HOME=str(home), USERPROFILE=str(home), CODEX_HOME=str(codex_home),
                   UCCIF_DATA_DIR=str(root / "uccif-data"))
        version = run([binary, "--version"], root, env).strip()
        assert version == PINNED_VERSION, "Expected %s; got %s" % (PINNED_VERSION, version)
        project = root / "plugin-project"
        project.mkdir()
        run(["git", "init", "-q"], project, env)
        added = json.loads(run([binary, "plugin", "marketplace", "add", REPO, "--json"], project, env))
        assert added["marketplaceName"] == "uccif-codex-local"
        installed = json.loads(run([binary, "plugin", "add", "uccif@uccif-codex-local", "--json"], project, env))
        package = Path(installed["installedPath"])
        skills = discover(binary, project, env)
        expected = {"uccif:init", "uccif:resume", "uccif:codegraph", "uccif:uccif"}
        assert {s["name"] for s in skills} == expected
        assert all(s["enabled"] and s["pluginId"] == "uccif@uccif-codex-local" for s in skills)
        for skill in skills:
            path = Path(skill["path"])
            assert package in path.parents
            core = (path.parent / "../../core/scripts/uccif_main.py").resolve()
            assert package in core.parents and core.is_file()
        core = package / "core/scripts/uccif_main.py"
        assert run([sys.executable, core, "version"], project, env).startswith("uccif ")
        assert "packaged core" in run([sys.executable, core, "doctor", "--host", "codex"], project, env)
        run([sys.executable, core, "task", "start", "Runtime verification", "--type", "test"], project, env)
        run([sys.executable, core, "task", "checkpoint", "--next", "Verify saved state"], project, env)
        assert "Verify saved state" in run([sys.executable, core, "task", "show"], project, env)
        run([sys.executable, core, "task", "close", "--no-findings"], project, env)
        run([sys.executable, core, "setup", "codex"], project, env)
        combined = discover(binary, project, env)
        assert {s["name"] for s in combined} == expected | {
            "uccif", "uccif-codex-init", "uccif-codex-resume", "uccif-codex-codegraph"}
        run([sys.executable, core, "setup", "codex", "--remove"], project, env)
        assert {s["name"] for s in discover(binary, project, env)} == expected
        run([binary, "plugin", "remove", "uccif@uccif-codex-local"], project, env)
        assert not discover(binary, project, env), "Uninstalled plugin skills still loaded"
        assert (project / ".claude/uccif/.local/tasks").is_dir(), "Plugin uninstall removed task history"

        # Verify repository setup independently of the plugin's namespace.
        target = root / "repository-project"
        target.mkdir()
        run(["git", "init", "-q"], target, env)
        source_main = REPO / "plugins/uccif/scripts/uccif_main.py"
        run([sys.executable, source_main, "setup", "codex"], target, env)
        repo_skills = discover(binary, target, env)
        assert {s["name"] for s in repo_skills} == {
            "uccif", "uccif-codex-init", "uccif-codex-resume", "uccif-codex-codegraph"}
        assert all(s["scope"] == "repo" and s["enabled"] and s.get("pluginId") is None for s in repo_skills)
        run([sys.executable, source_main, "setup", "codex", "--remove"], target, env)
        assert not discover(binary, target, env), "Removed repository skills still loaded"

        # Inspect the native review boundary, without trusting or executing a hook.
        # This trust entry applies only to a temporary test project, not user configuration.
        hooks_dir = target / ".codex"
        hooks_dir.mkdir(exist_ok=True)
        hook_path = hooks_dir / "hooks.json"
        hook_path.write_text(json.dumps({"hooks": {"SessionStart": [{"hooks": [{
            "type": "command", "command": "python3 -c 'pass'"}]}]}}), encoding="utf-8")
        config_path = codex_home / "config.toml"
        config_path.write_text(config_path.read_text(encoding="utf-8") +
                               "\n[projects.%s]\ntrust_level = \"trusted\"\n" % json.dumps(str(target)),
                               encoding="utf-8")
        with server(binary, target, env) as rpc:
            found = rpc("hooks/list", {"cwds": [str(target)]})
            local = [h for group in found["data"] for h in group["hooks"]
                     if h["sourcePath"] == str(hook_path)]
            assert len(local) == 1 and local[0]["trustStatus"] == "untrusted"
        return {"codex_version": version, "platform": sys.platform,
                "plugin_install": "passed", "plugin_skill_discovery": sorted(expected),
                "installed_core_and_task_cli": "passed", "plugin_uninstall": "passed",
                "plugin_repository_coexistence": "passed; distinct qualified names",
                "repository_skill_discovery_and_remove": "passed",
                "untrusted_hook_discovery": "passed; not trusted or executed",
                "model_turn": "not run", "hook_execution": "not verified",
                "desktop_vscode_ui": "not tested", "credentials_used": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex-bin", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = verify(args.codex_bin.resolve())
    text = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    print(text, end="")
