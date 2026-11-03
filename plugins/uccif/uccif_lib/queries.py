"""Graph queries over the unified nodes/edges model (`uccif index query ...`).

Every answer is read-only, at most index.QUERY_LINES lines, and cites file:line.
"""

import re

from uccif_lib import index, vue_template
from uccif_lib.index import QUERY_LINES

GROUPS = {
    "store": ("calls_action", "reads_state", "uses_store"),
    "vue": ("renders", "passes_prop", "listens", "emits"),
    "css": ("uses_css_var", "defines_css_var", "uses_class"),
    "route": ("routes_to", "navigates_to"),
    "types": ("references_type",),
    "vars": ("reads", "writes"),
    "code": ("imports", "calls", "passes_callback", "uses_composable"),
}
ALL_KINDS = ("imports", "calls", "renders", "calls_action", "reads_state", "uses_store", "uses_composable",
             "routes_to", "navigates_to", "passes_callback", "uses_css_var", "defines_css_var", "uses_class",
             "references_type", "reads", "writes", "extends", "implements", "passes_prop", "listens", "emits",
             "tests", "co_changes", "re_exports", "contains")
VERB = {"imports": "imports", "calls": "calls", "renders": "renders", "calls_action": "calls store action",
        "reads_state": "reads store state", "uses_store": "uses store", "uses_composable": "uses composable",
        "routes_to": "routes to", "navigates_to": "navigates to", "passes_callback": "passes callback",
        "uses_css_var": "uses CSS variable", "defines_css_var": "sets CSS variable", "uses_class": "uses class",
        "references_type": "uses type", "reads": "reads", "writes": "writes", "extends": "extends",
        "implements": "implements", "passes_prop": "passes prop", "listens": "listens to", "emits": "emits",
        "tests": "tests", "co_changes": "changes with", "re_exports": "re-exports", "contains": "contains"}


def parse_kinds(spec):
    """'calls,store' -> ('calls', 'calls_action', ...). Raises ValueError naming unknown kinds."""
    if not spec:
        return None
    out, bad = [], []
    for part in (p.strip() for p in spec.split(",") if p.strip()):
        if part in GROUPS:
            out += GROUPS[part]
        elif part in ALL_KINDS:
            out.append(part)
        else:
            bad.append(part)
    if bad:
        raise ValueError("unknown kind(s): %s. Kinds: %s; groups: %s" % (
            ", ".join(bad), ", ".join(ALL_KINDS), ", ".join(sorted(GROUPS))))
    return tuple(dict.fromkeys(out))


def _caller(src_id, src_path):
    return src_id[len(src_path) + 1:] if src_id and src_id.startswith(src_path + "#") else None


def _short(node_id):
    name = node_id.split("#", 1)[-1]
    return re.sub(r"^(?:\w+\.)?(?:prop|emit|route|css-class):", "", name)


def _sections(head, sections, cap=6):
    """head lines + [(title, [items])], fitted into QUERY_LINES with '... +N more'."""
    lines = list(head)
    for i, (title, items) in enumerate(sections):
        if not items:
            continue
        left = len([s for s in sections[i + 1:] if s[1]])
        room = QUERY_LINES - len(lines) - 1 - left  # keep one line for each later section's title
        if room < 1:
            lines.append("%s: %d more not shown" % (title, len(items)))
            continue
        shown = items[:min(cap, room)]
        if len(items) > len(shown) and len(shown) > 1:
            shown = shown[:-1]
        lines.append(title + ":")
        lines.extend("  " + x for x in shown)
        if len(items) > len(shown):
            lines.append("  ... +%d more" % (len(items) - len(shown)))
    return lines[:QUERY_LINES]


def _conf_list(min_confidence):
    return index._conf_ok(min_confidence)


# ---- impact of a symbol --------------------------------------------------------------

