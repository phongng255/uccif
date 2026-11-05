# UCCIF guide

How to install UCCIF, what it does once installed, and what to do when something goes wrong. Every command can be copied and pasted. Vietnamese version: [HUONG-DAN.md](HUONG-DAN.md).

## 1. What UCCIF is

UCCIF is a plugin for AI coding tools. It does not change your code on its own. It gives the AI these things:

| Part | What it does | Where it lives |
|---|---|---|
| **Core rules** | Tell the AI to run commands itself, check evidence before concluding, ask before installing packages, deploying or pushing, and reply in your language | Loaded at the start of each session |
| **Code index (CodeGraph)** | The AI looks up functions, call paths and impact in an index instead of searching and reading file by file | `.codegraph/` |
| **Project skills** | A module map, a short bug-fix path, and up to 5 skills for the largest modules, generated from the index | `.claude/skills/` or `.agents/skills/` |
| **Task memory** | The first file edit opens a task. It survives turns and `/clear`, so the AI knows what is in progress | `.claude/uccif/.local/` |
| **Token line** | Real token counts read from the transcript, never estimated | Shown after each reply |

UCCIF never blocks the AI's commands: it reminds, it does not forbid. An open task closes by itself when you move to new work or after 24 hours idle.

## 2. What each tool supports

| Feature | Claude Code | Antigravity CLI (`agy`) | Antigravity IDE | Gemini CLI |
|---|---|---|---|---|
| Rules, skills, CodeGraph | Yes | Yes | Yes | Yes |
| Automatic hooks | Yes | Yes | **No** | Yes |
| Task opened when a file is edited | Yes, titled from your prompt | Yes, always titled "Code change" | **No** | Yes, titled from your prompt |
| Automatic indexing and skills | Yes | Yes | **No**, run by hand (section 3.3) | Yes |
| Token line | Yes | No | No | Yes |
| `#quick` | Yes | No | No | Yes |
| Reminder to use CodeGraph before searching | Yes | No | No | Yes |

The Gemini CLI support has only been checked by automated tests, not in a real session. Google stopped serving Gemini CLI for unpaid and Google One users on June 18, 2026. With a personal account, choose Antigravity CLI.

It is normal for `.agents/` to hold fewer files than `.claude/`. Both tools share `.claude/uccif/`, and files like `.cc-writes` belong to Claude Code itself.

## 3. Install

You need:

| Tool | Required? | Check with | Used for |
|---|---|---|---|
| Python 3.8 or later | Yes | `python3 --version` | Running UCCIF |
| Git | Yes | `git --version` | Identifying the project |
| Node.js and npm | Only for CodeGraph or language servers | `node --version` | Installing CodeGraph, pyright |

