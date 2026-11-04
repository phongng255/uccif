"""`uccif` command-line entry point. Subcommands are added module by module."""

import argparse
import json
import os
import sys

from uccif_lib import SCHEMA_VERSION, __version__, codegraph, detect, drift, hooks, log, task, usage
from uccif_lib.paths import data_root_source, resolve_project


def build_parser():
    p = argparse.ArgumentParser(prog="uccif", description="UCCIF core CLI")
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("version", help="print framework and schema version")
    sub.add_parser("where", help="print project root, data dir and docs dir")
    sub.add_parser("detect", help="mechanical project survey as JSON (read-only)")
    sub.add_parser("doctor", help="check the UCCIF install for this project")

    t = sub.add_parser("task", help="current-task memory").add_subparsers(dest="action")
    s = t.add_parser("start")
    s.add_argument("title")
    s.add_argument("--type", required=True, choices=task.TYPES)
    s.add_argument("--goal", default="")
    s.add_argument("--rewrite", action="store_true")
    t.add_parser("show")
    c = t.add_parser("checkpoint")
    c.add_argument("--decision", action="append")
    c.add_argument("--issue", action="append")
    c.add_argument("--test", action="append")
    c.add_argument("--file", action="append")
    c.add_argument("--next")
    c.add_argument("--goal")
    c.add_argument("--modules")
    c.add_argument("--set", action="append", metavar="FIELD=VALUE")
    cl = t.add_parser("close")
    cl.add_argument("--decision", action="append")
    cl.add_argument("--issue", action="append")
    cl.add_argument("--no-findings", action="store_true")

    cgp = sub.add_parser("codegraph", help="CodeGraph state for this project as JSON (cli, indexed, mcp)")
    cgp.add_argument("action", nargs="?", choices=("decline",),
                     help="decline: the user does not want CodeGraph; stop offering it")
    sk = sub.add_parser("skills", help="project skills generated from the CodeGraph index").add_subparsers(dest="action")
    sg = sk.add_parser("generate", help="write/refresh .claude/skills/<project>-map, -bugfix, -mod-*")
    sg.add_argument("--force", action="store_true", help="also overwrite generated files you edited")
    sg.add_argument("--dry-run", action="store_true", help="show what would change, write nothing")
    sk.add_parser("list", help="generated skills present in .claude/skills/")

    dr = sub.add_parser("drift", help="structural changes that make docs stale").add_subparsers(dest="action")
    dr.add_parser("check")
    dr.add_parser("show")
    dr.add_parser("ack", help="docs updated: store the current shape")

    sub.add_parser("maintain", help="background upkeep: drift check")

    cm = sub.add_parser("claude-md", help="CLAUDE.md UCCIF block").add_subparsers(dest="action")
    cw = cm.add_parser("write", help="read the block from stdin: create CLAUDE.md, or append the block "
                                     "when it has none; replace an existing block only with --replace")
    cw.add_argument("--replace", action="store_true", help="overwrite the existing UCCIF block")
    cw.add_argument("--verified", default="", metavar="PURPOSES",
                    help="comma list of commands you ran successfully (e.g. test,build); the others "
                         "are marked (unverified)")

    sm = sub.add_parser("summary", help=".claude/uccif/summary.md").add_subparsers(dest="action")
    sw = sm.add_parser("write", help="read summary.md (<= 20 lines) from stdin and store the drift baseline")
    sw.add_argument("--replace", action="store_true", help="overwrite an existing summary.md")

    h = sub.add_parser("hook", help="run a hook handler (reads hook JSON on stdin)")
    h.add_argument("event")

    u = sub.add_parser("usage", help="real token usage from a transcript")
    u.add_argument("scope", choices=("turn", "session"))
    u.add_argument("--transcript", required=True)

    lg = sub.add_parser("log", help="view logs").add_subparsers(dest="action")
    lh = lg.add_parser("hooks")
    lh.add_argument("--last", type=int, default=40)
    lh.add_argument("--today", action="store_true")
    lh.add_argument("--event")
    lh.add_argument("--only-blocks", action="store_true")
    lh.add_argument("--only-errors", action="store_true")
    ls = lg.add_parser("sessions")
    ls.add_argument("--days", type=int, default=1)
    lp = lg.add_parser("prune")
    lp.add_argument("--days", type=int, default=30)
    return p


def _log_cmd(args):
    proj = resolve_project()
    if args.action == "hooks":
        lines = log.show_hooks(proj, last=args.last, today=args.today, event=args.event,
                               only_blocks=args.only_blocks, only_errors=args.only_errors)
    elif args.action == "sessions":
        lines = log.show_sessions(proj, days=args.days)
    elif args.action == "prune":
        lines = ["Removed %d log lines older than %d days." % (log.prune(proj, args.days), args.days)]
    else:
        return 2
    print("\n".join(lines))
    return 0


