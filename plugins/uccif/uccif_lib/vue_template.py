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

Template = namedtuple("Template", "tags calls elements reads")

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


def _expr_calls(expr, line, handler, out, reads=None):
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
        if n.type in ("call_expression", "new_expression"):
            ts_parse._js_call(n, sink)
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
    tags, calls, elements, reads = [], [], [], []
    stack = list(reversed(tpl.children[1:]))
    while stack:
        n = stack.pop()
        if n.type == "element":
            head = n.children[0] if n.children else None
            if head is not None and head.type in ("start_tag", "self_closing_tag"):
                tag, attrs = _tag(head), _attrs(head)
                line = head.start_point[0] + 1
                elements.append((tag, line, attrs))
                if is_component_tag(tag):
                    tags.append((tag, line))
                for name, value, aline in attrs:
                    if value is None:
                        continue
                    if name.startswith(("@", "v-on:")):
                        _expr_calls(value, aline, True, calls, reads)
                    elif name.startswith((":", "v-bind", "v-if", "v-else-if", "v-show", "v-model", "v-html",
                                          "v-text", "v-memo")) or name.startswith("v-slot"):
                        _expr_calls(value, aline, False, calls, reads)
                    elif name == "v-for":
                        m = _FOR.match(value)
                        _expr_calls(m.group(1) if m else value, aline, False, calls, reads)
            stack.extend(reversed(n.children[1:]))
        elif n.type == "text":
            base = n.start_point[0] + 1
            body = _txt(n)
            for m in _INTERP.finditer(body):
                _expr_calls(m.group(1), base + body.count("\n", 0, m.start(1)), False, calls, reads)
    return Template(tags, calls, elements, reads)


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
