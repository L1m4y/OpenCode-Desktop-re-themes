"""Minimal, strict reader/writer for the ASAR variant used by OpenCode Desktop.

The format is the Chromium Pickle envelope described by @electron/asar, with one
observable difference in the archives this project targets: the two size fields
include the zero padding that follows the JSON header.  The relationships are:

    a = 4
    b = len(json) + 8 + pad
    c = len(json) + 4 + pad
    d = len(json)

The payload starts at ``16 + d + pad``.  ``pad`` is detected from the header and
is never assumed; the versions observed so far use 0..3 bytes.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import struct
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MAGIC = 4
DEFAULT_BLOCK_SIZE = 4 * 1024 * 1024
HEADER_STRUCT = struct.Struct("<IIII")
MAIN_RE = re.compile(r"out/renderer/assets/main-[\w.-]+\.js")


class AsarError(Exception):
    """Raised when an archive is malformed or cannot be handled safely."""


@dataclass(frozen=True)
class Header:
    a: int
    b: int
    c: int
    d: int
    pad: int
    base: int
    json: dict[str, Any]


def read_header(stream: Any) -> Header:
    """Read and validate the 16-byte Pickle header plus the JSON header."""
    raw = stream.read(16)
    if len(raw) != 16:
        raise AsarError("archive is shorter than the 16-byte header")
    a, b, c, d = HEADER_STRUCT.unpack(raw)
    if a != MAGIC:
        raise AsarError(f"unexpected first header value: {a} (expected {MAGIC})")

    pad = b - d - 8
    if pad < 0 or pad > 16:
        raise AsarError(f"implausible header padding: {pad}")
    if b != d + 8 + pad:
        raise AsarError("header field b does not match len(json) + 8 + pad")
    if c != d + 4 + pad:
        raise AsarError("header field c does not match len(json) + 4 + pad")

    stream.seek(16)
    raw_json = stream.read(d)
    if len(raw_json) != d:
        raise AsarError("archive ends inside the JSON header")
    try:
        header = json.loads(raw_json.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AsarError(f"invalid JSON header: {exc}") from exc

    padding = stream.read(pad)
    if padding != b"\x00" * pad:
        raise AsarError("header padding is not zero-filled")

    return Header(a=a, b=b, c=c, d=d, pad=pad, base=16 + d + pad, json=header)


def walk(node: dict[str, Any], prefix: str = "") -> Iterator[tuple[str, dict[str, Any]]]:
    """Yield ``(path, entry)`` for every leaf in the ASAR file tree."""
    for name, value in node.get("files", {}).items():
        path = f"{prefix}/{name}" if prefix else name
        if "files" in value:
            yield from walk(value, path)
        else:
            yield path, value


def get_node(header: dict[str, Any], path: str) -> dict[str, Any]:
    """Return the header node for ``path`` (a file or a directory)."""
    node = header
    for part in path.split("/"):
        try:
            node = node["files"][part]
        except KeyError as exc:
            raise AsarError(f"missing archive path: {path}") from exc
    return node


def integrity_for(data: bytes, block_size: int = DEFAULT_BLOCK_SIZE) -> dict[str, Any]:
    """Build the ASAR ``integrity`` object for a file payload."""
    if block_size <= 0:
        raise AsarError("integrity block size must be positive")
    digest = hashlib.sha256(data).hexdigest()
    blocks = [
        hashlib.sha256(data[index : index + block_size]).hexdigest()
        for index in range(0, len(data), block_size)
    ]
    return {
        "algorithm": "SHA256",
        "hash": digest,
        "blockSize": block_size,
        "blocks": blocks or [digest],
    }


def validate_entry_types(header: dict[str, Any]) -> list[str]:
    """Return a list of type problems for entries that live inside the archive."""
    problems: list[str] = []
    for path, entry in walk(header):
        if "offset" not in entry:
            continue
        if not isinstance(entry.get("size"), int):
            problems.append(f"{path}: size is not an integer")
        if not isinstance(entry.get("offset"), str):
            problems.append(f"{path}: offset is not a string")
        if "integrity" in entry and not isinstance(entry["integrity"], dict):
            problems.append(f"{path}: integrity is not an object")
    return problems


def payload_ranges(header: dict[str, Any]) -> list[tuple[int, int, str]]:
    """Return ``(start, end, path)`` for every entry stored in the archive."""
    ranges: list[tuple[int, int, str]] = []
    for path, entry in walk(header):
        if "offset" not in entry:
            continue
        start = int(entry["offset"])
        end = start + int(entry["size"])
        ranges.append((start, end, path))
    return ranges


def validate_coverage(header: dict[str, Any], payload_size: int) -> list[str]:
    """Validate that the entry ranges cover the payload without partial overlaps.

    Exact duplicate ranges are allowed because @electron/asar deduplicates files
    with identical contents.  Gaps and partial overlaps are not.
    """
    problems: list[str] = []
    ranges = sorted(payload_ranges(header))
    if not ranges:
        return ["archive has no payload entries"] if payload_size else []

    cursor = 0
    for start, end, path in ranges:
        if start < 0 or end < start:
            problems.append(f"{path}: invalid range {start}..{end}")
            continue
        if end > payload_size:
            problems.append(f"{path}: range ends past the payload ({end} > {payload_size})")
        if start > cursor:
            problems.append(f"{path}: gap between {cursor} and {start}")
        elif start < cursor and end > cursor:
            problems.append(f"{path}: partial overlap at {cursor}")
        cursor = max(cursor, end)

    if cursor != payload_size:
        problems.append(f"payload coverage ends at {cursor}, file has {payload_size} bytes")
    return problems


def write_archive(path: Path, header: dict[str, Any], payload: bytes, pad: int) -> int:
    """Write an archive atomically and return the header JSON length."""
    if pad < 0:
        raise AsarError("padding cannot be negative")
    encoded = json.dumps(header, separators=(",", ":")).encode("utf-8")
    length = len(encoded)
    region = (
        HEADER_STRUCT.pack(MAGIC, length + 8 + pad, length + 4 + pad, length)
        + encoded
        + b"\x00" * pad
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("wb") as stream:
        stream.write(region)
        stream.write(payload)
    os.replace(temporary, path)
    return length


class Archive:
    """Read-only view over an ASAR archive."""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path)
        self._stream = self.path.open("rb")
        try:
            self.header = read_header(self._stream)
        except Exception:
            self._stream.close()
            raise
        self.entries = list(walk(self.header.json))
        self.entry_map = {path: entry for path, entry in self.entries}

    def close(self) -> None:
        self._stream.close()

    def __enter__(self) -> Archive:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def entry(self, path: str) -> dict[str, Any]:
        try:
            return self.entry_map[path]
        except KeyError as exc:
            raise AsarError(f"missing archive path: {path}") from exc

    def read(self, path: str) -> bytes:
        entry = self.entry(path)
        if "offset" not in entry:
            raise AsarError(f"{path} is unpacked and cannot be read from the archive")
        self._stream.seek(self.header.base + int(entry["offset"]))
        data = self._stream.read(int(entry["size"]))
        if len(data) != int(entry["size"]):
            raise AsarError(f"short read for {path}")
        return data

    def package(self) -> dict[str, Any]:
        try:
            return json.loads(self.read("package.json").decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AsarError(f"invalid package.json: {exc}") from exc

    def payload_size(self) -> int:
        return self.path.stat().st_size - self.header.base


def find_renderer_main(header: dict[str, Any]) -> str:
    """Return the single renderer ``main-*.js`` chunk."""
    candidates = [path for path, _ in walk(header) if MAIN_RE.fullmatch(path)]
    if len(candidates) != 1:
        raise AsarError(
            "expected exactly one out/renderer/assets/main-*.js chunk, "
            f"found {len(candidates)}: {candidates}"
        )
    return candidates[0]


def source_status(archive: Archive) -> tuple[bool | None, str]:
    """Compare the renderer main entry against its recorded integrity hash.

    Returns ``(True, ...)`` for a clean archive, ``(False, ...)`` for a modified
    one, and ``(None, ...)`` when the archive does not carry an integrity hash.
    """
    main_path = find_renderer_main(archive.header.json)
    entry = archive.entry(main_path)
    recorded = entry.get("integrity", {}).get("hash")
    if not isinstance(recorded, str):
        return None, "renderer main has no integrity hash"
    actual = hashlib.sha256(archive.read(main_path)).hexdigest()
    if actual == recorded:
        return True, f"{main_path} matches its integrity hash"
    return False, f"{main_path} does not match its integrity hash"
