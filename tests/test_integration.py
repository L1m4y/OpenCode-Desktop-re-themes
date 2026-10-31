from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from oc_theme.asar import integrity_for, write_archive

ROOT = Path(__file__).resolve().parents[1]

FAKE_MAIN = """\
var light={palette:{neutral:`#f7f7f7`,ink:`#171311`,primary:`#dcde8d`,success:`#12c905`,warning:`#ffdc17`,error:`#fc533a`,info:`#a753ae`,interactive:`#034cff`,diffAdd:`#9ff29a`,diffDelete:`#fc533a`},overrides:{"border-weak-base":`#DBDBDB`},v2Overrides:{"v2-grey-800":`#e0e0e0ff`}};
var dark={palette:{neutral:`#1f1f1f`,ink:`#f1ece8`,primary:`#fab283`,success:`#12c905`,warning:`#fcd53a`,error:`#fc533a`,info:`#edb2f1`,interactive:`#034cff`,diffAdd:`#c8ffc4`,diffDelete:`#fc533a`},overrides:{"border-weak-base":`#282828`},v2Overrides:{"v2-grey-800":`#3a3a3aff`}};
var map={"./themes/amoled.json":()=>Q(()=>import(`./amoled-abc.js`),[],import.meta.url)};
var reg={"oc-2":`OpenCode`,amoled:`AMOLED`};
function izt(){return document.getElementById("oc-theme")}
function apply(n){var s="";var t="amoled";izt().textContent=s,document.documentElement.dataset.theme=t,document.documentElement.dataset.colorScheme=n}
"""


def make_source(directory: str, modified: bool = False) -> Path:
    main_bytes = FAKE_MAIN.encode("utf-8")
    files = [
        (
            "package.json",
            json.dumps({"name": "@opencode/desktop", "version": "2.2.5"}).encode("utf-8"),
        ),
        ("out/main/index.js", b'console.log("main");'),
        ("out/renderer/oc-theme-preload.js", b";(function(){})();"),
        ("out/renderer/assets/main-test.js", main_bytes),
    ]
    header: dict = {"files": {}}
    payload = bytearray()
    offset = 0
    for path, data in files:
        parts = path.split("/")
        node = header
        for part in parts[:-1]:
            node = node.setdefault("files", {}).setdefault(part, {"files": {}})
        entry = {"size": len(data), "offset": str(offset)}
        if path == "out/renderer/assets/main-test.js":
            entry["integrity"] = integrity_for(b"other" if modified else main_bytes)
        else:
            entry["integrity"] = integrity_for(data)
        node.setdefault("files", {})[parts[-1]] = entry
        payload += data
        offset += len(data)
    source = Path(directory) / "source.asar"
    write_archive(source, header, bytes(payload), 3)
    return source


class IntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        if shutil.which("node") is None:
            self.skipTest("node is not installed")

    def test_build_and_verify(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = make_source(temporary)
            output = Path(temporary) / "app-graphite.asar"
            work = Path(temporary) / "work"
            build = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "oc_theme",
                    "build",
                    "--asar",
                    str(source),
                    "--output",
                    str(output),
                    "--work",
                    str(work),
                ],
                capture_output=True,
                text=True,
                check=False,
                cwd=ROOT,
            )
            self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
            self.assertTrue(output.exists())

            verify = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "oc_theme",
                    "verify",
                    "--asar",
                    str(output),
                    "--original",
                    str(source),
                    "--theme-id",
                    "graphite",
                ],
                capture_output=True,
                text=True,
                check=False,
                cwd=ROOT,
            )
            self.assertEqual(verify.returncode, 0, verify.stdout + verify.stderr)

    def test_modified_source_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = make_source(temporary, modified=True)
            output = Path(temporary) / "app-graphite.asar"
            build = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "oc_theme",
                    "build",
                    "--asar",
                    str(source),
                    "--output",
                    str(output),
                    "--work",
                    str(Path(temporary) / "work"),
                ],
                capture_output=True,
                text=True,
                check=False,
                cwd=ROOT,
            )
            self.assertNotEqual(build.returncode, 0)
            self.assertIn("modified", build.stderr)


if __name__ == "__main__":
    unittest.main()
