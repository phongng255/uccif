"""Optional tree-sitter parsing for the code index.

Everything here is best-effort: if `tree-sitter` or a grammar package is not installed
(or UCCIF_NO_TREE_SITTER is set), `parse()` returns None and the index falls back to
universal-ctags, then regexes. UCCIF never installs anything; `uccif doctor` only reports.

Optional packages: tree-sitter, tree-sitter-javascript, tree-sitter-typescript,
tree-sitter-python, tree-sitter-go, tree-sitter-rust, tree-sitter-java.
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
                 "function", "constructor", "typeof", "await"}
_CLASS_NODES = ("class_declaration", "abstract_class_declaration", "class")
_MAX_IDENTS = 3000
_TYPE_DECLS = ("interface_declaration", "type_alias_declaration", "class_declaration", "abstract_class_declaration",
               "enum_declaration", "type_parameter", "class")
_NOT_A_USE = ("variable_declarator", "function_declaration", "generator_function_declaration", "class_declaration",
              "import_specifier", "import_clause", "namespace_import", "export_specifier", "formal_parameters",
              "required_parameter", "optional_parameter", "labeled_statement", "break_statement",
              "continue_statement", "method_definition", "arrow_function", "catch_clause", "for_in_statement",
              "shorthand_property_identifier_pattern", "pair_pattern", "object_pattern", "array_pattern",
              "assignment_pattern", "rest_pattern")


def _is_default(x):
    """Is identifier x the default value of a parameter / pattern (a read, not a declaration)?"""
    p = x.parent
    while p is not None and p.type not in ("formal_parameters", "variable_declarator", "catch_clause"):
        if (p.type in ("assignment_pattern", "object_assignment_pattern") and p.child_by_field_name("right") is not None and
                p.child_by_field_name("right").start_byte <= x.start_byte) or (
                p.type in ("required_parameter", "optional_parameter") and p.child_by_field_name("value")
                is not None and p.child_by_field_name("value").start_byte <= x.start_byte):
            return True
        p = p.parent
    return False


def _ident_use(n):
    """'w' when identifier `n` is written, 'r' when it is read, None for declarations / names."""
    par = n.parent
    if par is None:
        return None
    pt = par.type
    if pt in ("assignment_expression", "augmented_assignment_expression"):
        return "w" if par.child_by_field_name("left") == n else "r"
    if pt == "update_expression":
        return "w"
    if pt == "call_expression" and par.child_by_field_name("function") == n:
        return None  # a call, recorded as such
    if pt == "member_expression":
        if par.child_by_field_name("object") != n:
            return None
        gp = par.parent  # x.value = 1 writes x
        if gp is not None and gp.type in ("assignment_expression", "augmented_assignment_expression") and \
                gp.child_by_field_name("left") == par:
            return "w"
        return "r"
    if pt in _NOT_A_USE:
        if pt == "variable_declarator" and par.child_by_field_name("value") == n:
            return "r"
        if (pt == "assignment_pattern" and par.child_by_field_name("right") == n) or (
                pt in ("required_parameter", "optional_parameter") and par.child_by_field_name("value") == n):
            return "r"  # a default value: (count = total) => ...
        if pt == "arrow_function" and par.child_by_field_name("body") == n:
            return "r"
        if pt == "for_in_statement" and par.child_by_field_name("right") == n:
            return "r"
        return None
    return "r"


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
        elif grammar in ("go", "rust", "java"):  # roadmap layer E, each optional on its own
            mod = __import__("tree_sitter_" + grammar)
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
    out = {"typescript": bool(_parser("tsx")), "python": bool(_parser("python"))}
    for g in ("go", "rust", "java"):
        if _parser(g):
            out[g] = True
    return out


def grammar_for(rel, lang):
    if lang == "python":
        return "python"
    if lang in ("go", "rust", "java"):
        return lang
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
    """-> a 15-item tuple, or None:
    (symbols, imports, calls, bindings, import_lines, heritage, members, origins, reads, emit_calls,
    navs, routes, callbacks, idents, types). Items 7, 9, 10, 11, 12 (members, reads, emit_calls, navs,
    routes) are reserved and always empty: the slots stay so the tuple shape is stable.
    origins: where local variables come from, [(enclosing function, "call"|"new", callee, None,
    [(local, member or None)], line)] for `const s = make()`, `const {a, b: c} = make()`,
    `const x = new Foo()`; callbacks (13th): [(enclosing function, name, "this" | None, line)] for
    identifiers passed as call arguments; idents (14th): [(enclosing function, name, "r"|"w", line)]
    for identifiers used as values (writes: `x = `, `x += `, `x++`, `x.value = `); types (15th):
    [(enclosing function, type name, line)] for type references (TS type positions, Python annotations).
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
        if grammar in ("go", "rust", "java"):
            from uccif_lib import ts_other
            return ts_other.PARSERS[grammar](tree.root_node)
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
    callee = _txt(fn)
    if callee in KEYWORD_CALLS:
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
        out.append((_js_caller(d), kind, callee, None, names, d.start_point[0] + 1))


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
    origins, callbacks = [], []
    idents, types, declared = [], [], {}

    def add_import(raw, line):
        if raw and raw not in imps:
            imps.append(raw)
            ilines[raw] = line

    for n in _walk(root):
        t = n.type
        line = n.start_point[0] + 1
        if t == "call_expression":
            if len(callbacks) < _MAX_CALLS:  # functions handed to another call: watch(src, handler)
                a2 = n.child_by_field_name("arguments")
                for arg in (a2.children if a2 is not None else []):
                    if arg.type == "identifier":
                        callbacks.append((_js_caller(n), _txt(arg), None, arg.start_point[0] + 1))
                    elif arg.type == "member_expression" and _txt(arg.child_by_field_name("object")) == "this":
                        callbacks.append((_js_caller(n), _txt(arg.child_by_field_name("property")), "this",
                                          arg.start_point[0] + 1))
        if t in ("variable_declarator", "formal_parameters", "catch_clause", "for_in_statement"):
            target = {"variable_declarator": "name", "catch_clause": "parameter", "for_in_statement": "left"}.get(t)
            part = n.child_by_field_name(target) if target else n
            owner = _js_caller(n)
            if part is not None and owner is not None:  # names that shadow module variables in `owner`
                for x in _walk(part):
                    if x.type in ("identifier", "shorthand_property_identifier_pattern") and not _is_default(x):
                        declared.setdefault(owner, set()).add(_txt(x))
        if t == "identifier" and len(idents) < _MAX_IDENTS:
            rw = _ident_use(n)
            if rw:
                idents.append((_js_caller(n), _txt(n), rw, line))
        elif t == "type_identifier" and len(types) < _MAX_IDENTS:
            par = n.parent
            if par is not None and not (par.type in _TYPE_DECLS and par.child_by_field_name("name") == n):
                types.append((_js_caller(n), _txt(n), line))
        if t == "variable_declarator":
            _js_origin(n, origins)
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
            for d in n.children:
                if d.type != "variable_declarator":
                    continue
                name, val = d.child_by_field_name("name"), d.child_by_field_name("value")
                if name is None or name.type != "identifier":
                    continue
                dline = d.start_point[0] + 1
                if val is not None and val.type in _FN_VALUES:
                    syms.append((_txt(name), "function", dline, None))
                else:  # module state: `let count = 0`, `const cache = new Map()`, `const state = make()`
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
    idents = [i for i in idents if not (i[0] is not None and i[1] in declared.get(i[0], ()))]
    syms = [s for s in syms if s[0]]
    syms.sort(key=lambda s: s[2])
    return (syms, imps[:200], calls, binds, ilines, heritage, [], origins, [], [], [], [],
            callbacks, idents, types)


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
    origins, callbacks, types = [], [], []

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
        if t == "type" and len(types) < _MAX_IDENTS:  # annotations: def f(x: Order) -> Item
            for x in _walk(n):
                if x.type == "identifier":
                    types.append((caller, _txt(x), x.start_point[0] + 1))
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
    return syms, imps[:200], calls, binds, ilines, heritage, [], origins, [], [], [], [], callbacks, [], types
