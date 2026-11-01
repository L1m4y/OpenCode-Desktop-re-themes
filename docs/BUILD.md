# Build and install

## Requirements

- Linux, with OpenCode Desktop installed at `/usr/lib/opencode-desktop/app.asar`.
  Pass `--asar` if your package uses a different path.
- Python 3.10 or newer.
- Node.js 20 or newer. The builder runs `node --check` on the generated files and
  refuses to continue without it unless you pass `--skip-node-check`.

No third-party Python packages are required.

## Inspect before building

```bash
python -m oc_theme info
```

The output includes the package version, the detected header padding, the
renderer main chunk and the source status. The source status compares the main
chunk against its recorded SHA-256 hash:

- `clean`: the archive matches its own integrity data.
- `modified`: something already changed the main chunk.
- `unknown`: the archive carries no hash for the main chunk.

Build only from a clean archive. If `info` reports `modified`, reinstall the
official package first. Building on top of a modified archive is possible with
`--force`, but the result inherits whatever the previous change did.

## Back up

```bash
python -m oc_theme backup
```

This copies the archive to `backups/app.asar.<timestamp>` and prints its SHA-256.
Keep that path; the restore command needs it.

## Build

```bash
python -m oc_theme build
```

Defaults:

| Option | Default | Meaning |
| --- | --- | --- |
| `--asar` | `/usr/lib/opencode-desktop/app.asar` | source archive |
| `--output` | `build/app-graphite.asar` | output archive |
| `--work` | `build` | directory for the generated JS files |
| `--theme-id` | `graphite` | id written to the map and registry |
| `--theme-name` | `Graphite` | display name in the theme picker |
| `--base-color` | `#323232` | target surface color |
| `--text-color` | `#EDEDED` | dark-mode text color |
| `--render-shift` | `3` | compensation for the renderer offset |

The build writes three files:

- `build/main-patched.mjs`, the patched renderer chunk;
- `build/<theme-id>.mjs`, the new theme module;
- `build/app-<theme-id>.asar`, the rebuilt archive.

The first two exist so you can inspect or diff what changed. They are not needed
to install the theme.

Use `--dry-run` to generate and validate the files without writing the archive.

## What the build verifies

The build runs the verifier automatically. It checks:

- header framing and padding;
- entry types and payload coverage;
- the package name and version;
- that exactly one renderer main chunk exists;
- that the three patch anchors are present and appear once;
- `node --check` on the patched main and the theme module;
- that the theme module exports the six expected bindings;
- that every untouched file is byte-identical to the source.

A failed check returns a non-zero exit code and leaves the archive uninstalled.
`python -m oc_theme verify --asar <file>` runs the same checks on an existing
archive without rebuilding it.

## Install

Close OpenCode Desktop from the tray first. Copying the archive while the app is
running can leave it with an old file handle.

```bash
sudo cp build/app-graphite.asar /usr/lib/opencode-desktop/app.asar
```

Open the app and pick **Graphite** in appearance settings. If the theme does not
appear, see `docs/TROUBLESHOOTING.md`.

## Restore

```bash
sudo python -m oc_theme restore --backup backups/app.asar.<timestamp> --yes
```

The restore command validates that the backup is a readable archive and prints
its version before copying. It refuses to overwrite the target without `--yes`.

## After a package update

An update replaces `app.asar`, so the theme disappears. The sequence is always:

1. `python -m oc_theme info` to confirm the new version and a clean source.
2. `python -m oc_theme build`.
3. Install the new output.

Do not reuse an archive built for a previous version. The main chunk filename
and its contents change between releases.

## Porting to a new release

The builder matches structure, not filenames, so most releases need no code
change. If an anchor moved, the build fails with a message naming the missing
piece:

- `could not locate the lazy theme import map`
- `could not locate the visible theme registry`
- `could not locate the stylesheet assignment`
- `could not locate the dark theme object`

Extract the main chunk and look at the area around the failing anchor:

```bash
python -m oc_theme extract --asar /usr/lib/opencode-desktop/app.asar \
  --path out/renderer/assets/main-<hash>.js \
  --output /tmp/main.mjs
```

Then update the corresponding pattern in `oc_theme/patch.py` or
`oc_theme/theme.py`. Keep the patterns structural: they should match the shape of
the code, not a specific minified identifier.

## Running the tests

```bash
python -m unittest discover -v
ruff check .
```

The integration tests build and verify a synthetic archive, so they do not need
OpenCode Desktop installed. They run the syntax checks when Node.js is on
`PATH` and skip them otherwise.
