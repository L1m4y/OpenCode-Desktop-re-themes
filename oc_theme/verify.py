"""Archive and patch verification."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .asar import (
    Archive,
    AsarError,
    find_renderer_main,
    validate_coverage,
    validate_entry_types,
)
from .patch import validate_patch


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str = ""


def _node_check(path: Path) -> Check:
    node = shutil.which("node")
    if node is None:
        return Check("node --check", False, "node is not installed")
    result = subprocess.run(
        [node, "--check", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    detail = result.stderr.strip() or result.stdout.strip()
    return Check(f"node --check {path.name}", result.returncode == 0, detail)


def _node_exports(path: Path) -> Check:
    node = shutil.which("node")
    if node is None:
        return Check("theme exports", False, "node is not installed")
    script = (
        "import(process.argv[1]).then((module) => {"
        "const keys = Object.keys(module).sort();"
        "console.log(JSON.stringify({keys, id: module.id, name: module.name}));"
        "}).catch((error) => {console.error(error.message); process.exit(1);})"
    )
    result = subprocess.run(
        [node, "--input-type=module", "-e", script, str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return Check("theme exports", False, result.stderr.strip())
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return Check("theme exports", False, result.stdout.strip())
    expected = {"$schema", "dark", "default", "id", "light", "name"}
    missing = sorted(expected - set(payload["keys"]))
    return Check(
        "theme exports",
        not missing,
        f"id={payload.get('id')} name={payload.get('name')} missing={missing}",
    )


def _compare_untouched(
    original: Archive, candidate: Archive, skip: set[str]
) -> Check:
    original_paths = {path for path, entry in original.entries if "offset" in entry}
    candidate_paths = {path for path, entry in candidate.entries if "offset" in entry}
    extra = sorted(candidate_paths - original_paths - skip)
    if extra:
        return Check("untouched files", False, f"unexpected extra files: {extra[:5]}")
    for path in sorted(original_paths - skip):
        if original.read(path) != candidate.read(path):
            return Check("untouched files", False, f"{path} changed")
    return Check("untouched files", True, f"compared {len(original_paths - skip)} files")


def _deep_integrity(archive: Archive) -> Check:
    problems: list[str] = []
    for path, entry in archive.entries:
        if "offset" not in entry:
            continue
        recorded = entry.get("integrity", {}).get("hash")
        if not isinstance(recorded, str):
            continue
        actual = hashlib.sha256(archive.read(path)).hexdigest()
        if actual != recorded:
            problems.append(path)
    detail = "all recorded hashes match" if not problems else f"mismatches: {problems[:5]}"
    return Check("integrity hashes", not problems, detail)


def verify_archive(
    path: str | Path,
    original: str | Path | None = None,
    theme_id: str | None = None,
    node_check: bool = True,
    deep: bool = False,
) -> list[Check]:
    """Verify an archive and, optionally, the theme patch inside it."""
    checks: list[Check] = []
    archive_path = Path(path)
    try:
        archive = Archive(archive_path)
    except (AsarError, OSError) as exc:
        return [Check("archive", False, str(exc))]

    with archive:
        checks.append(
            Check(
                "header framing",
                True,
                f"pad={archive.header.pad} json={archive.header.d} bytes",
            )
        )
        problems = validate_entry_types(archive.header.json)
        checks.append(Check("entry types", not problems, "; ".join(problems)))
        problems = validate_coverage(archive.header.json, archive.payload_size())
        checks.append(Check("payload coverage", not problems, "; ".join(problems)))

        try:
            package = archive.package()
            checks.append(
                Check(
                    "package",
                    package.get("name") == "@opencode/desktop",
                    f"{package.get('name')} {package.get('version')}",
                )
            )
        except AsarError as exc:
            checks.append(Check("package", False, str(exc)))

        main_path: str | None = None
        chunk_path: str | None = None
        try:
            main_path = find_renderer_main(archive.header.json)
            checks.append(Check("renderer main", True, main_path))
        except AsarError as exc:
            checks.append(Check("renderer main", False, str(exc)))

        if theme_id and main_path:
            chunk_path = f"out/renderer/assets/{theme_id}.js"
            main = archive.read(main_path).decode("utf-8")
            problems = validate_patch(main, theme_id)
            checks.append(Check("theme patch", not problems, "; ".join(problems)))
            if chunk_path in archive.entry_map:
                chunk = archive.read(chunk_path).decode("utf-8")
                has_id = bool(re.search(rf'const id = {re.escape(json.dumps(theme_id))};', chunk))
                has_default = "theme as default" in chunk
                checks.append(
                    Check(
                        "theme chunk",
                        has_id and has_default,
                        f"{chunk_path} ({len(chunk)} bytes)",
                    )
                )
            else:
                checks.append(Check("theme chunk", False, f"missing {chunk_path}"))

        if original:
            try:
                with Archive(original) as source:
                    skip = {value for value in (main_path, chunk_path) if value}
                    checks.append(_compare_untouched(source, archive, skip))
            except (AsarError, OSError) as exc:
                checks.append(Check("untouched files", False, str(exc)))

        if deep:
            checks.append(_deep_integrity(archive))

        if node_check and main_path:
            with tempfile.TemporaryDirectory(prefix="oc-theme-verify-") as temporary:
                directory = Path(temporary)
                main_file = directory / "main.mjs"
                main_file.write_bytes(archive.read(main_path))
                checks.append(_node_check(main_file))
                if chunk_path and chunk_path in archive.entry_map:
                    chunk_file = directory / f"{theme_id}.mjs"
                    chunk_file.write_bytes(archive.read(chunk_path))
                    checks.append(_node_check(chunk_file))
                    checks.append(_node_exports(chunk_file))

    return checks
