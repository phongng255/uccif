"""Vue single-file-component templates, parsed with the optional tree-sitter-html grammar.

`parse(text)` -> Template or None (grammar missing, no <template>, or a non-HTML template such
as `lang="pug"`). Everything is best effort: a template we cannot read just adds no edges.

Template.tags: [(tag as written, line)] for tags that may be components (PascalCase or
kebab-case, not plain HTML); Template.calls: [(name, object, line)] for functions the template
calls (`@click="save()"`, `@remove="remove"`, `{{ format(x) }}`, `:a="fn(b)"`, `v-if="ok()"`);
Template.elements keeps every element's attributes for later passes (props / emits).
"""

import re
from collections import namedtuple

from uccif_lib import ts_parse

Template = namedtuple("Template", "tags calls elements reads uses emits navs classes idents")

HTML_TAGS = frozenset("""a abbr address area article aside audio b base bdi bdo blockquote body br button canvas
caption cite code col colgroup data datalist dd del details dfn dialog div dl dt em embed fieldset figcaption
figure footer form h1 h2 h3 h4 h5 h6 head header hgroup hr html i iframe img input ins kbd label legend li link
main map mark menu meta meter nav noscript object ol optgroup option output p param picture pre progress q rp rt
ruby s samp script section select small source span strong style sub summary sup table tbody td template
textarea tfoot th thead time title tr track u ul var video wbr svg path circle rect line g text defs use
polygon polyline ellipse""".split())
# Components Vue / vue-router provide everywhere: known, not repo code.
VUE_BUILTINS = frozenset(("component", "slot", "template", "transition", "transitiongroup", "keepalive",
                          "teleport", "suspense", "routerlink", "routerview", "nuxtlink", "nuxtpage"))
_IDENT = re.compile(r"^[A-Za-z_$][\w$]*$")
_FOR = re.compile(r"^\s*\(?[^)]*?\)?\s+(?:in|of)\s+(.+)$", re.S)
_INTERP = re.compile(r"\{\{(.*?)\}\}", re.S)


def norm(tag):
    """Comparable form of a component name: `expense-item`, `ExpenseItem`, `expenseItem` match."""
    return tag.replace("-", "").replace("_", "").lower()


def is_component_tag(tag):
    if tag in HTML_TAGS:
        return False
    return "-" in tag or tag[:1].isupper() or norm(tag) in VUE_BUILTINS


def _txt(n):
    return n.text.decode("utf-8", errors="replace") if n is not None else ""


def _expr_classes(value):
    """Class names a `:class` expression can produce: string literals, object keys, array items."""
    parser = ts_parse._parser("tsx")
    if parser is None:
        return []
    root = parser.parse(("(" + value + ")").encode("utf-8")).root_node
    out = []
    for n in ts_parse._walk(root):
        if n.type == "string_fragment":
            out += n.text.decode("utf-8", errors="replace").split()
        elif n.type == "pair":
            k = n.child_by_field_name("key")
            if k is not None and k.type == "property_identifier":
                out.append(_txt(k))
        elif n.type == "shorthand_property_identifier" and n.parent is not None and n.parent.type == "object":
            out.append(_txt(n))
    return [c for c in out if re.match(r"^-?[_a-zA-Z][\w-]*$", c)]


def _expr_target(value):
    """Route target of a `:to="..."` expression: ('path'|'name', value, dynamic) or None."""
    parser = ts_parse._parser("tsx")
    if parser is None:
        return None
    root = parser.parse(("(" + value + ")").encode("utf-8")).root_node
    stmt = root.children[0] if root.children else None
    return ts_parse.route_target(stmt.children[0]) if stmt is not None and stmt.children else None


