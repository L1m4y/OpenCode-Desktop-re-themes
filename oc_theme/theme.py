"""Theme extraction and generation.

The builder reuses the palettes and override blocks that OpenCode Desktop ships
in its renderer bundle.  It does not re-implement the theme compiler; it only
adds a new theme object and a stylesheet that flattens the visible surfaces.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from .tokens import CLASSIC_FLAT_TOKENS, PALETTE_KEYS, V2_FLAT_TOKENS

LIGHT_RE = re.compile(
    r"(?<![A-Za-z0-9$])([A-Za-z$][\w$]*)=\{palette:\{neutral:`#f7f7f7`"
)
DARK_RE = re.compile(
    r"(?<![A-Za-z0-9$])([A-Za-z$][\w$]*)=\{palette:\{neutral:`#1f1f1f`"
)
COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


class ThemeError(Exception):
    """Raised when the renderer bundle does not contain the expected theme data."""


@dataclass(frozen=True)
class ThemeConfig:
    theme_id: str = "graphite"
    theme_name: str = "Graphite"
    base_color: str = "#323232"
    text_color: str = "#EDEDED"
    render_shift: int = 3

    def validate(self) -> None:
        if not ID_RE.fullmatch(self.theme_id):
            raise ThemeError(
                "theme id must match ^[a-z0-9][a-z0-9-]*$ "
                f"(got {self.theme_id!r})"
            )
        if not self.theme_name.strip():
            raise ThemeError("theme name cannot be empty")
        if not COLOR_RE.fullmatch(self.base_color):
            raise ThemeError(f"base color must be #rrggbb (got {self.base_color!r})")
        if not COLOR_RE.fullmatch(self.text_color):
            raise ThemeError(f"text color must be #rrggbb (got {self.text_color!r})")
        if not 0 <= self.render_shift <= 32:
            raise ThemeError("render shift must be between 0 and 32")


@dataclass(frozen=True)
class ThemeParts:
    light_palette: str
    light_overrides: str
    light_v2_overrides: str
    dark_palette: str
    dark_overrides: str
    dark_v2_overrides: str


def extract_balanced(text: str, start: int) -> str:
    """Return the balanced ``{...}`` block that starts at ``start``.

    Template literals are treated as opaque strings, which is correct for the
    theme data.  The function is not a general JavaScript parser.
    """
    if start < 0 or start >= len(text) or text[start] != "{":
        raise ThemeError("expected an opening brace")
    depth = 0
    index = start
    quote: str | None = None
    escaped = False
    while index < len(text):
        char = text[index]
        if quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
        elif char in ("'", '"', "`"):
            quote = char
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
        index += 1
    raise ThemeError("unbalanced braces in the renderer bundle")


def seg_block(text: str, key: str) -> str:
    """Extract the object assigned to ``key`` from a JavaScript object literal."""
    match = re.search(rf"(?<![A-Za-z0-9$]){re.escape(key)}\s*:\s*\{{", text)
    if not match:
        raise ThemeError(f"missing {key!r} block in the renderer bundle")
    start = text.find("{", match.start())
    return extract_balanced(text, start)


def _extract_object(main: str, pattern: re.Pattern[str], label: str) -> str:
    match = pattern.search(main)
    if not match:
        raise ThemeError(
            f"could not locate the {label} theme object; the renderer layout changed"
        )
    start = main.find("{", match.start())
    return extract_balanced(main, start)


def extract_theme_parts(main: str) -> ThemeParts:
    """Extract the light and dark palette/override blocks from the main chunk."""
    light_object = _extract_object(main, LIGHT_RE, "light")
    dark_object = _extract_object(main, DARK_RE, "dark")

    light_palette = seg_block(light_object, "palette")
    for key in PALETTE_KEYS:
        if not re.search(rf"(?<![A-Za-z0-9$]){re.escape(key)}\s*:", light_palette):
            raise ThemeError(f"light palette is missing {key!r}")
    dark_palette = seg_block(dark_object, "palette")
    for key in PALETTE_KEYS:
        if not re.search(rf"(?<![A-Za-z0-9$]){re.escape(key)}\s*:", dark_palette):
            raise ThemeError(f"dark palette is missing {key!r}")

    return ThemeParts(
        light_palette=light_palette,
        light_overrides=seg_block(light_object, "overrides"),
        light_v2_overrides=seg_block(light_object, "v2Overrides"),
        dark_palette=dark_palette,
        dark_overrides=seg_block(dark_object, "overrides"),
        dark_v2_overrides=seg_block(dark_object, "v2Overrides"),
    )


def authored_color(target: str, shift: int) -> str:
    """Subtract the renderer shift from a target color.

    The renderer adds a small amount to flat dark surfaces.  Authoring the
    compensated value makes the rendered result land on ``target``.
    """
    if not COLOR_RE.fullmatch(target):
        raise ThemeError(f"invalid color: {target!r}")
    channels = [int(target[index : index + 2], 16) for index in (1, 3, 5)]
    compensated = [max(0, min(255, channel - shift)) for channel in channels]
    return "#" + "".join(f"{channel:02x}" for channel in compensated)


def flat_css(config: ThemeConfig) -> str:
    """Return the ``:root`` block that flattens both CSS layers."""
    color = authored_color(config.base_color, config.render_shift)
    classic = "".join(f"--{token}:{color}!important;" for token in CLASSIC_FLAT_TOKENS)
    v2 = "".join(f"--{token}:{color}ff!important;" for token in V2_FLAT_TOKENS)
    return f":root{{{classic}{v2}}}"


def build_theme_module(parts: ThemeParts, config: ThemeConfig) -> str:
    """Build a readable ES module that exports the six theme bindings."""
    color = authored_color(config.base_color, config.render_shift)
    classic = ",".join(f'"{token}":`{color}`' for token in CLASSIC_FLAT_TOKENS)
    v2 = ",".join(f'"{token}":`{color}ff`' for token in V2_FLAT_TOKENS)

    dark_palette = f"{{...({parts.dark_palette}),neutral:`{color}`,ink:`{config.text_color}`}}"
    dark_overrides = f"{{...({parts.dark_overrides}),{classic}}}"
    dark_v2_overrides = f"{{...({parts.dark_v2_overrides}),{v2}}}"

    light = (
        "{palette:"
        + parts.light_palette
        + ",overrides:"
        + parts.light_overrides
        + ",v2Overrides:"
        + parts.light_v2_overrides
        + "}"
    )
    dark = (
        "{palette:"
        + dark_palette
        + ",overrides:"
        + dark_overrides
        + ",v2Overrides:"
        + dark_v2_overrides
        + "}"
    )

    return (
        "// Generated by oc_theme. Do not edit by hand.\n"
        f'const $schema = "https://opencode.ai/desktop-theme.json";\n'
        f"const name = {json.dumps(config.theme_name)};\n"
        f"const id = {json.dumps(config.theme_id)};\n"
        f"const light = {light};\n"
        f"const dark = {dark};\n"
        "const theme = { $schema, name, id, light, dark };\n"
        "export { $schema, dark, theme as default, id, light, name };\n"
    )
