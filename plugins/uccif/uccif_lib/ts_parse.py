"""Optional tree-sitter parsing for the code index.

Everything here is best-effort: if `tree-sitter` or a grammar package is not installed
(or UCCIF_NO_TREE_SITTER is set), `parse()` returns None and the index falls back to
universal-ctags, then regexes. UCCIF never installs anything; `uccif doctor` only reports.

Optional packages: tree-sitter, tree-sitter-javascript, tree-sitter-typescript,
tree-sitter-python.
"""

import os
import re

_CACHE = {}
_FAMILY_GRAMMAR = {"typescript": "ts", "tsx": "tsx", "javascript": "tsx", "vue": "tsx", "svelte": "tsx",
                   "python": "python"}
_CONST_RE = re.compile(r"^[A-Z][A-Z0-9_]{2,}$")
_MAX_CALLS = 1500
_FN_VALUES = ("arrow_function", "function_expression", "function", "generator_function")
KEYWORD_CALLS = {"require", "import", "super", "if", "for", "while", "switch", "catch", "return",
                 "function", "constructor", "typeof", "await", "defineProps", "defineEmits",
                 "defineExpose", "withDefaults"}
_CLASS_NODES = ("class_declaration", "abstract_class_declaration", "class")


def disabled():
    return bool(os.environ.get("UCCIF_NO_TREE_SITTER"))


def _parser(grammar):
    if grammar in _CACHE:
        return _CACHE[grammar]
    parser = None
    try:
        import tree_sitter
        if grammar == "python":
            import tree_sitter_python as mod
            lang = mod.language()
        elif grammar == "html":
            import tree_sitter_html as mod
            lang = mod.language()
        else:
            import tree_sitter_typescript as mod
            lang = mod.language_typescript() if grammar == "ts" else mod.language_tsx()
        parser = tree_sitter.Parser(tree_sitter.Language(lang))
    except Exception:  # ImportError, or an ABI/API mismatch between the packages
        parser = None
    _CACHE[grammar] = parser
    return parser


def availability():
    """{'typescript': bool, 'python': bool}; False everywhere when disabled."""
    if disabled():
        return {"typescript": False, "python": False}
    return {"typescript": bool(_parser("tsx")), "python": bool(_parser("python"))}


def html_available():
    """Is the optional tree-sitter-html grammar importable (Vue template parsing)?"""
    return not disabled() and bool(_parser("html"))


def grammar_for(rel, lang):
    if lang == "python":
        return "python"
    if lang in ("typescript", "javascript", "vue", "svelte"):
        return "ts" if rel.endswith((".ts", ".mts", ".cts")) else "tsx"
    return None


def _txt(node):
    return node.text.decode("utf-8", errors="replace") if node is not None and node.text else ""


def _walk(root):
    stack = [root]
    while stack:
        n = stack.pop()
        yield n
        stack.extend(reversed(n.children))


