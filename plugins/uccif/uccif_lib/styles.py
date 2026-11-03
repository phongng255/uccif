"""CSS variables and classes, by regex (no optional packages needed).

symbols(text, lang): definitions to add to a file's symbols:
  - CSS custom properties `--x:` inside `<style>` blocks of .vue/.svelte files (CSS files already
    get them from the per-line style regex), kind css-var;
  - class selectors `.name` in CSS/SCSS/Less files and in `<style>` blocks, kind css-class.
  It returns (symbols, scoped class names): names defined in `<style scoped>` / `<style module>`.
uses(text, lang): [(kind, name, line)] with kind
  - "var" for `var(--x)` anywhere (CSS, `<style>`, inline `style=`, CSS-in-JS strings),
  - "define" for `el.style.setProperty('--x', ...)` in code (a runtime definition),
  - "read" for `getPropertyValue('--x')`.
Template classes come from vue_template (they need the HTML grammar).
"""

import re

_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_STYLE_BLOCK = re.compile(r"<style\b([^>]*)>(.*?)</style>", re.S | re.I)
_VAR_DEF = re.compile(r"(?:^|[;{\s])(--[\w-]+)\s*:", re.M)
_VAR_USE = re.compile(r"var\(\s*(--[\w-]+)")
_SET_PROP = re.compile(r"""setProperty\(\s*['"`](--[\w-]+)""")
_GET_PROP = re.compile(r"""getPropertyValue\(\s*['"`](--[\w-]+)""")
_CLASS_SEL = re.compile(r"\.(-?[_a-zA-Z][\w-]*)")
STYLE_LANGS = ("css", "scss", "less")


def _blank_comments(css):
    return _COMMENT.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), css)


def style_parts(text, lang):
    """[(css text, offset in the file, scoped)] for a stylesheet or the <style> blocks of a component."""
    if lang in STYLE_LANGS:
        return [(text, 0, False)]
    if lang in ("vue", "svelte"):
        out = []
        for m in _STYLE_BLOCK.finditer(text):
            attrs = m.group(1)
            out.append((m.group(2), m.start(2), "scoped" in attrs or "module" in attrs or lang == "svelte"))
        return out
    return []


def _selectors(css):
    """(selector text, start offset) for every rule, skipping declarations and at-rule preludes."""
    out, start = [], 0
    for i, ch in enumerate(css):
        if ch == "{":
            seg = css[start:i]
            cut = max(seg.rfind(";"), seg.rfind("}"))
            sel_start = start + cut + 1
            sel = css[sel_start:i]
            if not sel.strip().startswith("@"):
                out.append((sel, sel_start))
            start = i + 1
        elif ch in "};":
            start = i + 1
    return out


def symbols(text, lang):
    syms, scoped_names = [], set()
    for css, offset, scoped in style_parts(text, lang):
        css = _blank_comments(css)
        base = text.count("\n", 0, offset)
        if lang not in STYLE_LANGS:  # stylesheets already get --vars from the per-line regex
            for m in _VAR_DEF.finditer(css):
                syms.append((m.group(1), "css-var", base + css.count("\n", 0, m.start(1)) + 1, None))
        seen = set()
        for sel, pos in _selectors(css):
            for m in _CLASS_SEL.finditer(re.sub(r"\[[^\]]*\]|\([^)]*\)|'[^']*'|\"[^\"]*\"", lambda x: " " * len(
                    x.group(0)), sel)):
                name = m.group(1)
                if name in seen or re.match(r"^\d", name):
                    continue
                seen.add(name)
                syms.append((name, "css-class", base + css.count("\n", 0, pos + m.start()) + 1, None))
                if scoped:
                    scoped_names.add(name)
    return syms[:2000], scoped_names


def uses(text, lang):
    out = []
    if "--" not in text:
        return out
    for kind, rx in (("var", _VAR_USE), ("define", _SET_PROP), ("read", _GET_PROP)):
        for m in rx.finditer(text):
            out.append((kind, m.group(1), text.count("\n", 0, m.start(1)) + 1))
    return out[:2000]
