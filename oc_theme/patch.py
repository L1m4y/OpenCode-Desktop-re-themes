"""Minimal, anchor-based patches for the OpenCode Desktop renderer bundle.

Three insertions are required:

1. a lazy import entry in the theme map;
2. a display name in the visible registry;
3. a stylesheet that flattens the classic and v2 surface tokens.

The patches are intentionally small.  The map and registry anchors are matched
by structure, and the wrapper name (``Q`` in 2.2.x, ``G`` in older builds) is
reused from the existing map instead of being hard-coded.
"""

from __future__ import annotations

import json
import re

from .theme import ThemeConfig


class PatchError(Exception):
    """Raised when the renderer bundle does not contain a safe patch anchor."""


THEME_MAP_RE = re.compile(
    r'"\./themes/[^"]+\.json"\s*:\s*\(\)\s*=>\s*([A-Za-z$][\w$]*)\s*'
    r"\(\s*\(\)\s*=>\s*import\(\s*`[^`]+`\s*\)\s*,\s*\[\]\s*,\s*import\.meta\.url\s*\)"
)
THEME_KEY_RE = re.compile(r'"\./themes/([^"]+)\.json"\s*:\s*\(\)\s*=>')
ASSIGN_RE = re.compile(
    r"([A-Za-z$][\w$]*\(\))\.textContent=([A-Za-z$][\w$]*)"
    r",document\.documentElement\.dataset\.theme=([A-Za-z$][\w$]*)"
    r",document\.documentElement\.dataset\.colorScheme=([A-Za-z$][\w$]*)"
)
REGISTRY_ANCHORS = ("amoled:`AMOLED`", "flexoki:`Flexoki`", '"oc-2":`OpenCode`')


def escape_template(value: str) -> str:
    """Escape a value that will be embedded in a JavaScript template literal."""
    return value.replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${")


def theme_ids(main: str) -> list[str]:
    """Return the theme ids declared by the lazy import map."""
    return sorted(set(THEME_KEY_RE.findall(main)))


def _remove_map_entry(main: str, theme_id: str) -> str:
    pattern = re.compile(
        r',?"\./themes/'
        + re.escape(theme_id)
        + r'\.json"\s*:\s*\(\)\s*=>\s*[A-Za-z$][\w$]*\s*'
        r"\(\s*\(\)\s*=>\s*import\(\s*`[^`]+`\s*\)\s*,\s*\[\]\s*,\s*import\.meta\.url\s*\)"
    )
    return pattern.sub("", main, count=1)


def insert_theme_map(main: str, theme_id: str, chunk_name: str, force: bool = False) -> str:
    """Add the lazy import entry after an existing theme entry."""
    if f'"./themes/{theme_id}.json"' in main:
        if not force:
            raise PatchError(f"theme map already contains {theme_id!r}")
        main = _remove_map_entry(main, theme_id)

    matches = list(THEME_MAP_RE.finditer(main))
    if not matches:
        raise PatchError("could not locate the lazy theme import map")
    anchor = next(
        (match for match in matches if "/amoled.json" in match.group(0)), matches[0]
    )
    wrapper = anchor.group(1)
    entry = (
        f',"./themes/{theme_id}.json":()=>{wrapper}('
        f"()=>import(`./{chunk_name}`),[],import.meta.url)"
    )
    return main[: anchor.end()] + entry + main[anchor.end() :]


def _remove_registry_entry(main: str, theme_id: str) -> str:
    pattern = re.compile(
        r',?\s*"?' + re.escape(theme_id) + r'"?\s*:\s*(`[^`]*`|"[^"]*")'
    )
    return pattern.sub("", main, count=1)


def insert_registry(
    main: str, theme_id: str, theme_name: str, force: bool = False
) -> str:
    """Add the display name to the registry with a quoted key.

    The previous builders inserted ``custom-theme:`Custom Theme```, which is a
    syntax error because the key contains a hyphen.  ``json.dumps`` produces a
    quoted key and a quoted value, both valid JavaScript.
    """
    entry_pattern = re.compile(
        r'"?' + re.escape(theme_id) + r'"?\s*:\s*(`[^`]*`|"[^"]*")'
    )
    if entry_pattern.search(main):
        if not force:
            raise PatchError(f"theme registry already contains {theme_id!r}")
        main = _remove_registry_entry(main, theme_id)

    anchor = next((candidate for candidate in REGISTRY_ANCHORS if candidate in main), None)
    if anchor is None:
        raise PatchError("could not locate the visible theme registry")
    entry = f"{json.dumps(theme_id)}:{json.dumps(theme_name)}"
    return main.replace(anchor, f"{anchor},{entry}", 1)


def remove_injection(main: str, theme_id: str) -> str:
    """Remove a previous stylesheet injection for ``theme_id``, if present.

    The optional groups keep this working on archives patched by an older build,
    which had no color-scheme guard and set a background color that the renderer
    overwrote immediately afterwards.
    """
    pattern = re.compile(
        r",?[A-Za-z$][\w$]*===`"
        + re.escape(theme_id)
        + r"`&&(?:[A-Za-z$][\w$]*===`dark`&&)?\([A-Za-z$][\w$]*\+=`.*?`"
        r"(?:,document\.documentElement\.style\.backgroundColor=`[^`]*`)?\)",
        re.S,
    )
    return pattern.sub("", main, count=1)


def insert_css(main: str, theme_id: str, css: str) -> str:
    """Insert the flattening stylesheet before the final stylesheet assignment.

    The injection is guarded by both the theme id and the color scheme.  The
    theme object only defines a flat dark variant, so applying its stylesheet in
    light mode would put light text on dark surfaces.
    """
    match = ASSIGN_RE.search(main)
    if not match:
        raise PatchError("could not locate the stylesheet assignment")
    _style_element, css_variable, theme_variable, scheme_variable = match.groups()
    injection = (
        f"{theme_variable}===`{theme_id}`&&{scheme_variable}===`dark`&&("
        f"{css_variable}+=`{escape_template(css)}`),"
    )
    return main[: match.start()] + injection + main[match.start() :]


def patch_main(
    main: str, config: ThemeConfig, css: str, force: bool = False
) -> str:
    """Apply the three renderer patches and return the new main chunk."""
    main = remove_injection(main, config.theme_id)
    main = insert_theme_map(main, config.theme_id, f"{config.theme_id}.js", force=force)
    main = insert_registry(main, config.theme_id, config.theme_name, force=force)
    return insert_css(main, config.theme_id, css)


def validate_patch(main: str, theme_id: str) -> list[str]:
    """Return a list of problems with the patched main chunk."""
    problems: list[str] = []
    if f'"./themes/{theme_id}.json"' not in main:
        problems.append("theme map entry is missing")
    if f"import(`./{theme_id}.js`)" not in main:
        problems.append("theme chunk import is missing")
    if f'"{theme_id}":' not in main:
        problems.append("registry entry is missing or its key is not quoted")
    if re.search(rf"(?<![A-Za-z0-9_$\"'-]){re.escape(theme_id)}\s*:", main):
        problems.append("registry contains an unquoted key with a hyphen")
    if main.count(f"===`{theme_id}`&&") != 1:
        problems.append("stylesheet injection is missing or duplicated")
    elif not re.search(rf"===`{theme_id}`&&[A-Za-z$][\w$]*===`dark`&&\(", main):
        problems.append("stylesheet injection is missing the dark color-scheme guard")
    if f"./themes/{theme_id}.json" in main and main.count(f'"./themes/{theme_id}.json"') != 1:
        problems.append("theme map entry is duplicated")
    return problems