def parse(text, rel, lang):
    """-> (symbols, imports, calls, bindings, import_lines, heritage, members, origins, reads) or None.
    members: [(store variable, member, "state"|"getter"|"action")] of Pinia stores (also in
    symbols as kind store_member with scope = the store variable); origins: where local variables
    come from, [(enclosing function, "call"|"new", callee, aliased variable, [(local, member or
    None)], line)] for `const s = useStore()`, `const {a, b: c} = useStore()`, `const x = new Foo()`,
    `const {a} = storeToRefs(s)`; reads: [(enclosing function, object variable, property, line)]
    for `obj.prop` that is not a call. Props and emits declared by defineProps / defineEmits (script
    setup, type or runtime form) or `props:` / `emits:` of an options component are symbols of kind
    prop / emit; emit_calls (tenth item): [(enclosing function, event, line)] for `emit('event')`;
    navs: [(enclosing function, "path"|"name", value, dynamic, line)] for `router.push/replace(...)`;
    routes: [(full path, route name, ("ident", x) | ("import", module) | None, line)] of router configs
    (also symbols of kind route, with the route name in members); callbacks (13th):
    [(enclosing function, name, "this" | None, line)] for identifiers passed as call arguments.
    heritage: [(class or interface name, base name as written, "extends"|"implements", line)];
    a dotted base keeps its dots (`mod.Base`), generic arguments are dropped.
    symbols: [(name, kind, line, scope)]; imports: [raw module strings];
    calls: [(caller, callee, object, line)] where caller is the enclosing function/method
    ("Class.method", or None at top level) and object is the receiver identifier ("this",
    a local name) when the call is `obj.callee()`; bindings: {local name: (raw module, name
    in that module)} with name "*" for namespace imports and "default" for default imports;
    import_lines: {raw module string: line of its first import}.
    `text` must already have non-script parts of .vue/.svelte blanked (line numbers kept)."""
    if disabled():
        return None
    grammar = grammar_for(rel, lang)
    parser = _parser(grammar) if grammar else None
    if parser is None:
        return None
    try:
        tree = parser.parse(text.encode("utf-8"))
        if grammar == "python":
            return _python(tree.root_node)
        return _js(tree.root_node)
    except Exception:
        return None


# ---- JavaScript / TypeScript -----------------------------------------------------

def _js_caller(n):
    """Name of the function/method enclosing node `n` ("Class.method"), or None at top level."""
    p = n.parent
    while p is not None:
        t = p.type
        if t in ("function_declaration", "generator_function_declaration"):
            return _txt(p.child_by_field_name("name")) or None
        if t in ("method_definition", "public_field_definition", "field_definition"):
            name = _txt(p.child_by_field_name("name"))
            q = p.parent.parent if p.parent is not None else None  # class_body -> class
            cls = _txt(q.child_by_field_name("name")) if q is not None and q.type in _CLASS_NODES else ""
            return (cls + "." + name) if cls and name else (name or None)
        if t == "variable_declarator":
            val = p.child_by_field_name("value")
            if val is not None and val.type in _FN_VALUES:
                return _txt(p.child_by_field_name("name")) or None
        p = p.parent
    return None


def _js_call(n, calls):
    fn = n.child_by_field_name("function" if n.type == "call_expression" else "constructor")
    if fn is None or len(calls) >= _MAX_CALLS:
        return
    obj = None
    if fn.type == "identifier":
        name = _txt(fn)
    elif fn.type == "member_expression":
        name = _txt(fn.child_by_field_name("property"))
        o = fn.child_by_field_name("object")
        if o is not None and o.type in ("identifier", "this"):
            obj = _txt(o)
    else:
        return
    if name and name not in KEYWORD_CALLS:
        calls.append((_js_caller(n), name, obj, n.start_point[0] + 1))


def _obj_keys(obj):
    """[(name, line)] of an object literal's keys / methods / shorthand properties."""
    keys = []
    for c in (obj.children if obj is not None else []):
        if c.type == "pair":
            k = c.child_by_field_name("key")
            name = _txt(k).strip("'\"`") if k is not None else ""
        elif c.type == "method_definition":
            name = _txt(c.child_by_field_name("name"))
        elif c.type == "shorthand_property_identifier":
            name = _txt(c)
        else:
            continue
        if name:
            keys.append((name, c.start_point[0] + 1))
    return keys


def _returned_object(fn):
    """The object a function / arrow returns, if it is a literal (`() => ({...})`, `return {...}`)."""
    if fn is None:
        return None
    body = fn.child_by_field_name("body")
    if body is None:
        return None
    if body.type == "parenthesized_expression":
        return next((c for c in body.children if c.type == "object"), None)
    if body.type == "statement_block":
        for c in body.children:
            if c.type == "return_statement":
                return next((x for x in c.children if x.type == "object"), None)
    return None


