#!/usr/bin/env python3
"""
Convert diagram-maker HTML output to a whiteboard-compatible SVG.

Usage:
    python3 html_to_svg.py <input.html> <output.svg>

The script:
1. Extracts the inner <svg> from the HTML (diagram-maker embeds SVG in HTML)
2. Parses the <style> block:
   - Reads CSS variables (`:root { --input: #bfdbfe; }`)
   - Reads class rules (`.node { stroke: var(--line); }`, `.input { fill: var(--input); }`)
   - Resolves var() references against the variable map
3. For every SVG element with a class attribute, looks up each class's resolved
   styles and inlines them as presentation attributes (fill, stroke, font-*, ...).
   Inline presentation attributes on the element itself take precedence.
4. Strips non-standard attributes, CSS classes, and var() references that
   Lark whiteboard can't parse.
5. Outputs a clean SVG ready for `lark-cli whiteboard +update`.

Supports both the older diagram-maker style (fill/stroke directly on elements)
and the newer CSS-variable style (light/dark mode via :root and @media).
"""

import sys
import re
from bs4 import BeautifulSoup, Comment


# ---------------------------------------------------------------------------
# CSS parsing
# ---------------------------------------------------------------------------

_VAR_RE = re.compile(r"--([a-zA-Z_][\w-]*)\s*:\s*([^;]+)\s*;")
_RULE_RE = re.compile(r"([^{}]+)\{([^{}]*)\}")
_DECL_RE = re.compile(r"([a-zA-Z-]+)\s*:\s*([^;]+)\s*;")
_VAR_REF_RE = re.compile(r"var\(\s*--([a-zA-Z_][\w-]*)\s*\)")

# Properties we are willing to inline as presentation attributes on SVG elements.
# The mapping is from CSS property name to SVG presentation attribute name.
INLINEABLE_PROPS = {
    "fill": "fill",
    "stroke": "stroke",
    "stroke-width": "stroke-width",
    "stroke-dasharray": "stroke-dasharray",
    "stroke-linecap": "stroke-linecap",
    "stroke-linejoin": "stroke-linejoin",
    "opacity": "opacity",
    "font-size": "font-size",
    "font-weight": "font-weight",
    "font-family": "font-family",
    "text-anchor": "text-anchor",
    "fill-opacity": "fill-opacity",
    "stroke-opacity": "stroke-opacity",
}

# Properties we ignore even if present in a CSS rule (e.g. color on text without
# an explicit fill — we only handle what the SVG renderer can read).
IGNORED_PROPS = {"color", "background", "display", "visibility"}


def parse_css_variables(css_text: str, light_only: bool = True) -> dict:
    """Extract CSS custom properties from :root (and optionally @media blocks).

    If light_only is True, only the :root block outside any @media rule is
    considered (we cannot resolve prefers-color-scheme in a static SVG, so we
    always emit the light theme for the whiteboard).
    """
    variables = {}

    if light_only:
        # Strip out all @media blocks so we only see the top-level :root.
        css_text = re.sub(
            r"@media[^{}]*\{(?:[^{}]|\{[^{}]*\})*\}",
            "",
            css_text,
            flags=re.DOTALL,
        )

    for match in _VAR_RE.finditer(css_text):
        name, value = match.group(1).strip(), match.group(2).strip()
        variables[name] = value
    return variables


def _resolve_value(value: str, variables: dict, _depth: int = 0) -> str:
    """Resolve var(--xxx) references inside a CSS value."""
    if _depth > 5:
        return value  # Bail on cyclic or deeply nested var() chains.

    def repl(match: re.Match) -> str:
        name = match.group(1)
        if name in variables:
            return _resolve_value(variables[name], variables, _depth + 1)
        return match.group(0)

    resolved = _VAR_REF_RE.sub(repl, value)
    return resolved.strip()


def parse_class_rules(css_text: str, variables: dict) -> dict:
    """Parse CSS class rules into a {class_name: {attr: value}} map.

    var() references are resolved against the supplied variables dict.
    Only properties we know how to inline as SVG presentation attributes are kept.
    """
    rules: dict[str, dict[str, str]] = {}

    # Drop @media blocks — we only inline the light theme.
    css_text = re.sub(
        r"@media[^{}]*\{(?:[^{}]|\{[^{}]*\})*\}",
        "",
        css_text,
        flags=re.DOTALL,
    )

    for selector_block, body in _RULE_RE.findall(css_text):
        selector = selector_block.strip()
        # We only care about simple class selectors like ".foo" or ".foo.bar".
        if not selector.startswith("."):
            continue
        # Skip pseudo-classes and pseudo-elements.
        if ":" in selector or "," in selector:
            continue
        class_names = [c for c in selector.split(".") if c]
        if not class_names:
            continue

        declarations = {}
        for prop, value in _DECL_RE.findall(body):
            prop = prop.strip().lower()
            value = value.strip()
            if prop in IGNORED_PROPS:
                continue
            if prop not in INLINEABLE_PROPS:
                continue
            resolved = _resolve_value(value, variables)
            declarations[INLINEABLE_PROPS[prop]] = resolved

        # If multiple classes appear in a single selector (".foo.bar"), apply
        # the declarations to each of them so any element with either class
        # picks them up.
        for cname in class_names:
            rules.setdefault(cname, {}).update(declarations)

    return rules


# ---------------------------------------------------------------------------
# SVG extraction & inlining
# ---------------------------------------------------------------------------


