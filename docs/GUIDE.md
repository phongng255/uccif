# UCCIF Guide (For Beginners)

This guide is written for everyone, even if you have **never used a command-line terminal** before. Every step includes copy-pasteable commands and real example output.

---

## 1. What is UCCIF and How Does It Help You?

Normally, when you use coding AI assistants (like Claude Code, Gemini CLI, or Antigravity), every time you ask a question or switch tasks, the AI tends to "forget" previous context, searches slowly through files, and burns through your API tokens.

**UCCIF** acts like an intelligent background project manager alongside your AI:
1. **Automatic Task Memory:** As soon as the AI makes its first edit, UCCIF records what you're working on. Even if you restart your machine or clear the chat history (`/clear`), the AI remembers where it left off.
2. **Smart Code Map:** Uses CodeGraph to build an instant index of your codebase. The AI navigates symbols directly without guessing or scanning whole files, answering faster while saving up to 70% in token costs.
3. **Safe Guidelines:** Keeps the AI focused, requiring verification after edits and keeping communication clear.

---

## 2. Prerequisites & Environment Setup

Before using UCCIF, make sure your machine has **Git**, **Python**, and **Node.js** installed. Open your terminal (Terminal on macOS/Linux or PowerShell on Windows) and follow the instructions below.

### Step 2.1: Open your Terminal
- **macOS:** Press `Command + Space`, type `Terminal`, and press `Enter`.
- **Windows:** Press the `Windows` key, type `PowerShell`, right-click **Windows PowerShell** and choose **Run as Administrator**.
- **Linux:** Press `Ctrl + Alt + T`.

---

### Step 2.2: Check or Install Git

**Check command:**
```bash
git --version
```
*Expected output:*
```text
git version 2.39.0 (or similar version number)
```