def _drift_cmd(args):
    proj = resolve_project()
    if args.action == "check":
        items = drift.check(proj)
    elif args.action == "show":
        items = drift.pending(proj)
    elif args.action == "ack":
        drift.ack(proj)
        print("Drift acknowledged; current project shape stored.")
        return 0
    else:
        return 2
    print("\n".join(items) if items else "No drift.")
    return 0


BEGIN, END = "<!-- UCCIF:BEGIN -->", "<!-- UCCIF:END -->"


MAX_BLOCK_LINES = 15
CMD_ORDER = ("build", "test", "lint", "dev", "run", "start", "typecheck")


def build_block(project, desc, verified=()):
    """The CLAUDE.md block, composed here so it stays small and has one source: 2-3 description
    lines from Claude, commands from the manifests, one pointer to the generated map skill."""
    from pathlib import Path
    from uccif_lib import skillgen, stack
    name = Path(project.root).name
    out = [BEGIN, "## %s" % name] + [l.strip() for l in desc.splitlines() if l.strip()][:3]
    cmds = dict(reversed(stack.commands(project.root)))
    shown = ["%s `%s`%s" % (k, cmds[k], "" if k in verified else " (unverified)")
             for k in CMD_ORDER if k in cmds][:4]
    if shown:
        out.append("Commands: " + " · ".join(shown))
    maps = [n for n in skillgen.generated(project) if n.endswith("-map")]
    ptr = "Code map: skill `%s` (modules, entry points, how to look code up)." % maps[0] if maps else ""
    if (project.docs_dir / "summary.md").exists():
        ptr += " Purpose, conventions, external services: `.claude/uccif/summary.md`."
    if ptr.strip():
        out.append(ptr.strip())
    return "\n".join(out + [END])


def _claude_md_cmd(args):
    from pathlib import Path
    from uccif_lib.paths import write_text_atomic
    proj = resolve_project()
    body = sys.stdin.read().strip()
    if not body:
        print("uccif: empty block on stdin", file=sys.stderr)
        return 1
    if BEGIN in body and END in body:  # a complete block: used as given
        body = body[body.index(BEGIN):body.index(END) + len(END)]
    else:  # 1-3 description lines: the command composes the rest
        verified = {v.strip() for v in (args.verified or "").split(",") if v.strip()}
        body = build_block(proj, body, verified)
    if len(body.splitlines()) > MAX_BLOCK_LINES:
        print("uccif: block has %d lines, max %d. Shorten it." % (len(body.splitlines()), MAX_BLOCK_LINES),
              file=sys.stderr)
        return 1
    path = Path(proj.root) / "CLAUDE.md"
    if path.is_symlink():  # e.g. CLAUDE.md -> AGENTS.md: edit the target, keep the link
        path = Path(os.path.realpath(str(path)))
    try:
        old = path.read_text(encoding="utf-8")
    except OSError:
        old = None
    if old is None:
        new, what = body + "\n", "created"
    elif BEGIN in old and END in old:
        if not args.replace:
            print("CLAUDE.md already has a UCCIF block: show the diff, ask, then rerun with --replace.")
            return 3
        i, j = old.index(BEGIN), old.index(END) + len(END)
        new, what = old[:i] + body + old[j:], "block replaced in"
    else:  # appended at the end: the user's own text above is never touched
        new, what = old.rstrip("\n") + ("\n\n" if old.strip() else "") + body + "\n", "block appended to"
    write_text_atomic(path, new)
    print("%s %s" % (what, path))
    return 0


MAX_SUMMARY_LINES = 20


def _summary_cmd(args):
    """Written through Bash on purpose: Claude Code treats a Write/Edit under .claude/ as a
    sensitive file and asks every time."""
    from uccif_lib.paths import write_text_atomic
    proj = resolve_project()
    body = sys.stdin.read().strip()
    lines = body.splitlines()
    if not body:
        print("uccif: empty summary on stdin", file=sys.stderr)
        return 1
    if len(lines) > MAX_SUMMARY_LINES:
        print("uccif: summary has %d lines, max %d. Keep only what the graph cannot know."
              % (len(lines), MAX_SUMMARY_LINES), file=sys.stderr)
        return 1
    path = proj.docs_dir / "summary.md"
    if path.exists() and not args.replace:
        print("summary.md exists: merge your lines into its text, then rerun with --replace.")
        return 3
    path.parent.mkdir(parents=True, exist_ok=True)
    write_text_atomic(path, body + "\n")
    drift.ack(proj)
    print("wrote %s (%d lines); drift baseline stored" % (path, len(lines)))
    return 0


