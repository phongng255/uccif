"""Go, Rust and Java parsing for the code index (roadmap layer E).

Optional, like the rest of tree-sitter: needs `tree-sitter-go`, `tree-sitter-rust` or
`tree-sitter-java`. Each parser returns the same 15-item tuple as ts_parse.parse(); the slots that
only make sense for JS/Vue (store members, template data, routes ...) stay empty, and slot 7 holds
typed variables instead of JS origins: [(enclosing function, variable, type as written)] from
parameters, receivers, fields and typed locals, so `f.bar()` can be tied to the method of f's type.

calls: [(enclosing function "Type.method" or "func", callee, receiver, line)] where receiver is
"this" for self / this, an identifier, or a path (`crate::util`, `fmt`); bindings: {local name:
(module or package as written, imported name or "*")}.
"""

from uccif_lib.ts_parse import _txt, _walk

_LIMIT = 1500


def _empty():
    return [], [], [], {}, {}, [], [], [], [], [], [], [], [], [], []


def _base_type(n):
    """Type name of a type node, without pointers / references / generics (`*S`, `&mut Foo<T>`)."""
    if n is None:
        return None
    t = n.type
    if t in ("type_identifier", "identifier", "field_identifier"):
        return _txt(n)
    if t == "parameter_list":  # a Go receiver list: (s *S)
        decl = next((c for c in n.children if c.type == "parameter_declaration"), None)
        return _base_type(decl.child_by_field_name("type")) if decl is not None else None
    if t == "parameter_declaration":
        return _base_type(n.child_by_field_name("type"))
    if t in ("pointer_type", "reference_type", "generic_type", "scoped_type_identifier", "qualified_type",
             "array_type", "slice_type", "type"):
        if t in ("scoped_type_identifier", "qualified_type"):
            return _txt(n)  # pkg.T / crate::m::T: kept whole, split by the resolver
        for c in n.children:
            r = _base_type(c)
            if r:
                return r
    return None


# ---- Go ---------------------------------------------------------------------------

def _top_level(n):
    """A const/var spec directly in a package-level declaration (not inside a function)."""
    p = n.parent
    while p is not None and p.type in ("const_declaration", "var_declaration", "var_spec_list", "const_spec_list"):
        p = p.parent
    return p is not None and p.type == "source_file"


def _go_caller(n):
    p = n.parent
    while p is not None:
        if p.type == "function_declaration":
            return _txt(p.child_by_field_name("name"))
        if p.type == "method_declaration":
            recv = _base_type(p.child_by_field_name("receiver"))
            name = _txt(p.child_by_field_name("name"))
            return "%s.%s" % (recv, name) if recv else name
        p = p.parent
    return None


def parse_go(root):
    syms, imps, calls, binds, ilines, heritage, _m, typed = _empty()[:8]
    for n in _walk(root):
        t, line = n.type, n.start_point[0] + 1
        if t == "function_declaration":
            syms.append((_txt(n.child_by_field_name("name")), "function", line, None))
        elif t == "method_declaration":
            recv = _base_type(n.child_by_field_name("receiver"))
            syms.append((_txt(n.child_by_field_name("name")), "method", line, recv))
            rp = n.child_by_field_name("receiver")
            for pd in (rp.children if rp is not None else []):
                if pd.type == "parameter_declaration" and pd.child_by_field_name("name") is not None:
                    typed.append((_go_caller(pd.child_by_field_name("name")) or None,
                                  _txt(pd.child_by_field_name("name")), recv))
        elif t == "type_spec":
            body = n.child_by_field_name("type")
            kind = "interface" if body is not None and body.type == "interface_type" else (
                "class" if body is not None and body.type == "struct_type" else "type")
            syms.append((_txt(n.child_by_field_name("name")), kind, line, None))
        elif t in ("const_spec", "var_spec") and _top_level(n):
            for c in n.children_by_field_name("name"):
                syms.append((_txt(c), "constant" if t == "const_spec" else "variable", line, None))
        elif t == "import_spec":
            path = n.child_by_field_name("path")
            raw = _txt(path).strip('"`') if path is not None else ""
            if raw and raw not in imps:
                imps.append(raw)
                ilines[raw] = line
            alias = n.child_by_field_name("name")
            local = _txt(alias) if alias is not None else raw.rsplit("/", 1)[-1]
            if local not in ("_", "."):
                binds[local] = (raw, "*")
        elif t == "parameter_declaration" and n.parent is not None and n.parent.parent is not None \
                and n.parent.parent.type in ("function_declaration", "method_declaration", "func_literal") \
                and n.parent != n.parent.parent.child_by_field_name("receiver"):
            ty = _base_type(n.child_by_field_name("type"))
            for c in n.children_by_field_name("name"):
                if ty:
                    typed.append((_go_caller(n), _txt(c), ty))
        elif t == "call_expression" and len(calls) < _LIMIT:
            fn = n.child_by_field_name("function")
            if fn is not None and fn.type == "identifier":
                calls.append((_go_caller(n), _txt(fn), None, line))
            elif fn is not None and fn.type == "selector_expression":
                op = fn.child_by_field_name("operand")
                calls.append((_go_caller(n), _txt(fn.child_by_field_name("field")),
                              _txt(op) if op is not None and op.type == "identifier" else None, line))
    syms = [s for s in syms if s[0]]
    return syms, imps[:200], calls, binds, ilines, heritage, [], typed, [], [], [], [], [], [], []