def _expr_calls(expr, line, handler, out, reads=None, emits=None, navs=None, idents=None):
    """Functions called in a template expression. `handler`: an event handler, where a bare
    identifier (`@remove="remove"`) or member (`@x="a.b"`) is itself a call."""
    expr = expr.strip()
    if not expr:
        return
    if handler and _IDENT.match(expr):
        out.append((expr, None, line))
        return
    parser = ts_parse._parser("tsx")
    if parser is None:
        return
    src = expr if handler else "(" + expr + ")"
    tree = parser.parse(src.encode("utf-8"))
    sink = []
    for n in ts_parse._walk(tree.root_node):
        if n.type == "identifier" and idents is not None:
            rw = ts_parse._ident_use(n)
            if rw and not _txt(n).startswith("$"):
                idents.append((_txt(n), rw, line + n.start_point[0]))
        if n.type in ("call_expression", "new_expression"):
            ts_parse._js_call(n, sink)
            fn = n.child_by_field_name("function")
            if navs is not None and fn is not None and fn.type == "member_expression" and _txt(
                    fn.child_by_field_name("object")) in ("$router", "router") and _txt(
                    fn.child_by_field_name("property")) in ("push", "replace"):
                args = n.child_by_field_name("arguments")
                tgt = ts_parse.route_target(next((c for c in (args.children if args is not None else [])
                                                  if c.type not in ("(", ")", ",")), None))
                if tgt:
                    navs.append((tgt[0], tgt[1], tgt[2], line + n.start_point[0]))
            if emits is not None and fn is not None and _txt(fn) in ("$emit", "emit"):
                args = n.child_by_field_name("arguments")
                first = next((c for c in (args.children if args is not None else [])
                              if c.type not in ("(", ")", ",")), None)
                ev = ts_parse._string_value(first)
                if ev:
                    emits.append((ev, line + n.start_point[0]))
        elif n.type == "member_expression" and reads is not None:  # obj.prop that is not a call
            o, prop, par = n.child_by_field_name("object"), n.child_by_field_name("property"), n.parent
            if o is not None and o.type == "identifier" and prop is not None and not (
                    par is not None and par.type == "call_expression" and par.child_by_field_name("function") == n):
                reads.append((_txt(o), _txt(prop), line + n.start_point[0]))
    for _caller, name, obj, ln in sink:
        if not name.startswith("$"):  # $emit, $router ...: Vue's own, not repo functions
            out.append((name, obj, line + ln - 1))