def impact_symbol(project, name, depth=3, kinds=None, min_confidence=None):
    """What depends on a symbol: who uses it (any edge kind), then who uses those, level by level."""
    kinds = kinds or index.DEFAULT_KINDS
    depth = max(1, min(int(depth), index.MAX_DEPTH))
    con = index.connect(project, write=False)
    defs = con.execute("SELECT id, path, line, kind FROM nodes WHERE name=? AND kind<>'file' "
                       "ORDER BY kind='method', path LIMIT 5", (name,)).fetchall()
    if not defs:
        con.close()
        return ["%s is neither an indexed file nor a symbol name (use --symbol %s for fuzzy matches)." % (name, name)]
    auto = min_confidence is None
    levels, hidden = _walk(con, [d[0] for d in defs], depth, kinds, "extracted" if auto else min_confidence)
    if auto:
        if not levels:  # nothing certain: show the inferred picture instead
            levels, hidden = _walk(con, [d[0] for d in defs], depth, kinds, "inferred")
            note = " (inferred edges only)"
        else:
            more, _ = _walk(con, [d[0] for d in defs], depth, kinds, "inferred")
            extra = {r[1] for lv in more for r in lv} - {r[1] for lv in levels for r in lv}
            note = ""
            hidden = len(extra)
    else:
        note, hidden = "", 0
    ids = {d[0] for d in defs} | {r[0] for lv in levels for r in lv}
    tests = con.execute("SELECT DISTINCT src_path, line FROM edges WHERE kind='tests' AND dst_id IN %s "
                        "ORDER BY src_path, line" % index._in(list(ids)), list(ids)).fetchall()
    con.close()
    n_users = len({r[1] for lv in levels for r in lv})
    head = ["Impact of %s (depth %d): %d places in %d files%s" % (
        name, depth, sum(len(lv) for lv in levels), n_users, note)]
    head += ["  defined at %s:%d (%s)" % (p, ln, k) for _, p, ln, k in defs[:3]]
    if hidden:
        head.append("  +%d more files through inferred edges (--min-confidence inferred)" % hidden)
    sections = []
    for i, lv in enumerate(levels, 1):
        items = ["%s:%s  %s %s%s%s" % (sp, ln or "?", VERB.get(k, k), d or "", (" in " + c) if c else "",
                                       "  ~inferred" if conf == "inferred" else "")
                 for _sid, sp, ln, k, d, conf, c in lv]
        sections.append(("Level %d%s" % (i, " (direct)" if i == 1 else ""), items))
    sections.append(("Tests to run (%d)" % len(tests), ["%s:%d" % t for t in tests]))
    if not levels:
        head.append("  nothing uses it (within the index)")
    return _sections(head, sections, cap=10)


def _walk(con, start, depth, kinds, min_confidence):
    conf = _conf_list(min_confidence)
    seen, frontier, levels = set(start), list(start), []
    for _ in range(depth):
        rows = []
        for i in range(0, len(frontier), 200):
            chunk = frontier[i:i + 200]
            rows += con.execute(
                "SELECT src_id, src_path, line, kind, detail, confidence FROM edges WHERE dst_id IN %s AND kind IN %s "
                "AND confidence IN %s ORDER BY src_path, line" % (index._in(chunk), index._in(kinds), index._in(conf)),
                tuple(chunk) + tuple(kinds) + tuple(conf)).fetchall()
        level, nxt = [], []
        for sid, sp, ln, k, d, c in rows:
            if sid in seen:
                continue
            seen.add(sid)
            nxt.append(sid)
            level.append((sid, sp, ln, k, d, c, _caller(sid, sp)))
        if not level:
            break
        levels.append(level)
        frontier = nxt
        if len(seen) > index.MAX_FILES * 4:
            break
    return levels, 0


# ---- component / store / route / css var / cochange --------------------------------

def _find_nodes(con, kind, arg):
    rows = con.execute("SELECT id, name, path, line, detail, scope FROM nodes WHERE kind=?", (kind,)).fetchall()
    key = vue_template.norm(arg)
    exact = [r for r in rows if r[1] == arg]
    return exact or [r for r in rows if vue_template.norm(r[1]) == key]


