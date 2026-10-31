from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from oc_theme.theme import (
    ThemeConfig,
    ThemeError,
    authored_color,
    build_theme_module,
    extract_theme_parts,
    flat_css,
)

FAKE_THEME = """\
var light={palette:{neutral:`#f7f7f7`,ink:`#171311`,primary:`#dcde8d`,success:`#12c905`,warning:`#ffdc17`,error:`#fc533a`,info:`#a753ae`,interactive:`#034cff`,diffAdd:`#9ff29a`,diffDelete:`#fc533a`},overrides:{"border-weak-base":`#DBDBDB`},v2Overrides:{"v2-grey-800":`#e0e0e0ff`}};
var dark={palette:{neutral:`#1f1f1f`,ink:`#f1ece8`,primary:`#fab283`,success:`#12c905`,warning:`#fcd53a`,error:`#fc533a`,info:`#edb2f1`,interactive:`#034cff`,diffAdd:`#c8ffc4`,diffDelete:`#fc533a`},overrides:{"border-weak-base":`#282828`},v2Overrides:{"v2-grey-800":`#3a3a3aff`}};
"""


class ThemeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = ThemeConfig()
        self.parts = extract_theme_parts(FAKE_THEME)

    def test_authored_color_compensates_the_render_shift(self) -> None:
        self.assertEqual(authored_color("#323232", 3), "#2f2f2f")
        self.assertEqual(authored_color("#323232", 0), "#323232")

    def test_flat_css_contains_both_layers(self) -> None:
        css = flat_css(self.config)
        self.assertIn("--background-base:#2f2f2f!important;", css)
        self.assertIn("--v2-grey-800:#2f2f2fff!important;", css)

    def test_module_contains_the_expected_bindings(self) -> None:
        module = build_theme_module(self.parts, self.config)
        self.assertIn('const id = "graphite";', module)
        self.assertIn('const name = "Graphite";', module)
        self.assertIn("neutral:`#2f2f2f`", module)
        self.assertIn("ink:`#EDEDED`", module)
        self.assertIn("theme as default", module)
        self.assertIn("export { $schema, dark, theme as default, id, light, name };", module)

    def test_module_parses(self) -> None:
        if shutil.which("node") is None:
            self.skipTest("node is not installed")
        module = build_theme_module(self.parts, self.config)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "graphite.mjs"
            path.write_text(module, encoding="utf-8")
            result = subprocess.run(
                ["node", "--check", str(path)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_missing_theme_object_is_reported(self) -> None:
        with self.assertRaises(ThemeError):
            extract_theme_parts("var nothing = 1;")


if __name__ == "__main__":
    unittest.main()
