# Architecture

This document covers the parts of OpenCode Desktop that the builder touches: the
ASAR envelope, the theme pipeline in the renderer bundle, and the three patch
points. It is not a general guide to Electron internals.

## 1. ASAR envelope

OpenCode Desktop ships a flat `app.asar`. The archive starts with a Chromium
Pickle header: four unsigned 32-bit little-endian integers, followed by a JSON
header and the file payload.

```text
[u32 a][u32 b][u32 c][u32 d][JSON of d bytes][pad zero bytes][payload]
```

The relationships observed in the archives this project targets are:

```text
a = 4
b = len(json) + 8 + pad
c = len(json) + 4 + pad
d = len(json)
payload_offset = 16 + d + pad
```

`pad` is not an alignment assumption. It is read from the header
(`pad = b - d - 8`) and validated against `c`. The versions observed so far use
0 to 3 bytes. A real 2.2.5 archive starts with:

```text
4, 3113610, 3113606, 3113599
```

That gives `pad = 3` and `payload_offset = 3113618`.

`oc_theme/asar.py` rejects any archive whose header does not satisfy these
relationships, so a future format change fails loudly instead of producing a
corrupt file.

### File entries

Each leaf entry uses a numeric `size` and a textual `offset`. `offset` is a
string because it represents a UINT64 that JavaScript cannot represent exactly.
Entries with `unpacked: true` have no `offset` and live in `app.asar.unpacked`;
the builder copies them through untouched and the verifier skips their payload.

Entries may also carry an `integrity` object:

```json
{
  "algorithm": "SHA256",
  "hash": "<sha256 of the file bytes>",
  "blockSize": 4194304,
  "blocks": ["<sha256 of each block>"]
}
```

The builder recomputes these hashes for the patched main chunk and the new theme
chunk. It does not update the external header hash used by macOS and Windows code
signing, which is why this project is Linux-only.

### Rebuild rules

- Preserve every untouched file byte-for-byte.
- Rewrite offsets contiguously in file-tree order.
- Append the new theme chunk after the last file.
- Keep `size` numeric and `offset` textual.
- Write the JSON header compactly and keep the original padding.
- Write the result to a temporary file and rename it into place.

The verifier compares every untouched file against the source archive, checks
that entry ranges cover the payload without gaps, and validates the recorded
hashes.

## 2. Theme pipeline

Themes live in `out/renderer/assets/main-<hash>.js`. That chunk contains:

- a lazy import map keyed by `./themes/<id>.json`;
- a visible registry that maps ids to display names;
- a light object and a dark object, each with `palette`, `overrides` and
  `v2Overrides`;
- an `applyTheme`-style function that writes a stylesheet into a `<style>`
  element and sets `document.documentElement.dataset.theme`.

Each theme chunk exports six bindings: `$schema`, `name`, `id`, `light`, `dark`
and a `default` object that groups them.

The theme system has two CSS layers. The classic layer uses variables such as
`--background-base` and `--surface-raised-strong`. The v2 layer uses variables
such as `--v2-grey-800` and `--v2-background-bg-base`. The v2 layer dominates the
visible interface in 2.x, so flattening only the classic `neutral` slot leaves
most of the UI untouched.

`oc_theme/tokens.py` lists the tokens that the generated stylesheet overrides.
`python -m oc_theme tokens` prints the current lists.

The generated theme only defines a flat dark variant. Its `light` object is
copied from the stock theme, and the stylesheet injection is guarded by the color
scheme, so selecting Graphite in light mode leaves the default light appearance
intact.

## 3. Patch points

The builder applies three insertions to the main chunk.

### Lazy import map

The existing map looks like this:

```js
"./themes/amoled.json":()=>Q(()=>import(`./amoled-abc.js`),[],import.meta.url)
```

The builder appends one entry with the same wrapper function that the existing
entries use. Older builds used `G` instead of `Q`, so the wrapper is read from
the anchor rather than hard-coded.

### Visible registry

The registry is a plain object literal:

```js
var tzt={"oc-2":`OpenCode`,amoled:`AMOLED`,...}
```

The builder appends `"graphite":"Graphite"`. Both the key and the value are
quoted with `json.dumps`, which keeps hyphenated ids valid JavaScript. An
unquoted `graphite:` key is a syntax error, and that mistake is the reason the
old builder produced a broken bundle.

### Stylesheet injection

The theme application function builds the CSS string and assigns it to the
`<style>` element:

```js
izt().textContent=s,document.documentElement.dataset.theme=t,document.documentElement.dataset.colorScheme=n
```

The builder inserts a guarded prefix:

```js
t===`graphite`&&n===`dark`&&(s+=`:root{...}`),
```

The guard means the extra CSS is only added when the selected theme is ours and
the app is in dark mode, so other themes keep their original appearance and light
mode stays readable. The builder reads both variable names from the anchor; they
are not hard-coded.

An earlier version of this patch also set
`document.documentElement.style.backgroundColor` inside the injection. That
assignment was dead code: the renderer overwrites the same property immediately
after the injection point. It has been removed.

## 4. Data flow

```text
app.asar
  -> Archive.read(main)
  -> extract_theme_parts(main)      palettes and overrides
  -> build_theme_module(parts)      new theme chunk
  -> flat_css(config)               :root stylesheet
  -> patch_main(main, config, css)  three insertions
  -> write_archive(output)          new header, new payload
  -> verify_archive(output)         framing, coverage, syntax, exports
```

Every step raises a named exception (`AsarError`, `ThemeError`, `PatchError`)
with a message that points at the failing anchor. The CLI prints that message
and exits non-zero; it never writes an archive after a failed check.
