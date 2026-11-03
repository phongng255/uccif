"""Install, update, and uninstall UCCIF for Antigravity and Claude Code."""

import os
import shutil
import subprocess
import sys
from pathlib import Path


def find_agy():
    cand = shutil.which("agy")
    if cand:
        return cand
    gemini_agy = Path.home() / ".gemini" / "bin" / "agy"
    if gemini_agy.is_file() and os.access(str(gemini_agy), os.X_OK):
        return str(gemini_agy)
    return None


def find_claude():
    return shutil.which("claude")


def repo_root():
    plugin_dir = Path(__file__).resolve().parent.parent
    candidate = plugin_dir.parent.parent
    if (candidate / ".git").is_dir() or (candidate / "plugins" / "uccif").is_dir():
        return candidate
    return plugin_dir


def plugin_dir():
    return Path(__file__).resolve().parent.parent


def install(target="auto"):
    """Install UCCIF plugin into Antigravity (agy) and/or Claude Code."""
    p_dir = plugin_dir()
    installed_any = False

    # 1. Antigravity CLI
    if target in ("auto", "antigravity", "all"):
        agy = find_agy()
        if agy:
            print("→ Installing UCCIF into Antigravity CLI (agy)...")
            res = subprocess.run([agy, "plugin", "install", str(p_dir)], text=True)
            if res.returncode == 0:
                installed_any = True
                print("✔ Successfully installed UCCIF in Antigravity.")
            else:
                print("✗ Failed to install UCCIF in Antigravity.")
        else:
            if target == "antigravity":
                print("✗ Antigravity CLI (agy) not found.")
            else:
                print("· Antigravity CLI (agy) not found (skipping).")

    # 2. Claude Code
    if target in ("auto", "claude", "all"):
        claude = find_claude()
        if claude:
            print("→ Installing UCCIF into Claude Code...")
            # Try adding local or marketplace
            subprocess.run([claude, "plugin", "marketplace", "add", "phongng255/uccif"],
                           capture_output=True)
            res = subprocess.run([claude, "plugin", "install", "uccif@uccif"], text=True)
            if res.returncode == 0:
                installed_any = True
                print("✔ Successfully installed UCCIF in Claude Code.")
            else:
                print("· Could not install from marketplace, trying local plugin path...")
                res2 = subprocess.run([claude, "plugin", "install", str(p_dir)], text=True)
                if res2.returncode == 0:
                    installed_any = True
                    print("✔ Successfully installed UCCIF in Claude Code.")
                else:
                    print("✗ Failed to install UCCIF in Claude Code.")
        else:
            if target == "claude":
                print("✗ Claude Code CLI (claude) not found.")
            else:
                print("· Claude Code CLI (claude) not found (skipping).")

    if not installed_any and target == "auto":
        print("Warning: Neither Antigravity (agy) nor Claude Code was found on PATH.")
        return 1
    return 0


def update(target="auto"):
    """Pull latest source code and reinstall UCCIF plugin."""
    root = repo_root()
    git_dir = root / ".git"

    if git_dir.is_dir() and shutil.which("git"):
        print("→ Pulling latest updates from git repository (%s)..." % root.name)
        res = subprocess.run(["git", "pull"], cwd=str(root), text=True)
        if res.returncode != 0:
            print("Warning: 'git pull' exited with code %d. Continuing with plugin re-install..." % res.returncode)
    else:
        print("· Not a git clone or git not available, skipping 'git pull'.")

    return install(target=target)


def uninstall(target="auto"):
    """Uninstall UCCIF plugin from Antigravity and/or Claude Code."""
    removed_any = False

    if target in ("auto", "antigravity", "all"):
        agy = find_agy()
        if agy:
            print("→ Uninstalling UCCIF from Antigravity CLI...")
            res = subprocess.run([agy, "plugin", "uninstall", "uccif"], text=True)
            if res.returncode == 0:
                removed_any = True
                print("✔ Uninstalled UCCIF from Antigravity.")
        else:
            if target == "antigravity":
                print("✗ Antigravity CLI (agy) not found.")

    if target in ("auto", "claude", "all"):
        claude = find_claude()
        if claude:
            print("→ Uninstalling UCCIF from Claude Code...")
            res = subprocess.run([claude, "plugin", "uninstall", "uccif@uccif"], text=True)
            if res.returncode == 0:
                removed_any = True
                print("✔ Uninstalled UCCIF from Claude Code.")
        else:
            if target == "claude":
                print("✗ Claude Code CLI (claude) not found.")

    return 0 if removed_any else 1


def status():
    """Print installation status of UCCIF across Antigravity and Claude Code."""
    print("=== UCCIF Status ===")
    
    # Antigravity status
    agy = find_agy()
    ag_plugin = Path.home() / ".gemini" / "config" / "plugins" / "uccif"
    if agy:
        print("Antigravity CLI (agy) : Available (%s)" % agy)
        if ag_plugin.is_dir():
            print("Antigravity Plugin    : Installed (%s)" % ag_plugin)
        else:
            print("Antigravity Plugin    : Not installed (run 'uccif install')")
    else:
        print("Antigravity CLI (agy) : Not found")

    # Claude Code status
    claude = find_claude()
    claude_plugin = Path.home() / ".claude" / "plugins" / "marketplaces" / "uccif"
    if claude:
        print("Claude Code CLI       : Available (%s)" % claude)
        if claude_plugin.is_dir():
            print("Claude Code Plugin    : Installed (%s)" % claude_plugin)
        else:
            print("Claude Code Plugin    : Not installed (run 'uccif install')")
    else:
        print("Claude Code CLI       : Not found")

    # CodeGraph status
    cg = shutil.which("codegraph")
    if cg:
        try:
            ver = subprocess.run([cg, "--version"], capture_output=True, text=True, timeout=5)
            print("CodeGraph CLI         : Available %s (%s)" % (ver.stdout.strip(), cg))
        except Exception:
            print("CodeGraph CLI         : Available (%s)" % cg)
    else:
        print("CodeGraph CLI         : Not installed (npm install -g @colbymchenry/codegraph)")

    return 0
