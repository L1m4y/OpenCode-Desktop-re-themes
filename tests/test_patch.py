from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from oc_theme.patch import patch_main, validate_patch
from oc_theme.theme import ThemeConfig

FAKE_MAIN = """\
var map={"./themes/amoled.json":()=>Q(()=>import(`./amoled-abc.js`),[],import.meta.url)};
var reg={"oc-2":`OpenCode`,amoled:`AMOLED`};
function izt(){return document.getElementById("oc-theme")}
function apply(n){var s="";var t="amoled";izt().textContent=s,document.documentElement.dataset.theme=t,document.documentElement.dataset.colorScheme=n}
"""

FAKE_MAIN_G = FAKE_MAIN.replace("Q(()=>import", "G(()=>import")


class PatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = ThemeConfig(theme_id="graphite", theme_name="Graphite")
        self.css = ":root{--background-base:#2f2f2f!important;}"

    def test_patch_inserts_map_registry_and_css(self) -> None:
        patched = patch_main(FAKE_MAIN, self.config, self.css, force=False)
        self.assertIn('"./themes/graphite.json":()=>Q(', patched)
        self.assertIn('"graphite":"Graphite"', patched)
        self.assertIn("t===`graphite`&&n===`dark`&&(s+=`", patched)
        self.assertEqual(validate_patch(patched, "graphite"), [])

    def test_registry_key_is_quoted(self) -> None:
        patched = patch_main(FAKE_MAIN, self.config, self.css, force=False)
        self.assertNotIn("graphite:`Graphite`", patched)
        self.assertIn('"graphite":"Graphite"', patched)

    def test_existing_wrapper_is_reused(self) -> None:
        patched = patch_main(FAKE_MAIN_G, self.config, self.css, force=False)
        self.assertIn("G(()=>import(`./graphite.js`)", patched)

    def test_patch_is_idempotent_with_force(self) -> None:
        once = patch_main(FAKE_MAIN, self.config, self.css, force=False)
        twice = patch_main(once, self.config, self.css, force=True)
        self.assertEqual(twice.count('"./themes/graphite.json"'), 1)
        self.assertEqual(twice.count("t===`graphite`&&"), 1)
        self.assertEqual(twice.count('"graphite":"Graphite"'), 1)
        self.assertEqual(validate_patch(twice, "graphite"), [])

    def test_patched_main_parses(self) -> None:
        if shutil.which("node") is None:
            self.skipTest("node is not installed")
        patched = patch_main(FAKE_MAIN, self.config, self.css, force=False)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "main.mjs"
            path.write_text(patched, encoding="utf-8")
            result = subprocess.run(
                ["node", "--check", str(path)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_unquoted_registry_key_is_reported(self) -> None:
        broken = FAKE_MAIN.replace(
            'var reg={"oc-2":`OpenCode`,amoled:`AMOLED`};',
            'var reg={"oc-2":`OpenCode`,amoled:`AMOLED`,graphite:`Graphite`};',
        )
        broken = broken.replace(
            'var map={"./themes/amoled.json":()=>Q(()=>import(`./amoled-abc.js`),[],import.meta.url)};',
            'var map={"./themes/amoled.json":()=>Q(()=>import(`./amoled-abc.js`),[],import.meta.url),'
            '"./themes/graphite.json":()=>Q(()=>import(`./graphite.js`),[],import.meta.url)};',
        )
        broken = broken.replace(
            "izt().textContent=s",
            "t===`graphite`&&n===`dark`&&(s+=`:root{}`),izt().textContent=s",
        )
        problems = validate_patch(broken, "graphite")
        self.assertTrue(any("unquoted" in problem for problem in problems))

    def test_missing_color_scheme_guard_is_reported(self) -> None:
        patched = patch_main(FAKE_MAIN, self.config, self.css, force=False)
        unguarded = patched.replace("&&n===`dark`&&(", "&&(", 1)
        problems = validate_patch(unguarded, "graphite")
        self.assertTrue(any("color-scheme" in problem for problem in problems))


if __name__ == "__main__":
    unittest.main()
