"""`uccif` command-line entry point. Subcommands are added module by module."""

import argparse
import json
import sys

from uccif_lib import SCHEMA_VERSION, __version__, detect, hooks, log, task, usage
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
    except task.TaskError as e:
        print("uccif: %s" % e, file=sys.stderr)
        return 1
    parser.print_help(sys.stderr)
    return 2