# ---- Rust -------------------------------------------------------------------------

def _rust_impl_type(n):
    p = n.parent
    while p is not None:
        if p.type == "impl_item":
            return _base_type(p.child_by_field_name("type"))
        if p.type in ("trait_item",):
            return _txt(p.child_by_field_name("name"))
        p = p.parent
    return None


def _rust_caller(n):
    p = n.parent
    while p is not None:
        if p.type == "function_item":
            owner = _rust_impl_type(p)
            name = _txt(p.child_by_field_name("name"))
            return "%s.%s" % (owner, name) if owner else name
        p = p.parent
    return None


def _rust_uses(node, prefix, out):
    """Flatten a use tree into [(module path, item, local name)]."""
    t = node.type
    if t == "scoped_identifier":
        path = node.child_by_field_name("path")
        out.append(((prefix + "::" if prefix else "") + (_txt(path) if path is not None else ""),
                    _txt(node.child_by_field_name("name")), _txt(node.child_by_field_name("name"))))
    elif t == "use_as_clause":
        inner = []
        _rust_uses(node.child_by_field_name("path"), prefix, inner)
        alias = _txt(node.child_by_field_name("alias"))
        out += [(m, it, alias) for m, it, _ in inner]
    elif t == "scoped_use_list":
        path = node.child_by_field_name("path")
        base = (prefix + "::" if prefix else "") + (_txt(path) if path is not None else "")
        lst = node.child_by_field_name("list")
        for c in (lst.children if lst is not None else []):
            if c.type in ("identifier", "self"):
                name = _txt(c)
                out.append((base, name, base.rsplit("::", 1)[-1] if name == "self" else name))
            elif c.type in ("scoped_identifier", "use_as_clause", "scoped_use_list"):
                _rust_uses(c, base, out)
    elif t == "identifier":
        out.append((prefix, _txt(node), _txt(node)))


def parse_rust(root):
    syms, imps, calls, binds, ilines, heritage, _m, typed = _empty()[:8]
    for n in _walk(root):
        t, line = n.type, n.start_point[0] + 1
        if t == "function_item":
            owner = _rust_impl_type(n)
            syms.append((_txt(n.child_by_field_name("name")), "method" if owner else "function", line, owner))
            params = n.child_by_field_name("parameters")
            for prm in (params.children if params is not None else []):
                if prm.type == "parameter":
                    pat, ty = prm.child_by_field_name("pattern"), _base_type(prm.child_by_field_name("type"))
                    if pat is not None and pat.type == "identifier" and ty:
                        typed.append((_rust_caller(pat), _txt(pat), ty))
        elif t in ("struct_item", "enum_item", "trait_item", "type_item", "union_item"):
            kind = {"struct_item": "class", "enum_item": "enum", "trait_item": "interface"}.get(t, "type")
            syms.append((_txt(n.child_by_field_name("name")), kind, line, None))
        elif t in ("const_item", "static_item"):
            syms.append((_txt(n.child_by_field_name("name")), "constant", line, None))
        elif t == "impl_item":
            trait, ty = n.child_by_field_name("trait"), _base_type(n.child_by_field_name("type"))
            if trait is not None and ty:
                heritage.append((ty, _base_type(trait) or _txt(trait), "implements", line))
        elif t == "mod_item" and n.child_by_field_name("body") is None:
            name = _txt(n.child_by_field_name("name"))
            if name not in imps:
                imps.append(name)
                ilines[name] = line
            binds[name] = (name, "*")
        elif t == "use_declaration":
            arg = n.child_by_field_name("argument")
            items = []
            if arg is not None:
                _rust_uses(arg, "", items)
            for module, item, local in items:
                if not module:
                    continue
                if module not in imps:
                    imps.append(module)
                    ilines[module] = line
                binds[local] = (module, "*" if item == "self" else item)
        elif t == "let_declaration":
            pat, ty = n.child_by_field_name("pattern"), _base_type(n.child_by_field_name("type"))
            if pat is not None and pat.type == "identifier" and ty:
                typed.append((_rust_caller(n), _txt(pat), ty))
        elif t == "call_expression" and len(calls) < _LIMIT:
            fn = n.child_by_field_name("function")
            caller = _rust_caller(n)
            if fn is None:
                continue
            if fn.type == "identifier":
                calls.append((caller, _txt(fn), None, line))
            elif fn.type == "scoped_identifier":  # util::helper(), Foo::new(), crate::m::f()
                path = fn.child_by_field_name("path")
                calls.append((caller, _txt(fn.child_by_field_name("name")), _txt(path) if path is not None else None,
                              line))
            elif fn.type == "field_expression":  # self.go(), x.y()
                val = fn.child_by_field_name("value")
                obj = "this" if val is not None and val.type == "self" else (
                    _txt(val) if val is not None and val.type == "identifier" else None)
                calls.append((caller, _txt(fn.child_by_field_name("field")), obj, line))
    syms = [s for s in syms if s[0]]
    return syms, imps[:200], calls, binds, ilines, heritage, [], typed, [], [], [], [], [], [], []