def collect_styles(soup: BeautifulSoup) -> str:
    """Return the concatenated text content of every <style> tag in the document."""
    parts = []
    for style in soup.find_all("style"):
        if style.string:
            parts.append(style.string)
    return "\n".join(parts)


def _resolve_attribute_value(value, variables: dict, _depth: int = 0) -> str:
    """Resolve var(--xxx) references inside any string-valued attribute.

    Accepts either a string or a list of strings (BeautifulSoup returns multi-valued
    attrs like class/style as lists); non-string entries are returned as-is.
    """
    if _depth > 5:
        return value
    if isinstance(value, list):
        return [_resolve_attribute_value(v, variables, _depth + 1) for v in value]
    if not isinstance(value, str):
        return value
    if not variables:
        return value

    def repl(match: re.Match) -> str:
        name = match.group(1)
        if name in variables:
            return _resolve_attribute_value(variables[name], variables, _depth + 1)
        return match.group(0)

    return _VAR_REF_RE.sub(repl, value)


def inline_class_styles(svg, class_rules: dict) -> None:
    """Walk every element in the SVG and inline class-bound styles.

    Inline presentation attributes already set on the element take precedence
    over class-bound styles. Multi-class elements get styles from every class
    (later classes win, matching CSS source order for single-selector rules).
    """
    for el in svg.find_all(True):
        class_attr = el.get("class")
        if not class_attr:
            continue
        # bs4 returns class attribute as a list when parsed via lxml/html.parser;
        # normalize to a list of string tokens either way.
        if isinstance(class_attr, list):
            class_names = [str(c).strip() for c in class_attr if str(c).strip()]
        else:
            class_names = [c for c in str(class_attr).split() if c]
        if not class_names:
            continue
        merged: dict[str, str] = {}
        for cname in class_names:
            if cname in class_rules:
                merged.update(class_rules[cname])
        for attr, value in merged.items():
            # Don't clobber attributes already explicitly set on the element.
            if attr in el.attrs:
                continue
            el[attr] = value


def strip_unsupported_attrs(svg) -> None:
    """Remove CSS classes, data-*, style, and other attrs the whiteboard can't parse."""
    for el in svg.find_all(True):
        if "class" in el.attrs:
            del el["class"]
        if "style" in el.attrs:
            # Strip style too — we have already inlined everything we need.
            del el["style"]
        for attr in list(el.attrs):
            if attr.startswith("data-"):
                del el[attr]
            elif attr == "xmlns:xlink":
                del el[attr]


def extract_svg(html_path: str) -> str:
    """Extract, clean, and inline the SVG from a diagram-maker HTML file."""
    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()

    soup = BeautifulSoup(html, "lxml")

    svg = soup.find("svg")
    if svg is None:
        raise ValueError(
            "No <svg> element found in HTML. Is this a diagram-maker output?"
        )

    # Normalize root attributes. BeautifulSoup lowercases attribute names, so
    # we compare case-insensitively against the whitelist.
    keep = {"xmlns", "viewbox", "viewBox", "width", "height"}
    for attr in list(svg.attrs):
        if attr not in keep:
            del svg.attrs[attr]
    # Ensure a viewBox is present so the whiteboard renderer can size the SVG.
    # BeautifulSoup lowercases the attribute name, so we have to re-emit it
    # with the original camelCase spelling — both cairosvg and the whiteboard
    # parser only recognize `viewBox` (not `viewbox`).
    if "viewBox" in svg.attrs:
        pass
    elif "viewbox" in svg.attrs:
        svg["viewBox"] = svg.attrs.pop("viewbox")
    else:
        width = svg.attrs.get("width", "800")
        height = svg.attrs.get("height", "600")
        try:
            svg["viewBox"] = f"0 0 {int(float(width))} {int(float(height))}"
        except (TypeError, ValueError):
            svg["viewBox"] = "0 0 800 600"
    if "xmlns" not in svg.attrs:
        svg["xmlns"] = "http://www.w3.org/2000/svg"

    # Parse styles, then inline class-bound declarations as presentation attrs.
    css_text = collect_styles(soup)
    variables = parse_css_variables(css_text)
    class_rules = parse_class_rules(css_text, variables)

    inline_class_styles(svg, class_rules)
    strip_unsupported_attrs(svg)

    # Resolve any remaining var(--xxx) literals in element attributes (e.g.
    # `fill="var(--line)"` written directly on a marker child path). The
    # whiteboard parser does not understand CSS variables, so we substitute
    # them with their resolved light-theme values.
    if variables:
        for el in svg.find_all(True):
            for attr in list(el.attrs):
                el[attr] = _resolve_attribute_value(el[attr], variables)

    return str(svg)


def clean_for_whiteboard(svg_str: str) -> str:
    """Post-process the SVG string for whiteboard compatibility."""
    # Drop HTML comments.
    svg_str = re.sub(r"<!--.*?-->", "", svg_str, flags=re.DOTALL)
    # Collapse blank lines.
    lines = [line for line in svg_str.split("\n") if line.strip()]
    return "\n".join(lines)


def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <input.html> <output.svg>")
        sys.exit(1)

    input_path = sys.argv[1]
    output_path = sys.argv[2]

    try:
        svg = extract_svg(input_path)
        svg = clean_for_whiteboard(svg)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(svg)
        print(f"✅ SVG written to {output_path}")
    except ValueError as e:
        print(f"❌ {e}")
        print(
            "Tip: If the HTML does not contain an embedded <svg>, you may need "
            "to manually construct the SVG from the HTML structure."
        )
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