def _pinia_members(call, store, syms, members):
    """Members of `defineStore(id, options | setup)`: state / getters / actions, or the names a setup
    store returns, classified by how each is declared (ref -> state, computed -> getter, function -> action)."""
    args = call.child_by_field_name("arguments")
    if args is None:
        return
    rest = [c for c in args.children if c.type not in ("(", ")", ",")][1:]
    if not rest:
        return
    spec = rest[0]
    found = []
    if spec.type == "object":
        for c in spec.children:
            key = (_txt(c.child_by_field_name("key" if c.type == "pair" else "name")).strip("'\"")
                   if c.type in ("pair", "method_definition") else "")
            val = c.child_by_field_name("value") if c.type == "pair" else c
            if key == "state":
                found += [(n, "state", ln) for n, ln in _obj_keys(_returned_object(val))]
            elif key in ("getters", "actions") and val is not None and val.type == "object":
                found += [(n, key[:-1] if key == "getters" else "action", ln) for n, ln in _obj_keys(val)]
                found = [(n, "getter" if k == "getter" else k, ln) for n, k, ln in found]
    elif spec.type in ("arrow_function", "function_expression", "function"):
        body = spec.child_by_field_name("body")
        kinds = {}
        for c in (body.children if body is not None and body.type == "statement_block" else []):
            if c.type == "function_declaration":
                kinds[_txt(c.child_by_field_name("name"))] = "action"
            elif c.type == "lexical_declaration":
                for d in c.children:
                    if d.type != "variable_declarator":
                        continue
                    v = d.child_by_field_name("value")
                    if v is None:
                        continue
                    callee = _txt(v.child_by_field_name("function")) if v.type == "call_expression" else ""
                    kinds[_txt(d.child_by_field_name("name"))] = (
                        "getter" if callee in ("computed",) else "action" if v.type in _FN_VALUES else "state")
        for c in (_returned_object(spec).children if _returned_object(spec) is not None else []):
            if c.type == "shorthand_property_identifier":
                name, ref = _txt(c), _txt(c)
            elif c.type == "pair":
                name, v = _txt(c.child_by_field_name("key")), c.child_by_field_name("value")
                ref = _txt(v) if v is not None and v.type == "identifier" else ""
            else:
                continue
            found.append((name, kinds.get(ref, "state"), c.start_point[0] + 1))
    for name, kind, line in found:
        syms.append((name, "store_member", line, store))
        members.append((store, name, kind))


def _js_origin(d, out):
    """Record where the variable(s) declared by a `variable_declarator` come from."""
    name, val = d.child_by_field_name("name"), d.child_by_field_name("value")
    if name is None or val is None or len(out) >= 500:
        return
    if val.type == "await_expression" and val.children:
        val = val.children[-1]
    if val.type == "new_expression":
        kind, fn = "new", val.child_by_field_name("constructor")
    elif val.type == "call_expression":
        kind, fn = "call", val.child_by_field_name("function")
    else:
        return
    if fn is None or fn.type != "identifier":
        return
    callee, alias = _txt(fn), None
    if callee == "storeToRefs":
        a = val.child_by_field_name("arguments")
        first = next((c for c in (a.children if a is not None else []) if c.type == "identifier"), None)
        if first is None:
            return
        callee, alias = None, _txt(first)
    elif callee in KEYWORD_CALLS:
        return
    names = []
    if name.type == "identifier":
        names = [(_txt(name), None)]
    elif name.type == "object_pattern":
        for c in name.children:
            if c.type == "shorthand_property_identifier_pattern":
                names.append((_txt(c), _txt(c)))
            elif c.type == "pair_pattern":
                k, v = c.child_by_field_name("key"), c.child_by_field_name("value")
                if k is not None and v is not None and v.type == "identifier":
                    names.append((_txt(v), _txt(k)))
    if names:
        out.append((_js_caller(d), kind, callee, alias, names, d.start_point[0] + 1))