def component(project, name):
    con = index.connect(project, write=False)
    hits = _find_nodes(con, "component", name)
    if not hits:
        con.close()
        return ["No component named %s in the index (try --symbol %s)." % (name, name)]
    cid, cname, path, line = hits[0][:4]
    q = con.execute
    parents = q("SELECT src_path, line, src_id, confidence FROM edges WHERE kind='renders' AND dst_id=? "
                "ORDER BY src_path, line", (cid,)).fetchall()
    children = q("SELECT detail, dst_path, line, kind FROM edges WHERE src_id=? AND kind IN ('renders','renders_ext') "
                 "ORDER BY line", (cid,)).fetchall()
    props = q("SELECT id, name, line FROM nodes WHERE path=? AND kind='prop' ORDER BY line", (path,)).fetchall()
    emits = q("SELECT id, name, line FROM nodes WHERE path=? AND kind='emit' ORDER BY line", (path,)).fetchall()
    routes = q("SELECT detail, src_path, line FROM edges WHERE kind='routes_to' AND dst_id=?", (cid,)).fetchall()
    uses = q("SELECT kind, dst_id, line, src_id FROM edges WHERE src_path=? AND kind IN "
             "('uses_store','uses_composable','calls_action','reads_state') ORDER BY line", (path,)).fetchall()

    def users(nid, kind):
        r = q("SELECT src_path, line FROM edges WHERE dst_id=? AND kind=? ORDER BY src_path, line", (nid, kind)).fetchall()
        return ("%d: %s" % (len(r), ", ".join("%s:%d" % x for x in r[:3]))) if r else "none"

    head = ["Component %s  %s:%d%s" % (cname, path, line, ("  (%d more with this name)" % (len(hits) - 1))
                                        if len(hits) > 1 else "")]
    sections = [
        ("Rendered by (%d)" % len(parents), ["%s:%d  %s%s" % (sp, ln, _short(sid), "  ~inferred" if c == "inferred"
                                                               else "") for sp, ln, sid, c in parents]),
        ("Renders (%d)" % len(children), ["<%s> :%d  %s" % (d, ln, dp or ("(external)" if k == "renders_ext"
                                                                          else "(unresolved)"))
                                          for d, dp, ln, k in children]),
        ("Props (%d)" % len(props), ["%s  :%d  passed by %s" % (n, ln, users(nid, "passes_prop"))
                                     for nid, n, ln in props]),
        ("Emits (%d)" % len(emits), ["%s  :%d  emitted %s; listened by %s" % (n, ln, users(nid, "emits"),
                                                                              users(nid, "listens"))
                                     for nid, n, ln in emits]),
        ("Routes", ["%s  (%s:%d)" % r for r in routes]),
        ("Stores / composables", sorted({"%s %s" % (VERB[k], _short(d)) for k, d, _, _ in uses if d})),
    ]
    con.close()
    return _sections(head, sections)


def store(project, name):
    con = index.connect(project, write=False)
    hits = _find_nodes(con, "store", name)
    if not hits:
        guess = "use%sStore" % (name[:1].upper() + name[1:])
        hits = _find_nodes(con, "store", guess)
    if not hits:
        con.close()
        return ["No Pinia store named %s in the index (stores are found with tree-sitter)." % name]
    sid, sname, path, line = hits[0][:4]
    members = con.execute("SELECT id, name, line, detail FROM nodes WHERE path=? AND scope=? AND kind='store_member' "
                          "ORDER BY detail, line", (path, sname)).fetchall()
    users = con.execute("SELECT DISTINCT src_path FROM edges WHERE dst_id=? AND kind='uses_store' ORDER BY src_path",
                        (sid,)).fetchall()
    head = ["Store %s  %s:%d  used in %d files%s" % (sname, path, line, len(users),
                                                     (": " + ", ".join(u[0] for u in users[:4])) if users else "")]
    by_kind = {}
    for mid, mname, mline, det in members:
        rows = con.execute("SELECT src_path, line, src_id FROM edges WHERE dst_id=? AND kind IN "
                           "('calls_action','reads_state') ORDER BY src_path, line", (mid,)).fetchall()
        who = ", ".join("%s:%d" % (sp, ln) for sp, ln, _ in rows[:3]) + (" +%d" % (len(rows) - 3) if len(rows) > 3 else "")
        by_kind.setdefault(det or "member", []).append("%s  :%d  %s" % (mname, mline, ("%d uses: %s" % (len(rows), who))
                                                                       if rows else "unused in the index"))
    con.close()
    sections = [("Actions", by_kind.get("action", [])), ("State", by_kind.get("state", [])),
                ("Getters", by_kind.get("getter", []))]
    return _sections(head, sections, cap=8)