On Windows, Claude Code runs hooks through Git Bash, so install [Git for Windows](https://git-scm.com/download/win). CI runs on Windows, but UCCIF has not been tried in a real Claude Code session there.

### 3.1. Claude Code

In the Claude Code chat, type:

```text
/plugin marketplace add phongng255/uccif
/plugin install uccif@uccif
```

Restart Claude Code, then check from a terminal:

```bash
claude plugin list
```

The list must include `uccif`. Then go to section 3.5.

### 3.2. Antigravity CLI

```bash
agy plugin install https://github.com/phongng255/uccif/tree/main/plugins/uccif-antigravity
```

Use exactly this URL form. A bare repo URL, `#branch` or `--ref` installs the Claude plugin instead, and Antigravity skips its hooks.

Check:

```bash
agy plugin list
```

```text
Installed plugins:
- uccif (enabled, 1.2.0)
    Source:     antigravity
    Components: 3 skills, 1 rule, 1 MCP server, 1 hook
```

### 3.3. Antigravity IDE

The IDE has no hooks, so you run this by hand for each project. The commands below assume you installed the plugin in section 3.2. Otherwise use `plugins/uccif/bin/uccif` from a clone of this repository.

```bash
cd /path/to/your/project
```

```bash
~/.gemini/config/plugins/uccif/core/bin/uccif setup antigravity
```

Do not run this file with `python3 .../bin/uccif`: it is a shell script, and that fails with `SyntaxError`.

The output starts with the line below. `N` is the number of files written, and it can differ on later runs:

```text
Wrote N files under .agents/ for the Antigravity IDE.
```

This writes only `.agents/rules/uccif.md`, `.agents/mcp_config.json` and the 3 skills `codegraph`, `init` and `resume`. For the index and project skills, also run:

```bash
codegraph init --yes
```

```bash
~/.gemini/config/plugins/uccif/core/bin/uccif skills generate
```

Skills do not refresh by themselves in this mode. When the project's structure changes a lot, run `skills generate` again.

If you use both the `agy` plugin and `.agents/mcp_config.json`, CodeGraph's tools may appear twice. In that case keep only one declaration.

### 3.4. Gemini CLI (paid accounts only)

```bash
gemini extensions install https://github.com/phongng255/uccif.git
```

```bash
gemini extensions list
```

To update to the latest version (use `--all` instead of the name to update every extension), then reopen Gemini CLI:

```bash
gemini extensions update uccif
```

### 3.5. First time in a project

1. Open your AI tool in the project folder and ask anything.
2. If CodeGraph is missing, the AI asks once whether to install it. The wording varies, because the AI writes the question itself.
3. If you say **yes**, the AI installs the CLI, indexes the project and generates skills. Then restart the tool once to load the `codegraph_explore` tool.
4. If you say **no**, the AI searches with Grep and does not ask again in that project.

Once CodeGraph is on the machine, projects you open later are indexed and get their skills in the background.

To check, ask the AI: *"run uccif doctor"*. `OK` is fine, `WARN` is worth fixing, and `INFO` is for reference.

## 4. Daily use

Talk normally. You do not need to remember any `uccif` command:

| You want to | Just say |
|---|---|
| Understand a flow | "How does login work?" |
| Find code | "Where is the total price calculated?" |
| See what a change touches | "What breaks if I change this component's props?" |
| Fix a bug | "Checkout returns a 500, please fix it" |
| Resume work | "Continue yesterday's work" or "what was I doing?" |
| Check the hooks | "Did the hooks run today?" |
| Make a tiny edit without a task | Add `#quick` to the prompt (Claude Code, Gemini CLI) |

### Reading the token line

```text
🔢 Tokens
   This turn: 2.4k input (2.1k from cache), 320 output
   Session total: 48k
   Context now: 35k (18%)
```

| Part | Meaning |
|---|---|
| `This turn: ... input (... from cache)` | Input tokens this turn, and how many of them were read from cache |
| `output` | Tokens the AI produced this turn |
| `Session total` | Total tokens for the whole session |
| `Context now` | Context in use, and its share of the limit when known |

A hint is sometimes added on a last line:

| Hint | When | What to do |
|---|---|---|
| `💡 /clear recommended (task saved)` | Context at 80k or more, no open task | Type `/clear` |
| `💡 checkpoint, then /clear` | Context at 150k or more, task open | Ask the AI to save progress, then `/clear` |
| `💡 long session` | Session total at 3 million tokens or more | Consider a new session |

After `/clear`, the AI recovers what was saved in the task: its title, edited files, decisions and open issues. The chat itself is not kept, so ask the AI to record important decisions.

## 5. Options and extensions

Change options in Claude Code's `/config`. For Gemini CLI, use the extension's settings.

| Option | Default | Effect |
|---|---|---|
| `reply_language` | `vi` | The language the AI replies in |
| `token_report` | on | Shows the token line |
| `auto_setup` | on | Indexes and generates skills automatically when CodeGraph is present |

To add your own rules, create these files. UCCIF only reads them. At most 15 non-empty lines of each file are loaded.

| Scope | File |
|---|---|
| One project | `<project>/.claude/uccif/rules.md` |
| All projects | `~/.claude/uccif/rules.md` |

To add notes to a generated skill, write **inside** its `<!-- uccif:notes -->` block. Those notes survive every regeneration. If you edit outside the block, UCCIF skips that file until you use `--force`, which overwrites your edits outside the block.

## 6. What to commit

| File or folder | Solo | Team | Notes |
|---|---|---|---|
| `.codegraph/` | No | No | Per-machine index, kept out of git automatically |
| `.claude/uccif/.local/` | No | No | Per-machine tasks and state |
| `.agents/rules/uccif.md` | No | No | Holds your machine's absolute path |
| `.claude/uccif/summary.md`, `rules.md` | Optional | Yes | The project's purpose and conventions |
| `<project>-*` skills | Optional | Yes | Can be regenerated from the index |
| `AGENTS.md` | Optional | Yes | If it has a UCCIF block, the block points to `.claude/uccif/summary.md`, so commit both together |

Working alone, you can add `.claude/` and `.agents/` to `.gitignore`. If `.claude/` holds other files you want to share, ignore only the parts you need to.

## 7. Update

**Claude Code**, from a terminal:

```bash
claude plugin marketplace update uccif
```

```bash
claude plugin update uccif@uccif
```

Then **restart Claude Code**: the new version only applies after a restart. "Already up to date" means there is no newer version. The old version stays in the plugin cache for a while. That is normal, and it is no longer used.

A project's skills only refresh the next time you open the tool in that project.

**Antigravity CLI:**

```bash
agy plugin uninstall uccif
```

```bash
agy plugin install https://github.com/phongng255/uccif/tree/main/plugins/uccif-antigravity
```

**Antigravity IDE:** run `uccif setup antigravity` again in the project. Files you edited are kept, and the command reports what it skipped.

## 8. Uninstall

Remove it from the tool:

| Tool | Command |
|---|---|
| Claude Code | `claude plugin uninstall uccif@uccif` |
| Antigravity CLI | `agy plugin uninstall uccif` |
| Antigravity IDE | `uccif setup antigravity --remove`, run in the project and **before** removing the plugin. It deletes only files it wrote that you have not edited |
| Gemini CLI | `gemini extensions uninstall uccif` |

Clean up the project if you want to. Look before deleting:

- `.codegraph/`: safe to delete.
- `.claude/uccif/`: holds `summary.md` and `rules.md`, so keep it if you still need them.
- `.claude/skills/<project>-*` and `.agents/skills/<project>-*`: delete only the generated skills. Do not delete the whole `skills/` folder, which may hold your own skills.
- The `<!-- UCCIF:BEGIN -->` to `<!-- UCCIF:END -->` block in `AGENTS.md`, and the `@AGENTS.md` line in `CLAUDE.md` if you no longer use it.

Remove CodeGraph if no project needs it:

```bash
npm uninstall -g @colbymchenry/codegraph
```

## 9. Troubleshooting

The first step is always to ask the AI: *"run uccif doctor"*.

| Symptom | Cause | Fix |
|---|---|---|
| `SyntaxError` from `python3 .../bin/uccif` | `bin/uccif` is a shell script | Run the file directly, without `python3` |
| `python3: command not found` | Python is missing or not on PATH | Install it from [python.org](https://www.python.org/downloads/). On Windows, tick "Add Python to PATH" |
| Old behaviour after an update | The tool has not been restarted | Restart it. If that does not help, uninstall and reinstall the plugin |
| `.claude/skills` and `.agents/skills` have different counts | One side has skills from an older version, or that tool has not been opened since the update | Open that tool in the project so its skills regenerate |
| No token line | You use Antigravity, or `token_report` is off | Antigravity does not support it. In Claude Code, turn it on in `/config` |
| No `codegraph_explore` tool | No restart since installing, or the CLI is missing | Restart, then ask the AI to run `uccif codegraph` |
| CodeGraph's tools appear twice | The server is declared in two places | Keep one. Do not also run `codegraph install --target=claude` |
| No automatic tasks in Antigravity | You use the IDE, or the plugin came from the wrong URL | The IDE has no hooks. For the CLI, reinstall with the URL in section 3.2 |
| `doctor` reports `hook errors` | A hook failed, possibly only once | Ask the AI to run `uccif log hooks --only-errors`. Investigate only if it repeats |
| Cannot log in to Gemini CLI | The account is unpaid | Use Antigravity CLI |

## 10. FAQ

**Does UCCIF send my code anywhere?**
UCCIF itself has no server, and CodeGraph runs with telemetry off. Indexing and task memory stay on your machine. The AI tool you use still sends the code it reads to its provider, under that provider's policy.

**Does UCCIF change my code by itself?**
No. UCCIF writes only its own files: the index, skills, notes and task state. Code is changed by the AI, at your request and under your tool's permission system.

**How many tokens does UCCIF save?**
It depends on the project and how you work, so this guide gives no general figure. The token line shows your real numbers.

**What if teammates do not install UCCIF?**
Nothing breaks. `AGENTS.md` and the skills are plain Markdown files.

**Should I generate more skills?**
Usually not: every skill costs context in every session, and generated skills only repeat what the index can answer. If you have knowledge the code does not show, put it in a notes block or write your own skill.