def route_target(node):
    """What a router call / `to` attribute points at: (kind, value, dynamic) or None.
    kind 'path' or 'name'; for a template literal or concatenation `value` is the static prefix and
    dynamic is True (`/trip/${id}` -> ('path', '/trip/', True))."""
    if node is None:
        return None
    t = node.type
    if t == "string":
        v = _string_value(node)
        return ("path", v, False) if v is not None else None
    if t == "template_string":
        prefix = ""
        for c in node.children:
            if c.type == "string_fragment":
                prefix += _txt(c)
            elif c.type == "template_substitution":
                return ("path", prefix, True)
        return ("path", prefix, False)
    if t == "binary_expression":
        left = route_target(node.child_by_field_name("left"))
        return ("path", left[1], True) if left and left[0] == "path" else None
    if t == "parenthesized_expression":
        inner = [c for c in node.children if c.type not in ("(", ")")]
        return route_target(inner[0]) if inner else None
    if t == "object":
        found = {}
        for c in node.children:
            if c.type == "pair":
                k = _txt(c.child_by_field_name("key")).strip("'\"")
                if k in ("name", "path"):
                    found[k] = route_target(c.child_by_field_name("value"))
        if found.get("name") and found["name"][0] == "path":
            return ("name", found["name"][1], found["name"][2])
        return found.get("path")
    return None


def _route_info(obj):
    """(path, name, component) of a route-record object literal, or None. component is
    ('ident', name) or ('import', module) or None."""
    path = name = comp = None
    has_target = False
    for c in obj.children:
        if c.type != "pair":
            continue
        k = _txt(c.child_by_field_name("key")).strip("'\"")
        v = c.child_by_field_name("value")
        if k == "path":
            path = _string_value(v)
        elif k == "name":
            name = _string_value(v)
        elif k in ("component", "components") and v is not None:
            has_target = True
            if v.type == "identifier":
                comp = ("ident", _txt(v))
            else:
                for x in _walk(v):
                    if x.type == "call_expression" and _txt(x.child_by_field_name("function")) == "import":
                        a = x.child_by_field_name("arguments")
                        first = next((q for q in (a.children if a is not None else []) if q.type == "string"), None)
                        if first is not None:
                            comp = ("import", _string_value(first))
                        break
        elif k in ("redirect", "children"):
            has_target = True
    return (path, name, comp) if path is not None and has_target else None


def _routes(root):
    """Route records of a router config: [(full path, name, component, line)] with nested `children`
    joined onto their parent's path."""
    infos = {}
    for n in _walk(root):
        if n.type == "object":
            info = _route_info(n)
            if info:
                infos[n.id] = (n, info)
    out = []
    for nid, (n, (path, name, comp)) in infos.items():
        full, cur = path, n
        while not full.startswith("/"):
            par = cur.parent.parent.parent if cur.parent is not None and cur.parent.parent is not None else None
            if par is None or par.id not in infos or cur.parent.type != "array":
                full = "/" + full
                break
            full = infos[par.id][1][0].rstrip("/") + "/" + full
            cur = par
        out.append((full.replace("//", "/"), name, comp, n.start_point[0] + 1))
    out.sort(key=lambda r: r[3])
    return out


def text_hint(root):
    """Cheap pre-check so files without any `path` word skip the route scan."""
    return root.text.decode("utf-8", errors="ignore") if root.end_byte < 400000 else "path"


def _as_object_type(body):
    """interface_body shares the shape of object_type for our purposes."""
    return body


def _string_value(n):
    """Text of a string literal node (quotes stripped), or None."""
    if n is None or n.type not in ("string", "template_string"):
        return None
    frag = next((c for c in n.children if c.type == "string_fragment"), None)
    return _txt(frag) if frag is not None else (_txt(n).strip("'\"`") if n.type == "string" else None)