def parse(text):
    parser = ts_parse._parser("html") if ts_parse.html_available() else None
    if parser is None or "<template" not in text:
        return None
    try:
        root = parser.parse(text.encode("utf-8")).root_node
    except Exception:
        return None
    tpl = next((c for c in root.children if c.type == "element" and c.children
                and c.children[0].type == "start_tag" and _tag(c.children[0]) == "template"), None)
    if tpl is None:
        return None
    for a in _attrs(tpl.children[0]):
        if a[0] == "lang" and a[1] not in ("html", ""):
            return None
    tags, calls, elements, reads, uses, emits, navs, classes, idents = [], [], [], [], [], [], [], [], []
    stack = list(reversed(tpl.children[1:]))
    while stack:
        n = stack.pop()
        if n.type == "element":
            head = n.children[0] if n.children else None
            if head is not None and head.type in ("start_tag", "self_closing_tag"):
                tag, attrs = _tag(head), _attrs(head)
                line = head.start_point[0] + 1
                elements.append((tag, line, attrs))
                for an, av, al in attrs:
                    if an.startswith("v-model") and av and _IDENT.match(av.strip()):
                        idents.append((av.strip(), "w", al))
                    if an == "class" and av:
                        classes += [(c, al) for c in av.split() if re.match(r"^-?[_a-zA-Z][\w-]*$", c)]
                    elif an in (":class", "v-bind:class") and av:
                        classes += [(c, al) for c in _expr_classes(av)]
                if is_component_tag(tag):
                    tags.append((tag, line))
                    uses += [(tag, line, k, nm, al) for k, nm, al in _tag_uses(attrs)]
                    if norm(tag) in ("routerlink", "nuxtlink"):
                        for an, av, al in attrs:
                            if an == "to" and av:
                                navs.append(("path", av, False, al))
                            elif an in (":to", "v-bind:to") and av:
                                tgt = _expr_target(av)
                                if tgt:
                                    navs.append((tgt[0], tgt[1], tgt[2], al))
                for name, value, aline in attrs:
                    if value is None:
                        continue
                    if name.startswith(("@", "v-on:")):
                        _expr_calls(value, aline, True, calls, reads, emits, navs, idents)
                    elif name.startswith((":", "v-bind", "v-if", "v-else-if", "v-show", "v-model", "v-html",
                                          "v-text", "v-memo")) or name.startswith("v-slot"):
                        _expr_calls(value, aline, False, calls, reads, emits, navs, idents)
                    elif name == "v-for":
                        m = _FOR.match(value)
                        _expr_calls(m.group(1) if m else value, aline, False, calls, reads, emits, navs, idents)
            stack.extend(reversed(n.children[1:]))
        elif n.type == "text":
            base = n.start_point[0] + 1
            body = _txt(n)
            for m in _INTERP.finditer(body):
                _expr_calls(m.group(1), base + body.count("\n", 0, m.start(1)), False, calls, reads, emits, navs, idents)
    # v-for aliases and slot props are template locals: they shadow script variables of the same name
    local = set()
    for _t, _l, attrs in elements:
        for an, av, _al in attrs:
            if av and an == "v-for":
                m = re.match(r"^\s*\(?([^)]*?)\)?\s+(?:in|of)\s", av)
                if m:
                    local |= set(re.findall(r"[A-Za-z_$][\w$]*", m.group(1)))
            elif av and (an.startswith("v-slot") or an.startswith("#") or an == "slot-scope"):
                local |= set(re.findall(r"[A-Za-z_$][\w$]*", av))
    idents = [i for i in idents if i[0] not in local]
    return Template(tags, calls, elements, reads, uses, emits, navs, classes, idents)


_NOT_PROPS = frozenset(("class", "style", "key", "ref", "is", "slot", "v-slot", "id"))


def _tag_uses(attrs):
    """[(kind, name, line)] for what a parent passes to a component tag: kind 'prop' for `:x=`,
    `v-bind:x=` and plain `x="..."`, 'event' for `@x=` / `v-on:x=`; `v-model` is both."""
    out = []
    for name, value, line in attrs:
        if name.startswith("@") or name.startswith("v-on:"):
            out.append(("event", name.split(":", 1)[-1].lstrip("@").split(".")[0], line))
        elif name == "v-model" or name.startswith("v-model:"):
            arg = name.split(":", 1)[1].split(".")[0] if ":" in name else "modelValue"
            out += [("prop", arg, line), ("event", "update:" + arg, line)]
        elif name.startswith(":") or name.startswith("v-bind:"):
            arg = name.split(":", 1)[1].split(".")[0]
            if arg and arg not in _NOT_PROPS:
                out.append(("prop", arg, line))
        elif not name.startswith("v-") and name not in _NOT_PROPS and not name.startswith("#"):
            out.append(("prop", name, line))
    return out


def _tag(node):
    t = next((c for c in node.children if c.type == "tag_name"), None)
    return _txt(t)


def _attrs(node):
    out = []
    for a in node.children:
        if a.type != "attribute":
            continue
        name = next((c for c in a.children if c.type == "attribute_name"), None)
        val = next((c for c in a.children if c.type in ("quoted_attribute_value", "attribute_value")), None)
        if val is not None and val.type == "quoted_attribute_value":
            inner = next((c for c in val.children if c.type == "attribute_value"), None)
            value = _txt(inner) if inner is not None else ""
            line = inner.start_point[0] + 1 if inner is not None else a.start_point[0] + 1
        else:
            value, line = (_txt(val) if val is not None else None), a.start_point[0] + 1
        out.append((_txt(name), value, line))
    return out
