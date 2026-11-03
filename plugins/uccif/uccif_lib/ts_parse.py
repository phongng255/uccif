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
_FN_VALUES = ("arrow_function", "function_expression", "function", "generator_function")
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
    """-> (symbols, imports) or None. symbols: [(name, kind, line, scope)]; imports: [raw].
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

def _js(root):
    syms, imps = [], []

    def add_import(raw):
        if raw and raw not in imps:
            imps.append(raw)

    for n in _walk(root):
        t = n.type
        line = n.start_point[0] + 1
        if t in ("function_declaration", "generator_function_declaration"):
            name = n.child_by_field_name("name")
            if name is not None:
                syms.append((_txt(name), "function", line, None))
        elif t in _CLASS_NODES and t != "class":
            name = n.child_by_field_name("name")
            if name is not None:
                cname = _txt(name)
                syms.append((cname, "class", line, None))
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
                elif exported:
                    syms.append((_txt(name), "variable", dline, None))
        elif t in ("import_statement", "export_statement"):
            src = n.child_by_field_name("source")
            if src is not None:
                add_import(_txt(src).strip("'\"`"))
        elif t == "call_expression":
            fn = n.child_by_field_name("function")
            args = n.child_by_field_name("arguments")
            if fn is not None and args is not None and (fn.type == "import" or _txt(fn) == "require"):
                first = next((c for c in args.children if c.type == "string"), None)
                if first is not None:
                    add_import(_txt(first).strip("'\"`"))
    syms = [s for s in syms if s[0]]
    syms.sort(key=lambda s: s[2])
    return syms, imps[:200]


# ---- Python ------------------------------------------------------------------------

def _python(root):
    syms, imps = [], []

    def add_import(raw):
        if raw and raw not in imps:
            imps.append(raw)

    # (node, enclosing class name or None, at module level)
    stack = [(root, None, True)]
    while stack:
        n, cls, top = stack.pop()
        t = n.type
        nxt_cls, nxt_top = cls, top
        if t == "class_definition":
            name = n.child_by_field_name("name")
            if name is not None:
                syms.append((_txt(name), "class", n.start_point[0] + 1, cls))
                nxt_cls, nxt_top = _txt(name), False
        elif t == "function_definition":
            name = n.child_by_field_name("name")
            if name is not None:
                syms.append((_txt(name), "method" if cls else "function", n.start_point[0] + 1, cls))
            nxt_cls, nxt_top = None, False
        elif t == "assignment" and top:
            left = n.child_by_field_name("left")
            if left is not None and left.type == "identifier" and _CONST_RE.match(_txt(left)):
                syms.append((_txt(left), "constant", n.start_point[0] + 1, None))
        elif t == "import_from_statement":
            add_import(_txt(n.child_by_field_name("module_name")))
        elif t == "import_statement":
            for c in n.children_by_field_name("name"):
                add_import(_txt(c.child_by_field_name("name") if c.type == "aliased_import" else c))
        for c in reversed(n.children):
            stack.append((c, nxt_cls, nxt_top))
    syms.sort(key=lambda s: s[2])
    return syms, imps[:200]