def _declared_names(node, type_props):
    """[(name, line)] declared by a props / emits spec: an array of strings, an object literal, or
    (in a type argument) an object type, a call-signature list or a type name from this file."""
    out = []
    if node is None:
        return out
    t = node.type
    if t == "array":
        for c in node.children:
            v = _string_value(c)
            if v:
                out.append((v, c.start_point[0] + 1))
    elif t == "object":
        out += _obj_keys(node)
    elif t == "type_identifier":
        out += type_props.get(_txt(node), [])
    elif t in ("object_type", "interface_body"):
        for c in node.children:
            if c.type == "property_signature":
                k = c.children[0] if c.children else None
                name = _string_value(k) if k is not None and k.type == "string" else _txt(k)
                if name:
                    out.append((name, c.start_point[0] + 1))
            elif c.type == "call_signature":  # (e: 'save', x: T): void
                params = next((x for x in c.children if x.type == "formal_parameters"), None)
                first = next((x for x in (params.children if params is not None else [])
                              if x.type in ("required_parameter", "optional_parameter")), None)
                frag = None
                for x in (_walk(first) if first is not None else []):
                    if x.type == "string_fragment":
                        frag = x
                        break
                if frag is not None:
                    out.append((_txt(frag), c.start_point[0] + 1))
    return out


def _define_macro(call, name, syms, type_props):
    """defineProps / defineEmits (and the options-API `props:` / `emits:` values)."""
    kind = "prop" if name == "defineProps" else "emit"
    targ = next((c for c in call.children if c.type == "type_arguments"), None)
    args = call.child_by_field_name("arguments")
    sources = []
    if targ is not None:
        sources += [c for c in targ.children if c.type not in ("<", ">", ",")][:1]
    sources += [c for c in (args.children if args is not None else []) if c.type not in ("(", ")", ",")][:1]
    for src in sources:
        for nm, ln in _declared_names(src, type_props):
            syms.append((nm, kind, ln, None))


def _base_name(c):
    """Written name of a base class / interface node, or None when it is not a plain name."""
    t = c.type
    if t in ("identifier", "type_identifier", "member_expression", "nested_type_identifier",
             "attribute"):
        return _txt(c) or None
    if t == "generic_type":
        first = c.children[0] if c.children else None
        return _base_name(first) if first is not None else None
    if t == "subscript":  # python Generic[T], Base[int]
        v = c.child_by_field_name("value")
        return _base_name(v) if v is not None else None
    if t == "parenthesized_expression":
        inner = [x for x in c.children if x.type not in ("(", ")")]
        return _base_name(inner[0]) if inner else None
    return None


def _js_heritage(n, cname, out):
    line = n.start_point[0] + 1
    for c in n.children:
        if c.type == "class_heritage":
            for clause in c.children:
                kind = "implements" if clause.type == "implements_clause" else "extends"
                for b in clause.children:
                    name = _base_name(b)
                    if name:
                        out.append((cname, name, kind, line))
        elif c.type == "extends_type_clause":  # interface X extends Y, Z
            for b in c.children:
                name = _base_name(b)
                if name:
                    out.append((cname, name, "extends", line))


