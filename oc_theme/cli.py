"""Command-line interface for building and verifying the theme patch."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import shutil
import subprocess
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from . import __version__
from .asar import (
    DEFAULT_BLOCK_SIZE,
    Archive,
    AsarError,
    find_renderer_main,
    get_node,
    integrity_for,
    source_status,
    write_archive,
)
from .patch import PatchError, patch_main, theme_ids
from .theme import (
    ThemeConfig,
    ThemeError,
    build_theme_module,
    extract_theme_parts,
    flat_css,
)
from .tokens import CLASSIC_FLAT_TOKENS, V2_FLAT_TOKENS
from .verify import Check, verify_archive

DEFAULT_ASAR = Path("/usr/lib/opencode-desktop/app.asar")
DEFAULT_WORK = Path("build")
DEFAULT_BACKUP_DIR = Path("backups")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def print_checks(checks: list[Check]) -> None:
    width = max((len(check.name) for check in checks), default=0)
    for check in checks:
        status = "ok" if check.ok else "FAIL"
        print(f"  [{status:4}] {check.name:<{width}}  {check.detail}")


def run_node_check(path: Path) -> None:
    node = shutil.which("node")
    if node is None:
        raise SystemExit(
            "node is required to validate the generated JavaScript. "
            "Install Node.js 20+ or pass --skip-node-check."
        )
    result = subprocess.run(
        [node, "--check", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(f"node --check failed for {path}:\n{result.stderr.strip()}")


def cmd_info(args: argparse.Namespace) -> int:
    with Archive(args.asar) as archive:
        package = archive.package()
        main_path = find_renderer_main(archive.header.json)
        main = archive.read(main_path).decode("utf-8")
        clean, detail = source_status(archive)
        payload = {
            "archive": str(archive.path),
            "size": archive.path.stat().st_size,
            "package": package.get("name"),
            "version": package.get("version"),
            "pad": archive.header.pad,
            "json_bytes": archive.header.d,
            "payload_offset": archive.header.base,
            "main": main_path,
            "source": {True: "clean", False: "modified", None: "unknown"}[clean],
            "source_detail": detail,
            "themes": theme_ids(main),
        }
        if args.json:
            print(json.dumps(payload, indent=2))
            return 0
        print(f"archive:        {payload['archive']}")
        print(f"package:        {payload['package']} {payload['version']}")
        print(f"size:           {payload['size']} bytes")
        print(
            f"header:         pad={payload['pad']} "
            f"json={payload['json_bytes']} bytes payload={payload['payload_offset']}"
        )
        print(f"renderer main:  {payload['main']}")
        print(f"source:         {payload['source']} ({payload['source_detail']})")
        print(f"themes ({len(payload['themes'])}): {', '.join(payload['themes'])}")
        if clean is False:
            print(
                "\nwarning: this archive is already modified. Reinstall the official "
                "package before building, or pass --force to build on top of it.",
                file=sys.stderr,
            )
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    config = ThemeConfig(
        theme_id=args.theme_id,
        theme_name=args.theme_name,
        base_color=args.base_color,
        text_color=args.text_color,
        render_shift=args.render_shift,
    )
    config.validate()

    source = Path(args.asar)
    work = Path(args.work)
    output = Path(args.output) if args.output else work / f"app-{config.theme_id}.asar"
    if output.resolve() == source.resolve():
        raise SystemExit("output must be different from the source archive")
    work.mkdir(parents=True, exist_ok=True)

    with Archive(source) as archive:
        package = archive.package()
        version = package.get("version", "unknown")
        clean, detail = source_status(archive)
        print(f"source:  {source}")
        print(f"package: {package.get('name')} {version}")
        status = {True: "clean", False: "modified", None: "unknown"}[clean]
        print(f"source:  {status} ({detail})")
        if clean is False and not args.force:
            raise SystemExit(
                "the source archive is already modified. Reinstall the official "
                "package, or pass --force if you know what you are doing."
            )
        if clean is None:
            print("warning: no integrity hash; cannot prove the source is clean")

        main_path = find_renderer_main(archive.header.json)
        main = archive.read(main_path).decode("utf-8")
        parts = extract_theme_parts(main)
        module = build_theme_module(parts, config)
        css = flat_css(config)
        patched = patch_main(main, config, css, force=args.force)

        main_file = work / "main-patched.mjs"
        theme_file = work / f"{config.theme_id}.mjs"
        main_file.write_text(patched, encoding="utf-8")
        theme_file.write_text(module, encoding="utf-8")
        if not args.skip_node_check:
            run_node_check(main_file)
            run_node_check(theme_file)

        new_header = copy.deepcopy(archive.header.json)
        payload = bytearray()
        offset = 0
        for path, entry in archive.entries:
            if "offset" not in entry:
                continue
            data = patched.encode("utf-8") if path == main_path else archive.read(path)
            node = get_node(new_header, path)
            node["offset"] = str(offset)
            node["size"] = len(data)
            block_size = entry.get("integrity", {}).get("blockSize", DEFAULT_BLOCK_SIZE)
            node["integrity"] = integrity_for(data, block_size)
            payload += data
            offset += len(data)

        chunk_name = f"{config.theme_id}.js"
        chunk_bytes = module.encode("utf-8")
        assets = get_node(new_header, "out/renderer/assets")["files"]
        assets[chunk_name] = {
            "size": len(chunk_bytes),
            "offset": str(offset),
            "integrity": integrity_for(chunk_bytes),
        }
        payload += chunk_bytes

        print(f"theme:   {config.theme_id} ({config.theme_name})")
        print(f"main:    {len(main)} -> {len(patched)} bytes")
        print(f"chunk:   {len(chunk_bytes)} bytes")
        print(f"payload: {len(payload)} bytes")
        print(f"output:  {output}")

        if args.dry_run:
            print("dry run: archive not written")
            return 0

        write_archive(output, new_header, bytes(payload), archive.header.pad)
        print(f"file:    {output} ({output.stat().st_size} bytes)")
        print(f"sha256:  {sha256_file(output)}")

    if not args.no_verify:
        checks = verify_archive(
            output,
            original=source,
            theme_id=config.theme_id,
            node_check=not args.skip_node_check,
        )
        print("\nverification:")
        print_checks(checks)
        if not all(check.ok for check in checks):
            return 1
    print("\ndone")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    checks = verify_archive(
        args.asar,
        original=args.original,
        theme_id=args.theme_id,
        node_check=not args.no_node_check,
        deep=args.deep,
    )
    if args.json:
        print(json.dumps([asdict(check) for check in checks], indent=2))
    else:
        print_checks(checks)
    return 0 if all(check.ok for check in checks) else 1


def cmd_extract(args: argparse.Namespace) -> int:
    with Archive(args.asar) as archive:
        data = archive.read(args.path)
    output = Path(args.output) if args.output else Path(args.path).name
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(data)
    print(f"{args.path} -> {output} ({len(data)} bytes)")
    return 0


def cmd_backup(args: argparse.Namespace) -> int:
    source = Path(args.asar)
    with Archive(source) as archive:
        package = archive.package()
        version = package.get("version", "unknown")
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    output = Path(args.output) if args.output else DEFAULT_BACKUP_DIR / f"app.asar.{timestamp}"
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, output)
    print(f"backup: {output}")
    print(f"version: {version}")
    print(f"sha256: {sha256_file(output)}")
    return 0


def cmd_restore(args: argparse.Namespace) -> int:
    backup = Path(args.backup)
    target = Path(args.target)
    with Archive(backup) as archive:
        package = archive.package()
        version = package.get("version", "unknown")
    print(f"backup: {backup} ({package.get('name')} {version})")
    print(f"target: {target}")
    if args.dry_run:
        print("dry run: target not written")
        return 0
    if not args.yes:
        raise SystemExit("pass --yes to overwrite the target archive")
    shutil.copy2(backup, target)
    print(f"restored: {target}")
    return 0


def cmd_tokens(_: argparse.Namespace) -> int:
    print("# classic")
    print("\n".join(CLASSIC_FLAT_TOKENS))
    print("\n# v2")
    print("\n".join(V2_FLAT_TOKENS))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="oc-theme",
        description="Build and verify a custom OpenCode Desktop theme.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    info = subparsers.add_parser("info", help="inspect the installed archive")
    info.add_argument("--asar", default=str(DEFAULT_ASAR))
    info.add_argument("--json", action="store_true")
    info.set_defaults(func=cmd_info)

    build = subparsers.add_parser("build", help="build a patched archive")
    build.add_argument("--asar", default=str(DEFAULT_ASAR))
    build.add_argument("--work", default=str(DEFAULT_WORK))
    build.add_argument("--output", default=None)
    build.add_argument("--theme-id", default="graphite")
    build.add_argument("--theme-name", default="Graphite")
    build.add_argument("--base-color", default="#323232")
    build.add_argument("--text-color", default="#EDEDED")
    build.add_argument("--render-shift", type=int, default=3)
    build.add_argument("--force", action="store_true")
    build.add_argument("--dry-run", action="store_true")
    build.add_argument("--skip-node-check", action="store_true")
    build.add_argument("--no-verify", action="store_true")
    build.set_defaults(func=cmd_build)

    verify = subparsers.add_parser("verify", help="verify an archive and its patch")
    verify.add_argument("--asar", required=True)
    verify.add_argument("--original", default=None)
    verify.add_argument("--theme-id", default=None)
    verify.add_argument("--no-node-check", action="store_true")
    verify.add_argument("--deep", action="store_true")
    verify.add_argument("--json", action="store_true")
    verify.set_defaults(func=cmd_verify)

    extract = subparsers.add_parser("extract", help="extract one file from an archive")
    extract.add_argument("--asar", required=True)
    extract.add_argument("--path", required=True)
    extract.add_argument("--output", default=None)
    extract.set_defaults(func=cmd_extract)

    backup = subparsers.add_parser("backup", help="copy the installed archive")
    backup.add_argument("--asar", default=str(DEFAULT_ASAR))
    backup.add_argument("--output", default=None)
    backup.set_defaults(func=cmd_backup)

    restore = subparsers.add_parser("restore", help="restore an archive from a backup")
    restore.add_argument("--backup", required=True)
    restore.add_argument("--target", default=str(DEFAULT_ASAR))
    restore.add_argument("--yes", action="store_true")
    restore.add_argument("--dry-run", action="store_true")
    restore.set_defaults(func=cmd_restore)

    tokens = subparsers.add_parser("tokens", help="print the flattened token lists")
    tokens.set_defaults(func=cmd_tokens)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except (AsarError, PatchError, ThemeError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
