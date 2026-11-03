"""Graph queries over the unified nodes/edges model (`uccif index query ...`).

Every answer is read-only, at most index.QUERY_LINES lines, and cites file:line.
"""

from uccif_lib import index
from uccif_lib.index import QUERY_LINES

GROUPS = {
    "code": ("imports", "calls", "passes_callback"),
    "types": ("references_type",),
    "vars": ("reads", "writes"),
}
ALL_KINDS = ("imports", "calls", "passes_callback", "references_type", "reads", "writes", "extends", "implements",
             "tests", "co_changes", "re_exports", "contains")
VERB = {"imports": "imports", "calls": "calls", "passes_callback": "passes callback", "references_type": "uses type",
        "reads": "reads", "writes": "writes", "extends": "extends", "implements": "implements", "tests": "tests",
        "co_changes": "changes with", "re_exports": "re-exports", "contains": "contains"}


def parse_kinds(spec):
    """'calls,vars' -> ('calls', 'reads', 'writes'). Raises ValueError naming unknown kinds."""
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


# ---- cochange ----------------------------------------------------------------------

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