def _js(root):
    syms, imps, calls, binds, ilines, heritage = [], [], [], {}, {}, []
    members, origins, reads = [], [], []
    type_props, emit_cands, macros, nav_cands, callbacks = {}, [], [], [], []

    def add_import(raw, line):
        if raw and raw not in imps:
            imps.append(raw)
            ilines[raw] = line

    for n in _walk(root):
        t = n.type
        line = n.start_point[0] + 1
        if t in ("interface_declaration", "type_alias_declaration"):
            body = n.child_by_field_name("body") if t == "interface_declaration" else n.child_by_field_name("value")
            if body is not None and body.type in ("object_type", "interface_body"):
                type_props[_txt(n.child_by_field_name("name"))] = _declared_names(
                    body if body.type == "object_type" else _as_object_type(body), type_props)
        if t == "pair" and n.parent is not None and n.parent.type == "object":
            key = _txt(n.child_by_field_name("key")).strip("'\"")
            gp = n.parent.parent
            if key in ("props", "emits") and gp is not None and (
                    gp.type == "export_statement" or (gp.type == "arguments" and gp.parent is not None
                                                      and _txt(gp.parent.child_by_field_name("function")) in (
                                                          "defineComponent", "Vue.extend"))):
                for nm, ln in _declared_names(n.child_by_field_name("value"), type_props):
                    syms.append((nm, "prop" if key == "props" else "emit", ln, None))
        if t == "call_expression":
            fn0 = n.child_by_field_name("function")
            if len(callbacks) < _MAX_CALLS:  # functions handed to another call: watch(src, handler)
                a2 = n.child_by_field_name("arguments")
                for arg in (a2.children if a2 is not None else []):
                    if arg.type == "identifier":
                        callbacks.append((_js_caller(n), _txt(arg), None, arg.start_point[0] + 1))
                    elif arg.type == "member_expression" and _txt(arg.child_by_field_name("object")) == "this":
                        callbacks.append((_js_caller(n), _txt(arg.child_by_field_name("property")), "this",
                                          arg.start_point[0] + 1))
            if fn0 is not None and fn0.type == "member_expression" and len(nav_cands) < 300 and _txt(
                    fn0.child_by_field_name("property")) in ("push", "replace"):
                a1 = n.child_by_field_name("arguments")
                tgt = route_target(next((c for c in (a1.children if a1 is not None else [])
                                         if c.type not in ("(", ")", ",")), None))
                if tgt:
                    nav_cands.append((_js_caller(n), _txt(fn0.child_by_field_name("object")), tgt, line))
            if fn0 is not None and fn0.type == "identifier":
                f0 = _txt(fn0)
                if f0 in ("defineProps", "defineEmits"):
                    macros.append((n, f0))
                elif len(emit_cands) < 300:
                    a0 = n.child_by_field_name("arguments")
                    first = next((c for c in (a0.children if a0 is not None else []) if c.type not in ("(", ")", ",")),
                                 None)
                    ev = _string_value(first)
                    if ev:
                        emit_cands.append((_js_caller(n), f0, ev, line))
        if t == "variable_declarator":
            _js_origin(n, origins)
        elif t == "member_expression" and len(reads) < _MAX_CALLS:
            o, prop, par = n.child_by_field_name("object"), n.child_by_field_name("property"), n.parent
            if o is not None and o.type == "identifier" and prop is not None and not (
                    par is not None and par.type == "call_expression" and par.child_by_field_name("function") == n):
                reads.append((_js_caller(n), _txt(o), _txt(prop), line))
        if t in ("function_declaration", "generator_function_declaration"):
            name = n.child_by_field_name("name")
            if name is not None:
                syms.append((_txt(name), "function", line, None))
        elif t in _CLASS_NODES and t != "class":
            name = n.child_by_field_name("name")
            if name is not None:
                cname = _txt(name)
                syms.append((cname, "class", line, None))
                _js_heritage(n, cname, heritage)
                body = n.child_by_field_name("body")
                for m in (body.children if body is not None else []):
                    mname = m.child_by_field_name("name")
                    if mname is None:
                        continue
                    if m.type in ("method_definition", "abstract_method_signature"):
                        syms.append((_txt(mname), "method", m.start_point[0] + 1, cname))
                    elif m.type in ("public_field_definition", "field_definition"):
                        val = m.child_by_field_name("value")
                        if val is not None and val.type in _FN_VALUES:
                            syms.append((_txt(mname), "method", m.start_point[0] + 1, cname))
        elif t == "interface_declaration":
            syms.append((_txt(n.child_by_field_name("name")), "interface", line, None))
            _js_heritage(n, _txt(n.child_by_field_name("name")), heritage)
        elif t == "type_alias_declaration":
            syms.append((_txt(n.child_by_field_name("name")), "type", line, None))
        elif t == "enum_declaration":
            syms.append((_txt(n.child_by_field_name("name")), "enum", line, None))
        elif t in ("lexical_declaration", "variable_declaration"):
            parent = n.parent
            top = parent is not None and (parent.type == "program" or (
                parent.type == "export_statement" and parent.parent is not None
                and parent.parent.type == "program"))
            if not top:
                continue
            exported = parent.type == "export_statement"
            for d in n.children:
                if d.type != "variable_declarator":
                    continue
                name, val = d.child_by_field_name("name"), d.child_by_field_name("value")
                if name is None or name.type != "identifier":
                    continue
                dline = d.start_point[0] + 1
                if val is not None and val.type in _FN_VALUES:
                    syms.append((_txt(name), "function", dline, None))
                elif val is not None and val.type == "call_expression" \
                        and _txt(val.child_by_field_name("function")) == "defineStore":
                    syms.append((_txt(name), "store", dline, None))
                    _pinia_members(val, _txt(name), syms, members)
                elif exported:
                    syms.append((_txt(name), "variable", dline, None))
        elif t in ("import_statement", "export_statement"):
            src = n.child_by_field_name("source")
            if src is not None:
                raw = _txt(src).strip("'\"`")
                add_import(raw, line)
                if t == "import_statement":
                    _js_bindings(n, raw, binds)
        elif t == "new_expression":
            _js_call(n, calls)
        elif t == "call_expression":
            _js_call(n, calls)
            fn = n.child_by_field_name("function")
            args = n.child_by_field_name("arguments")
            if fn is not None and args is not None and (fn.type == "import" or _txt(fn) == "require"):
                first = next((c for c in args.children if c.type == "string"), None)
                if first is not None:
                    add_import(_txt(first).strip("'\"`"), line)
    emit_vars = {"emit"}
    for caller, kind, callee, alias, names, ln in origins:
        if callee == "defineEmits":
            emit_vars |= {nm for nm, _ in names}
    for call, mname in macros:
        _define_macro(call, mname, syms, type_props)
    emit_calls = [(c, ev, ln) for c, f0, ev, ln in emit_cands if f0 in emit_vars]
    router_vars = {"router", "$router", "this.$router"}
    for caller, kind, callee, alias, names, ln in origins:
        if callee == "useRouter":
            router_vars |= {nm for nm, _ in names}
    navs = [(c, tgt[0], tgt[1], tgt[2], ln) for c, obj, tgt, ln in nav_cands if obj in router_vars]
    routes = _routes(root) if "path" in text_hint(root) else []
    for full, rname, comp, ln in routes:
        syms.append((full, "route", ln, None))
        members.append((None, full, rname))
    syms = [s for s in syms if s[0]]
    syms.sort(key=lambda s: s[2])
    return (syms, imps[:200], calls, binds, ilines, heritage, members, origins, reads, emit_calls, navs, routes,
            callbacks)


