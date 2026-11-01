# Contributing

## Before you start

This project patches a local application bundle. Changes that make the patch
less conservative, or that skip verification, are unlikely to be accepted.

## Development setup

```bash
git clone https://github.com/L1m4y/OpenCode-Desktop-re-themes.git
cd OpenCode-Desktop-re-themes
python -m unittest discover -v
ruff check .
```

Node.js 20+ is required for the tests that parse the generated JavaScript. Tests
that need it are skipped when `node` is not on `PATH`.

`ruff` is a development tool, not a runtime dependency. Install it with
`python -m pip install ruff` or `pipx install ruff`.

## What to test against

The integration tests build and verify a synthetic archive, so they run without
OpenCode Desktop installed. For changes to the patch anchors, also run against a
real installation:

```bash
python -m oc_theme info
python -m oc_theme build --dry-run
```

Report the package version and the main chunk filename in the pull request. The
anchor shapes are the part most likely to change between releases.

## Style

- Python 3.10+, standard library only. Do not add runtime dependencies.
- Keep functions small and name exceptions after what failed.
- Prefer structural regular expressions over minified identifiers.
- No silent fallbacks. If an anchor is missing, raise and let the CLI report it.
- Comments explain why a value exists, not what the next line does.

Run `ruff check .` before opening a pull request. The configuration lives in
`pyproject.toml`.

## Adding a token

If a surface is not flattened, add the CSS variable name to
`CLASSIC_FLAT_TOKENS` or `V2_FLAT_TOKENS` in `oc_theme/tokens.py`. Include the
version where you observed it and a screenshot or a short description of the
affected area.

## Documentation

Documentation is in `docs/`. Keep claims tied to something that was observed on a
real archive. If a version has not been tested, say so in the compatibility table
instead of implying support.

## Commits

One logical change per commit. A commit that fixes a patch anchor should include
the test or the manual check that shows the fix. Avoid mixing documentation
rewrites with code changes.

## License

By contributing you agree that your changes are licensed under GPL-3.0-or-later,
the same terms as the rest of the project.
