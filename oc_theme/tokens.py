"""CSS tokens flattened by the theme.

The classic layer and the v2 layer are generated separately by OpenCode Desktop.
The visible UI in 2.x is dominated by the v2 layer, so flattening only the
classic ``neutral`` slot is not enough.  Both lists below are written into the
theme object and into the injected stylesheet.
"""

from __future__ import annotations

CLASSIC_FLAT_TOKENS: tuple[str, ...] = (
    "background-base",
    "background-weak",
    "background-strong",
    "background-stronger",
    "surface-base",
    "surface-weak",
    "surface-weaker",
    "surface-strong",
    "surface-base-hover",
    "surface-base-active",
    "surface-raised-base",
    "surface-raised-base-hover",
    "surface-raised-base-active",
    "surface-raised-strong",
    "surface-raised-strong-hover",
    "surface-raised-stronger",
    "surface-raised-stronger-hover",
    "surface-raised-stronger-non-alpha",
    "surface-float-base",
    "surface-float-base-hover",
    "surface-inset-base",
    "surface-inset-base-hover",
    "surface-inset-strong",
    "surface-inset-strong-hover",
    "input-base",
    "input-hover",
    "input-active",
    "input-disabled",
    "border-base",
    "border-weak-base",
    "border-weaker-base",
    "border-strong-base",
    "base",
    "base2",
    "base3",
    "surface-diff-unchanged-base",
    "surface-diff-hidden-base",
    "surface-diff-hidden-strong",
    "surface-diff-hidden-stronger",
    "surface-diff-hidden-weak",
    "surface-diff-hidden-weaker",
    "surface-diff-skip-base",
    "markdown-code",
    "markdown-code-block",
)

V2_FLAT_TOKENS: tuple[str, ...] = (
    "v2-grey-800",
    "v2-grey-900",
    "v2-grey-1000",
    "v2-grey-1100",
    "v2-grey-1200",
    "v2-background-bg-base",
    "v2-background-bg-deep",
    "v2-background-bg-layer-01",
    "v2-background-bg-layer-02",
    "v2-background-bg-layer-03",
    "v2-background-bg-layer-04",
    "v2-border-border-muted",
    "v2-border-border-base",
    "v2-border-border-strong",
)

PALETTE_KEYS: tuple[str, ...] = (
    "neutral",
    "ink",
    "primary",
    "success",
    "warning",
    "error",
    "info",
    "interactive",
    "diffAdd",
    "diffDelete",
)