def _js_bindings(stmt, raw, binds):
    for clause in stmt.children:
        if clause.type != "import_clause":
            continue
        for c in clause.children:
            if c.type == "identifier":
                binds[_txt(c)] = (raw, "default")
            elif c.type == "namespace_import":
                ident = next((x for x in c.children if x.type == "identifier"), None)
                if ident is not None:
                    binds[_txt(ident)] = (raw, "*")
            elif c.type == "named_imports":
                for spec in c.children:
                    if spec.type != "import_specifier":
                        continue
                    name = _txt(spec.child_by_field_name("name"))
                    alias = _txt(spec.child_by_field_name("alias")) or name
                    if name:
                        binds[alias] = (raw, name)


# ---- Python ------------------------------------------------------------------------

def _python(root):
    syms, imps, calls, binds, ilines, heritage = [], [], [], {}, {}, []
    origins, callbacks = [], []

    def add_import(raw, line):
        if raw and raw not in imps:
            imps.append(raw)
            ilines[raw] = line

    # (node, enclosing class name or None, at module level, enclosing function name or None)
    stack = [(root, None, True, None)]
    while stack:
        n, cls, top, caller = stack.pop()
        t = n.type
        nxt_cls, nxt_top, nxt_caller = cls, top, caller
        if t == "assignment" and len(origins) < 500:  # x = Foo(...)
            left, right = n.child_by_field_name("left"), n.child_by_field_name("right")
            fn = right.child_by_field_name("function") if right is not None and right.type == "call" else None
            if left is not None and left.type == "identifier" and fn is not None and fn.type == "identifier":
                origins.append((caller, "call", _txt(fn), None, [(_txt(left), None)], n.start_point[0] + 1))
        if t == "class_definition":
            name = n.child_by_field_name("name")
            if name is not None:
                syms.append((_txt(name), "class", n.start_point[0] + 1, cls))
                nxt_cls, nxt_top = _txt(name), False
                bases = n.child_by_field_name("superclasses")
                for b in (bases.children if bases is not None else []):
                    base = _base_name(b)
                    if base:
                        heritage.append((_txt(name), base, "extends", n.start_point[0] + 1))
        elif t == "function_definition":
            name = n.child_by_field_name("name")
            if name is not None:
                syms.append((_txt(name), "method" if cls else "function", n.start_point[0] + 1, cls))
                nxt_caller = (cls + "." + _txt(name)) if cls else _txt(name)
            nxt_cls, nxt_top = None, False
        elif t == "call" and len(calls) < _MAX_CALLS:
            fn = n.child_by_field_name("function")
            obj = None
            if fn is not None and fn.type == "identifier":
                cname = _txt(fn)
            elif fn is not None and fn.type == "attribute":
                cname = _txt(fn.child_by_field_name("attribute"))
                o = fn.child_by_field_name("object")
                if o is not None and o.type == "identifier":
                    obj = "this" if _txt(o) in ("self", "cls") else _txt(o)
            else:
                cname = ""
            if cname and cname not in KEYWORD_CALLS:
                calls.append((caller, cname, obj, n.start_point[0] + 1))
            args = n.child_by_field_name("arguments")
            for arg in (args.children if args is not None and len(callbacks) < _MAX_CALLS else []):
                if arg.type == "keyword_argument":
                    arg = arg.child_by_field_name("value")
                if arg is not None and arg.type == "identifier":
                    callbacks.append((caller, _txt(arg), None, arg.start_point[0] + 1))
        elif t == "assignment" and top:
            left = n.child_by_field_name("left")
            if left is not None and left.type == "identifier" and _CONST_RE.match(_txt(left)):
                syms.append((_txt(left), "constant", n.start_point[0] + 1, None))
        elif t == "import_from_statement":
            raw = _txt(n.child_by_field_name("module_name"))
            add_import(raw, n.start_point[0] + 1)
            for c in n.children_by_field_name("name"):
                if c.type == "aliased_import":
                    orig = _txt(c.child_by_field_name("name"))
                    binds[_txt(c.child_by_field_name("alias")) or orig] = (raw, orig)
                else:
                    binds[_txt(c)] = (raw, _txt(c))
        elif t == "import_statement":
            for c in n.children_by_field_name("name"):
                if c.type == "aliased_import":
                    mod = _txt(c.child_by_field_name("name"))
                    add_import(mod, n.start_point[0] + 1)
                    binds[_txt(c.child_by_field_name("alias")) or mod] = (mod, "*")
                else:
                    mod = _txt(c)
                    add_import(mod, n.start_point[0] + 1)
                    binds[mod.split(".")[0]] = (mod.split(".")[0], "*")
        for c in reversed(n.children):
            stack.append((c, nxt_cls, nxt_top, nxt_caller))
    syms.sort(key=lambda s: s[2])
    return syms, imps[:200], calls, binds, ilines, heritage, [], origins, [], [], [], [], callbacks