# ---- Java -------------------------------------------------------------------------

_JAVA_TYPES = ("class_declaration", "interface_declaration", "enum_declaration", "record_declaration")


def _java_class(n):
    p = n.parent
    while p is not None:
        if p.type in _JAVA_TYPES:
            return _txt(p.child_by_field_name("name"))
        p = p.parent
    return None


def _java_caller(n):
    p = n.parent
    while p is not None:
        if p.type in ("method_declaration", "constructor_declaration"):
            cls = _java_class(p)
            name = _txt(p.child_by_field_name("name"))
            return "%s.%s" % (cls, name) if cls else name
        if p.type in _JAVA_TYPES:
            return _txt(p.child_by_field_name("name"))  # field initialisers belong to the class
        p = p.parent
    return None


def parse_java(root):
    syms, imps, calls, binds, ilines, heritage, _m, typed = _empty()[:8]
    for n in _walk(root):
        t, line = n.type, n.start_point[0] + 1
        if t in _JAVA_TYPES:
            name = _txt(n.child_by_field_name("name"))
            kind = {"interface_declaration": "interface", "enum_declaration": "enum"}.get(t, "class")
            syms.append((name, kind, line, _java_class(n)))
            sup = n.child_by_field_name("superclass")
            if sup is not None:
                b = _base_type(next((c for c in sup.children if c.type not in ("extends",)), None))
                if b:
                    heritage.append((name, b, "extends", line))
            ifs = n.child_by_field_name("interfaces")
            for c in (_walk(ifs) if ifs is not None else []):
                if c.type == "type_identifier":
                    heritage.append((name, _txt(c), "implements" if t != "interface_declaration" else "extends",
                                     line))
        elif t in ("method_declaration", "constructor_declaration"):
            syms.append((_txt(n.child_by_field_name("name")), "method", line, _java_class(n)))
        elif t == "import_declaration":
            target = next((c for c in n.children if c.type in ("scoped_identifier", "identifier")), None)
            raw = _txt(target) if target is not None else ""
            wild = any(c.type == "asterisk" for c in n.children)
            if raw:
                raw = raw + ".*" if wild else raw
                if raw not in imps:
                    imps.append(raw)
                    ilines[raw] = line
                if not wild:
                    binds[raw.rsplit(".", 1)[-1]] = (raw, raw.rsplit(".", 1)[-1])
        elif t in ("formal_parameter", "local_variable_declaration", "field_declaration"):
            ty = _base_type(n.child_by_field_name("type"))
            owner = _java_caller(n) if t != "field_declaration" else None  # fields: whole file
            if ty:
                if t == "formal_parameter":
                    typed.append((owner, _txt(n.child_by_field_name("name")), ty))
                for d in n.children_by_field_name("declarator"):
                    typed.append((owner, _txt(d.child_by_field_name("name")), ty))
        elif t == "method_invocation" and len(calls) < _LIMIT:
            obj = n.child_by_field_name("object")
            o = None
            if obj is not None:
                o = "this" if obj.type == "this" else (_txt(obj) if obj.type == "identifier" else None)
            calls.append((_java_caller(n), _txt(n.child_by_field_name("name")), o, line))
        elif t == "object_creation_expression" and len(calls) < _LIMIT:
            ty = _base_type(n.child_by_field_name("type"))
            if ty:
                calls.append((_java_caller(n), ty, None, line))
    syms = [s for s in syms if s[0]]
    return syms, imps[:200], calls, binds, ilines, heritage, [], typed, [], [], [], [], [], [], []


PARSERS = {"go": parse_go, "rust": parse_rust, "java": parse_java}
