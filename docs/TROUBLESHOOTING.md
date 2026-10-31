# Troubleshooting

## `the source archive is already modified`

`info` compares the renderer main chunk against its recorded SHA-256 hash. A
mismatch means the archive was patched before, usually by an earlier build of
this project or by another tool.

Reinstall the official package:

```bash
# Linux example; use the equivalent for your package manager
sudo pacman -S opencode-desktop
```

Then run `python -m oc_theme info` again. If you are certain the existing
modification is harmless, pass `--force` to `build`.

## `theme map already contains 'graphite'`

The source archive already has a theme with that id. Either you are building on a
patched archive, or the id collides with a bundled theme. Use a different id:

```bash
python -m oc_theme build --theme-id my-theme --theme-name "My Theme"
```

`python -m oc_theme info` lists the ids that are already present.

## `could not locate the lazy theme import map`

The renderer no longer contains the expected `./themes/<id>.json` import
pattern. This usually means the package changed its theme loading strategy.

Extract the main chunk (see `docs/BUILD.md`) and search for `themes/`:

```bash
grep -o '\./themes/[a-z0-9-]*\.json' /tmp/main.mjs | head
```

If the pattern is gone, the patch approach needs to change. Do not force a build;
a missing anchor means the output would not register the theme.

## `node --check failed`

The generated JavaScript does not parse. The message includes the file and the
line/column from Node. Common causes:

- a theme id or name that breaks the surrounding syntax (use letters, digits and
  hyphens for ids);
- an anchor that matched more than the intended snippet, so the insertion landed
  inside a string or a comment.

Inspect `build/main-patched.mjs` around the reported position. The build does not
write the archive when this check fails.

## The theme is installed but not listed

Check that the archive in place is the one you built:

```bash
python -m oc_theme info
```

The theme list at the end of the output should include your id. If it does, and
the app still does not show it, close the app fully (including the tray icon) and
reopen it. Electron caches the renderer bundle for the lifetime of the process.

## The theme is listed but the interface is unchanged

Graphite is dark-only. In light mode the patch deliberately does nothing, so the
default light theme remains readable. Switch the app to dark mode to see it.

In dark mode, two possibilities:

1. The stylesheet injection did not apply. `verify` reports `theme patch` as
   failed if the guarded injection is missing or duplicated.
2. The app version renders surfaces through tokens that are not in the flattened
   list. Run `python -m oc_theme tokens` and compare with the CSS variables in the
   renderer's stylesheet.

The second case is a coverage gap, not a broken build. Add the missing variable
names to `CLASSIC_FLAT_TOKENS` or `V2_FLAT_TOKENS` in `oc_theme/tokens.py`.

## Colors are a few shades off

The renderer adds a small offset to flat dark surfaces. The default
`--render-shift 3` compensates for that, so `--base-color "#323232"` renders as
`#323232` instead of `#353535`. If a release changes the offset, adjust the
value. `--render-shift 0` disables compensation.

## The archive is huge and the build is slow

`app.asar` is around 235 MB and contains about 11,800 files. The builder reads
every file to preserve it byte-for-byte and to recompute integrity hashes, so a
build takes a few seconds and needs roughly twice the archive size in free disk
space. This is expected.

## `verify` reports `payload coverage`

The entry ranges do not cover the payload exactly. This points at a bug in the
writer or at a source archive with an unusual layout. The message names the first
problem range:

- `gap between X and Y`: no entry owns those bytes;
- `partial overlap`: two entries claim overlapping but not identical ranges;
- `range ends past the payload`: an entry points beyond the end of the file.

Exact duplicate ranges are allowed because the packer deduplicates identical
files.

## macOS and Windows

This project does not support them. Those builds are code-signed and validate the
ASAR header hash through a mechanism this tool does not update. Installing a
patched archive there will either be rejected or break the signature.

## Version log

| Version | Main chunk | Padding | Themes | Result |
| --- | --- | --- | --- | --- |
| 2.2.5 | `main-DH32_HOX.js` | 3 | 37 | Builds and verifies |
| 2.2.3 | — | — | — | Expected to work; run `info` first |
| 2.0.x | — | — | — | Older wrapper (`G`); the builder reads it from the anchor |

Only 2.2.5 has been tested end to end. For any other version, run `info` and
`build --dry-run` before touching the installed archive.