def maintain():
    """Background upkeep run by hooks: drift check; with auto_setup on, index the project with
    CodeGraph when its CLI is installed and refresh the generated project skills when the
    project's shape changed. CodeGraph keeps its own index in sync after that."""
    proj = resolve_project()
    drift.check(proj)
    if hooks.options()["auto_setup"]:
        from uccif_lib import skillgen
        codegraph.auto_init(proj)
        skillgen.auto(proj)
    return 0


def _skills_cmd(args):
    from uccif_lib import skillgen
    proj = resolve_project()
    if args.action == "list":
        names = skillgen.generated(proj)
        print("\n".join(names) if names else "No generated project skills yet (`uccif skills generate`).")
        return 0
    try:
        res = skillgen.generate(proj, force=args.force, dry_run=args.dry_run)
    except skillgen.NoIndex as e:
        print("Cannot generate skills: %s. Run the uccif:codegraph skill first." % e)
        return 1
    print("\n".join(skillgen.report(res)))
    return 0


def _task_cmd(args):
    proj = resolve_project()
    if args.action == "start":
        tk = task.start(proj, args.title, args.type, goal=args.goal, rewrite=args.rewrite)
        print("Started %s: %s" % (tk["id"], tk["title"]))
    elif args.action == "show":
        tk = task.load_current(proj)
        if not tk or tk.get("status") == "done":
            print("No open task.")
        else:
            sys.stdout.write(task.render(tk))
    elif args.action == "checkpoint":
        tk = task.checkpoint(
            proj, decisions=args.decision, issues=args.issue, tests=args.test,
            files=args.file, sets=args.set,
            next=args.next, goal=args.goal, modules=args.modules,
        )
        print("Checkpoint saved for %s." % tk["id"])
    elif args.action == "close":
        tk = task.close(proj, decisions=args.decision, issues=args.issue,
                        no_findings=args.no_findings)
        print("Closed %s." % tk["id"])
    else:
        return 2
    return 0


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.cmd == "hook":
        return hooks.run(args.event)  # never raises, always 0
    try:
        if args.cmd == "version":
            print("uccif %s (schema %d)" % (__version__, SCHEMA_VERSION))
            return 0
        if args.cmd == "where":
            proj = resolve_project()
            print("project:  %s" % proj.root)
            print("key:      %s" % proj.key)
            print("data:     %s" % proj.data_dir)
            print("docs:     %s" % proj.docs_dir)
            print("commit:   %s" % (proj.root_commit or "-"))
            print("source:   %s" % data_root_source()[1])
            if proj.renamed_from:
                print("moved from: %s" % proj.renamed_from)
            return 0
        if args.cmd == "detect":
            print(json.dumps(detect.detect(resolve_project()), ensure_ascii=False, indent=1))
            return 0
        if args.cmd == "doctor":
            ok, lines = detect.doctor(resolve_project())
            print("\n".join(lines))
            return 0 if ok else 1
        if args.cmd == "task" and args.action:
            return _task_cmd(args)
        if args.cmd == "usage":
            s = usage.summarize(args.transcript)
            if args.scope == "session" and s:
                print("Session: in %s · out %s · %d turns · Ctx %s" % (
                    usage.fmt(s["session"]["in"]), usage.fmt(s["session"]["output_tokens"]),
                    s["turns"], usage.fmt(s["ctx"])))
            else:
                print(usage.token_line(s))
            return 0
        if args.cmd == "log" and args.action:
            return _log_cmd(args)
        if args.cmd == "skills" and args.action:
            return _skills_cmd(args)
        if args.cmd == "codegraph":
            proj = resolve_project()
            if args.action == "decline":
                codegraph.decline(proj)
                print("CodeGraph offer declined for this project.")
                return 0
            st = dict(codegraph.state(proj), gitignored=codegraph.gitignored(proj), package=codegraph.PACKAGE)
            print(json.dumps(st, indent=1))
            return 0
        if args.cmd == "drift" and args.action:
            return _drift_cmd(args)
        if args.cmd == "maintain":
            return maintain()
        if args.cmd == "summary" and args.action:
            return _summary_cmd(args)
        if args.cmd == "claude-md" and args.action:
            return _claude_md_cmd(args)
    except task.TaskError as e:
        print("uccif: %s" % e, file=sys.stderr)
        return 1
    parser.print_help(sys.stderr)
    return 2
