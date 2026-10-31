from __future__ import annotations

import hashlib
import struct
import tempfile
import unittest
from pathlib import Path

from oc_theme.asar import (
    Archive,
    AsarError,
    integrity_for,
    validate_coverage,
    validate_entry_types,
    write_archive,
)


def make_archive(directory: str, pad: int = 0) -> Path:
    header = {
        "files": {
            "a.txt": {"size": 5, "offset": "0"},
            "dir": {"files": {"b.txt": {"size": 3, "offset": "5"}}},
            "unpacked.txt": {"size": 4, "unpacked": True},
        }
    }
    path = Path(directory) / "test.asar"
    write_archive(path, header, b"helloabc", pad)
    return path


class AsarTests(unittest.TestCase):
    def test_round_trip_for_all_observed_padding(self) -> None:
        for pad in range(4):
            with self.subTest(pad=pad), tempfile.TemporaryDirectory() as temporary:
                path = make_archive(temporary, pad)
                with Archive(path) as archive:
                    self.assertEqual(archive.header.pad, pad)
                    self.assertEqual(archive.header.base, 16 + archive.header.d + pad)
                    self.assertEqual(archive.read("a.txt"), b"hello")
                    self.assertEqual(archive.read("dir/b.txt"), b"abc")
                    self.assertEqual(
                        validate_entry_types(archive.header.json),
                        [],
                    )
                    self.assertEqual(
                        validate_coverage(archive.header.json, archive.payload_size()),
                        [],
                    )

    def test_unpacked_entry_is_not_readable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = make_archive(temporary)
            with Archive(path) as archive:
                with self.assertRaises(AsarError):
                    archive.read("unpacked.txt")

    def test_invalid_magic_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "bad.asar"
            path.write_bytes(struct.pack("<IIII", 5, 8, 4, 0))
            with self.assertRaises(AsarError):
                Archive(path)

    def test_invalid_padding_relationship_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "bad.asar"
            path.write_bytes(struct.pack("<IIII", 4, 99, 98, 0))
            with self.assertRaises(AsarError):
                Archive(path)

    def test_deduplicated_ranges_are_allowed(self) -> None:
        header = {
            "files": {
                "a": {"size": 5, "offset": "0"},
                "b": {"size": 5, "offset": "0"},
            }
        }
        self.assertEqual(validate_coverage(header, 5), [])

    def test_gap_is_reported(self) -> None:
        header = {
            "files": {
                "a": {"size": 2, "offset": "0"},
                "b": {"size": 2, "offset": "4"},
            }
        }
        problems = validate_coverage(header, 6)
        self.assertTrue(any("gap" in problem for problem in problems))

    def test_integrity_uses_the_recorded_block_size(self) -> None:
        data = b"hello"
        result = integrity_for(data, block_size=4)
        self.assertEqual(result["hash"], hashlib.sha256(data).hexdigest())
        self.assertEqual(
            result["blocks"],
            [
                hashlib.sha256(b"hell").hexdigest(),
                hashlib.sha256(b"o").hexdigest(),
            ],
        )


if __name__ == "__main__":
    unittest.main()