**If Git is not installed:**
- **macOS:** Run `xcode-select --install` and click **Install** in the popup window.
- **Windows:** Download and install from [git-scm.com/download/win](https://git-scm.com/download/win) (keep default options).
- **Ubuntu/Linux:** Run:
  ```bash
  sudo apt update && sudo apt install -y git
  ```

---

### Step 2.3: Check or Install Python (Version 3.8 or higher)

**Check command:**
```bash
python3 --version || python --version
```
*Expected output:*
```text
Python 3.10.12 (or any version >= 3.8)
```

**If Python is not installed:**
- **macOS:** Download the official installer from [python.org/downloads](https://www.python.org/downloads/) or via Homebrew: `brew install python`.
- **Windows:** Download from [python.org/downloads](https://www.python.org/downloads/). *(Important: Be sure to check the box "Add Python to PATH" on the first screen)*.
- **Ubuntu/Linux:** Run:
  ```bash
  sudo apt update && sudo apt install -y python3 python3-pip
  ```

---

### Step 2.4: Check or Install Node.js (Version 18 or higher)

Node.js is required by the CodeGraph indexer.

**Check command:**
```bash
node --version && npm --version
```
*Expected output:*
```text
v20.18.0
10.8.2
```

**If Node.js is not installed:**
- **macOS / Windows:** Download and install the LTS version from [nodejs.org](https://nodejs.org/).
- **Ubuntu/Linux:** Run:
  ```bash
  curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
  sudo apt install -y nodejs
  ```

---

## 3. Installing UCCIF for Your Tool

Choose the section corresponding to the AI tool you use:

```
+-------------------------------------------------------------------+
|  Which tool are you using?                                        |
|  - Claude Code: See Section 3.1                                   |
|  - Antigravity CLI (agy command): See Section 3.2                 |
|  - Antigravity IDE: See Section 3.3                               |
|  - Gemini CLI (Enterprise accounts only): See Section 3.4         |
+-------------------------------------------------------------------+
```

---

### 3.1. For Claude Code

#### 1. Installation Commands
Launch Claude Code in your terminal:
```bash
claude
```
Inside the Claude Code chat interface, run the following two commands:
```text
/plugin marketplace add phongng255/uccif
/plugin install uccif@uccif
```

#### 2. Verify Installation
Run:
```text
/plugin list
```
*Expected output:* You should see `uccif` listed with status `enabled`.

#### 3. First Session in a Project
- Open your project directory with `claude`.
- Ask any question, for example: `"What does this project do?"`.
- Claude will detect that CodeGraph is not yet installed and ask you once:
  > *"CodeGraph is NOT installed. Install it now? (yes/no)"*
- Simply answer: **`yes`**. Claude Code will install CodeGraph, index the repo, and generate project skills. Restart Claude Code once to finalize the MCP tool integration.

---

### 3.2. For Antigravity CLI (`agy`)

> [!NOTE]
> Google deprecated free Gemini CLI access on June 18, 2026, replacing it with **Antigravity CLI** (`agy`). This is the standard tool for individual and non-enterprise users.

#### 1. Installation Command
In your terminal, run:
```bash
agy plugin install https://github.com/phongng255/uccif/tree/main/plugins/uccif-antigravity
```
*Or if you cloned the repository locally:*
```bash
agy plugin install /path/to/uccif/plugins/uccif-antigravity
```

#### 2. Verify Installation
Run:
```bash
agy plugin list
```
*Expected output:*
```text
Installed plugins:
- uccif (enabled, 1.1.0)
    Source:     antigravity
    Components: 3 skills, 1 MCP server, 1 hook
```

#### 3. First Experience
Open any project folder and start `agy`:
```bash
agy
```
UCCIF activates immediately: core guidelines are loaded, project structure is indexed, and you're ready to code.

---

### 3.3. For Antigravity IDE

Antigravity IDE reads workspace customizations from the project's `.agents/` folder.

#### 1. Setup in a Project
In your terminal, navigate to your project folder and run:
```bash
cd /path/to/your/project
python3 /path/to/uccif/plugins/uccif/bin/uccif setup antigravity
```
*(On Windows, replace `python3` with `python`)*.

*Expected output:*
```text
uccif: configured .agents/ for Antigravity IDE (rules, skills, mcp_config.json)
```

#### 2. Verify Installation
Check the created files in `.agents/`:
- `.agents/rules/uccif.md`: Project rules.
- `.agents/mcp_config.json`: CodeGraph MCP configuration.

Open the project in Antigravity IDE, and the IDE automatically activates all skills and rules.

---

### 3.4. For Gemini CLI (Gemini Code Assist Enterprise)

> [!IMPORTANT]
> This applies only to paid **Gemini Code Assist Enterprise** subscriptions. Free personal Google accounts cannot authenticate with Gemini CLI.

#### 1. Installation Command
In your terminal, run:
```bash
gemini extensions install https://github.com/phongng255/uccif.git
```

#### 2. Verify Installation
```bash
gemini extensions list
```
You should see `uccif` listed in the installed extensions.

---

## 4. Daily Usage

Once installed, **you do not need to memorize any technical commands**. Just talk naturally to your AI.

### Example prompts in natural language:
- *"Explain how the user authentication flow works in this project."*
- *"Where is the calculateTotal function defined?"*
- *"I want to add email notifications. Which files do I need to touch?"*
- *"Run the test suite and verify our changes didn't break anything."*

### What Does the Token Line (🔢) Mean?
After each AI response in Claude Code, you will see a status line:
```text
🔢 2.4k tok (+120 cache 90%) · turn 3 · 💡 /clear recommended (task saved)
```
- **Meaning:** Shows exact token consumption for the turn and the prompt caching percentage.
- **The `/clear` recommendation:** When conversations get long, UCCIF suggests `/clear`. You can safely clear because active tasks and decisions are already stored on disk.

### Which Files to Commit to Git?

| File / Folder | Commit? | Purpose |
| :--- | :---: | :--- |
| `AGENTS.md` | **YES** | Shared AI guidelines for the repo. |
| `.claude/skills/` or `.agents/skills/` | **YES** | Pre-built code map skills for team AI use. |
| `.claude/uccif/summary.md` | **YES** | High-level project summary and conventions. |
| `.claude/uccif/.local/` | **NO** | Local session tasks (auto-ignored by git). |
| `.codegraph/` | **NO** | Local SQLite index database (auto-ignored). |

---

## 5. Updating to New Versions

When new UCCIF updates are released:

### Claude Code:
Inside Claude Code:
```text
/plugin marketplace update uccif
/plugin update uccif@uccif
```
*Restart Claude Code after updating.*

### Antigravity CLI:
Re-run the install command:
```bash
agy plugin install https://github.com/phongng255/uccif/tree/main/plugins/uccif-antigravity
```

### Antigravity IDE:
Navigate to your project and re-run setup:
```bash
python3 /path/to/uccif/plugins/uccif/bin/uccif setup antigravity
```

---

## 6. Complete Uninstallation

To cleanly remove UCCIF without affecting your code:

### Step 6.1: Uninstall from your tool
- **Claude Code:** Run `/plugin uninstall uccif@uccif` in chat.
- **Antigravity CLI:** Run in terminal:
  ```bash
  agy plugin uninstall uccif
  ```
- **Antigravity IDE:** Run in your project directory:
  ```bash
  python3 /path/to/uccif/plugins/uccif/bin/uccif setup antigravity --remove
  ```
- **Gemini CLI:** Run:
  ```bash
  gemini extensions uninstall uccif
  ```

### Step 6.2: Uninstall CodeGraph (optional)
```bash
npm uninstall -g @colbymchenry/codegraph
```

### Step 6.3: Delete UCCIF project files
Remove any generated directories:
- `.claude/uccif/`
- `.codegraph/`
- `.agents/skills/` (the `<project>-map`, `-mod-*`, `-bugfix` skills)
- If you wish to keep your project notes, preserve `.claude/uccif/summary.md`.

---

## 7. Troubleshooting & Common Issues

| Symptom | Cause | Solution |
| :--- | :--- | :--- |
| `python3: command not found` or `python not found` | Python is missing or not in system PATH. | Install Python from python.org. On Windows, check **"Add Python to PATH"**. |
| `Error: install target must be a directory` with `agy plugin install` | Provided URL was malformed or incomplete. | Use the exact tree URL: `https://github.com/phongng255/uccif/tree/main/plugins/uccif-antigravity` or local path. |
| No token line after replies | Using Antigravity or token reporting disabled. | Antigravity hooks do not support trailing system messages. In Claude Code, run `/config` and enable `token_report`. |
| Gemini CLI login fails | Using an unpaid personal Google account. | Free Gemini CLI access ended June 18, 2026. Use **Antigravity CLI** (`agy`) instead. |
| `ModuleNotFoundError: No module named 'pytest'` | Python environment lacks test dependencies. | Run `python3 -m pip install pytest` or activate a virtualenv. |

---

## 8. Frequently Asked Questions (FAQ)

**Q: Does UCCIF send my source code to any external servers?**  
*A:* **Never.** All indexing and task memory execute 100% locally on your machine. UCCIF does not host external servers or transmit telemetry.

**Q: Will UCCIF modify or delete my codebase without permission?**  
*A:* **No.** Code changes are made exclusively by the AI assistant under your interactive supervision and approval. UCCIF only manages its own helper docs and indexes.

**Q: If teammates do not have UCCIF installed, will this break their workflow?**  
*A:* **Not at all.** The generated `AGENTS.md` and skill files are plain standard Markdown files. Any developer or tool can read them without UCCIF installed.
