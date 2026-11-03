import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
PLUGIN = REPO / "plugins" / "uccif"
sys.path.insert(0, str(PLUGIN))

ENV_VARS = ("UCCIF_DATA_DIR", "UCCIF_SYNC", "CLAUDE_PLUGIN_DATA", "CLAUDE_PROJECT_DIR", "CLAUDE_ENV_FILE",
            "CLAUDE_PLUGIN_OPTION_REPLY_LANGUAGE", "CLAUDE_PLUGIN_OPTION_TOKEN_REPORT", "UCCIF_NO_TREE_SITTER")


def git(cwd, *args):
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t"] + list(args),
                   cwd=str(cwd), check=True, capture_output=True)


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    for var in ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    d = tmp_path / "data"
    monkeypatch.setenv("UCCIF_DATA_DIR", str(d))
    monkeypatch.setenv("UCCIF_SYNC", "1")  # background upkeep runs inline in tests
    monkeypatch.setenv("UCCIF_NO_TREE_SITTER", "1")  # regex/ctags path by default; ts tests opt in
    return d


@pytest.fixture
def repo(tmp_path, monkeypatch):
    r = tmp_path / "repo"
    r.mkdir()
    git(r, "init", "-q")
    git(r, "commit", "-q", "--allow-empty", "-m", "init")
    monkeypatch.chdir(r)
    return Path(os.path.realpath(str(r)))


@pytest.fixture
def project(repo):
    from uccif_lib.paths import resolve_project
    return resolve_project()


def write_transcript(path, entries):
    path.write_text("".join(json.dumps(e) + "\n" for e in entries), encoding="utf-8")
    return path


def prompt(text="hi"):
    return {"type": "user", "message": {"role": "user", "content": text}}


def tool_result():
    return {"type": "user", "message": {"role": "user",
                                        "content": [{"type": "tool_result", "content": "ok"}]}}


def assistant(mid, inp=0, cache_read=0, cache_new=0, out=0, model="m", sidechain=False):
    e = {"type": "assistant", "message": {"id": mid, "model": model, "usage": {
        "input_tokens": inp, "cache_read_input_tokens": cache_read,
        "cache_creation_input_tokens": cache_new, "output_tokens": out}}}
    if sidechain:
        e["isSidechain"] = True
    return e


def run_hook(event, data, raw=None):
    """Run a hook handler in-process; return (exit_code, parsed_stdout_or_None)."""
    from uccif_lib import hooks
    out = io.StringIO()
    code = hooks.run(event, stdin=io.StringIO(raw if raw is not None else json.dumps(data)), stdout=out)
    text = out.getvalue()
    return code, (json.loads(text) if text else None)


def hook_log(project):
    from uccif_lib import log
    return log.read(project, "hooks.jsonl")


VUE_APP = Path(__file__).resolve().parent / "fixtures" / "vue-app"


def copy_vue_app(dest):
    """Copy the fixed JS/TS fixture app (it has .vue files, read for their <script>) into `dest` and commit it."""
    import shutil
    for src in sorted(VUE_APP.rglob("*")):
        if src.is_file():
            target = Path(dest) / src.relative_to(VUE_APP)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(str(src), str(target))
    git(dest, "add", "-A")
    git(dest, "commit", "-q", "-m", "vue-app fixture")


@pytest.fixture
def vue_app(repo):
    copy_vue_app(repo)
    return repo