def route(project, arg):
    con = index.connect(project, write=False)
    hits = con.execute("SELECT id, name, path, line, detail FROM nodes WHERE kind='route' AND (name=? OR detail=?)",
                       (arg, arg)).fetchall()
    if not hits:
        con.close()
        return ["No route %s (by path or name) in the index." % arg]
    lines = []
    sections = []
    for rid, rpath, path, line, rname in hits[:2]:
        lines.append("Route %s%s  %s:%d" % (rpath, (" (name: %s)" % rname) if rname else "", path, line))
        comp = con.execute("SELECT dst_path, confidence FROM edges WHERE src_id=? AND kind='routes_to'", (rid,)).fetchall()
        lines += ["  shows %s%s" % (c[0] or "(component not found)", "" if c[1] == "extracted" else "  ~" + c[1])
                  for c in comp]
        navs = con.execute("SELECT src_path, line, src_id, confidence, detail FROM edges WHERE dst_id=? AND "
                           "kind='navigates_to' ORDER BY src_path, line", (rid,)).fetchall()
        sections.append(("Opened from (%d)" % len(navs), ["%s:%d%s  -> %s%s" % (
            sp, ln, (" in " + _caller(sid, sp)) if _caller(sid, sp) else "", d, "  ~inferred" if c == "inferred" else "")
            for sp, ln, sid, c, d in navs]))
    con.close()
    return _sections(lines, sections, cap=12)


def css_var(project, name):
    name = name if name.startswith("--") else "--" + name  # `--css-var brand-color` works too
    con = index.connect(project, write=False)
    defs = con.execute("SELECT id, path, line FROM nodes WHERE kind='css_var' AND name=? ORDER BY path", (name,)).fetchall()
    ids = [d[0] for d in defs]
    users = con.execute("SELECT src_path, line, kind, src_id FROM edges WHERE kind IN ('uses_css_var','defines_css_var') "
                        "AND (dst_id IN %s OR (dst_id IS NULL AND detail=?)) ORDER BY src_path, line"
                        % index._in(ids or [""]), tuple(ids or [""]) + (name,)).fetchall()
    con.close()
    seen, rows = set(), []
    for sp, ln, k, sid in users:
        if (sp, ln, k) not in seen:
            seen.add((sp, ln, k))
            rows.append("%s:%d  %s%s" % (sp, ln, "sets it" if k == "defines_css_var" else "uses it",
                                         (" in " + _caller(sid, sp)) if _caller(sid, sp) else ""))
    head = ["CSS variable %s: %d definitions, used at %d places" % (name, len(defs), len(rows))]
    return _sections(head, [("Defined at", ["%s:%d" % (p, ln) for _, p, ln in defs]),
                            ("Used at (%d)" % len(rows), rows)], cap=20)


def cochange(project, path):
    con = index.connect(project, write=False)
    rel = index._norm(project, path)
    rows = con.execute("SELECT dst_path, detail FROM edges WHERE kind='co_changes' AND src_path=? "
                       "ORDER BY CAST(detail AS INTEGER) DESC, dst_path", (rel,)).fetchall()
    known = con.execute("SELECT 1 FROM files WHERE path=?", (rel,)).fetchone()
    con.close()
    if not known:
        return ["%s is not in the index." % rel]
    head = ["Files changed together with %s (last %d commits, inferred from history):" % (rel, index.COCHANGE_COMMITS)]
    if not rows:
        head.append("  none (needs 2+ shared commits covering 30% of either file's changes)")
    return _sections(head, [("Pairs (%d)" % len(rows), ["%s  [%s]" % r for r in rows])], cap=25)
