# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""`make erplibre_home_enable_extension` against fake gnome-extensions and
gsettings: the real session is never reached because the fakes come first
on PATH (asserted in setUp)."""

import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UUID = "erplibre-home@technolibre.ca"

FAKE_GNOME_EXT = """#!/bin/sh
case "$1" in
enable)
    [ "$FAKE_ENABLE_RC" = 0 ] && exit 0
    echo "L’extension « $2 » n’existe pas" >&2
    exit 2 ;;
info) echo "  Activé : Oui" ;;
esac
"""

# `get KEY` prints the content of $FAKE_DIR/KEY; `set KEY VALUE` records the
# call in $FAKE_DIR/calls and stores VALUE as the new content.
FAKE_GSETTINGS = """#!/bin/sh
[ -n "$FAKE_GSETTINGS_FAIL" ] && { echo "no dconf" >&2; exit 1; }
if [ "$1" = get ]; then cat "$FAKE_DIR/$3"
else echo "$*" >> "$FAKE_DIR/calls"; printf '%s\\n' "$4" > "$FAKE_DIR/$3"; fi
"""


class EnableTargetTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)
        for name, body in (
            ("gnome-extensions", FAKE_GNOME_EXT),
            ("gsettings", FAKE_GSETTINGS),
        ):
            p = self.dir / name
            p.write_text(body)
            p.chmod(p.stat().st_mode | stat.S_IEXEC)
        self.env = dict(
            os.environ,
            PATH=f"{self.dir}{os.pathsep}{os.environ['PATH']}",
            FAKE_DIR=str(self.dir),
        )
        for tool in ("gnome-extensions", "gsettings"):
            self.assertEqual(shutil.which(tool, path=self.env["PATH"]), str(self.dir / tool))

    def run_target(self, enable_rc, enabled="@as []", disabled="@as []", **extra):
        (self.dir / "enabled-extensions").write_text(enabled + "\n")
        (self.dir / "disabled-extensions").write_text(disabled + "\n")
        env = dict(self.env, FAKE_ENABLE_RC=str(enable_rc), **extra)
        return subprocess.run(
            ["make", "-s", "erplibre_home_enable_extension"],
            cwd=ROOT, env=env, capture_output=True, text=True,
        )

    def value(self, key):
        return (self.dir / key).read_text().strip()

    def test_enable_works_prints_info_and_leaves_settings(self):
        r = self.run_target(0)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Activé", r.stdout)
        self.assertFalse((self.dir / "calls").exists())

    def test_fallback_appends_keeping_order(self):
        r = self.run_target(2, enabled="['a@x', 'b@x']")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.value("enabled-extensions"), f"['a@x', 'b@x', '{UUID}']")
        self.assertIn("next login", r.stdout)

    def test_fallback_from_empty_list(self):
        r = self.run_target(2)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.value("enabled-extensions"), f"['{UUID}']")

    def test_fallback_does_not_duplicate(self):
        r = self.run_target(2, enabled=f"['a@x', '{UUID}', 'b@x']")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse((self.dir / "calls").exists())
        self.assertIn("next login", r.stdout)

    def test_fallback_cleans_disabled(self):
        r = self.run_target(2, enabled="['a@x']", disabled=f"['z@x', '{UUID}']")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.value("disabled-extensions"), "['z@x']")
        self.assertEqual(self.value("enabled-extensions"), f"['a@x', '{UUID}']")

    def test_enable_error_first_line_is_shown(self):
        r = self.run_target(2)
        self.assertIn("n’existe pas", r.stderr)

    def test_disabled_written_before_enabled(self):
        self.run_target(2, enabled="['a@x']", disabled=f"['{UUID}']")
        calls = (self.dir / "calls").read_text().splitlines()
        self.assertIn("disabled-extensions", calls[0])
        self.assertIn("enabled-extensions", calls[1])

    def test_unparsable_setting_exits_nonzero(self):
        r = self.run_target(2, enabled="not a list (")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("gsettings failed", r.stderr)

    def test_gnome_extensions_absent_uses_fallback(self):
        (self.dir / "gnome-extensions").unlink()
        tools = self.dir / "bin"
        tools.mkdir()
        for name in ("make", "sh", "python3", "env", "head", "printf", "dirname", "cat", "uname", "bash"):
            found = shutil.which(name)
            if found:
                (tools / name).symlink_to(found)
        env = dict(self.env, PATH=f"{self.dir}{os.pathsep}{tools}")
        self.assertIsNone(shutil.which("gnome-extensions", path=env["PATH"]))
        (self.dir / "enabled-extensions").write_text("@as []\n")
        (self.dir / "disabled-extensions").write_text("@as []\n")
        r = subprocess.run(
            ["make", "-s", "erplibre_home_enable_extension"],
            cwd=ROOT, env=env, capture_output=True, text=True,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("next login", r.stdout)
        self.assertEqual(self.value("enabled-extensions"), f"['{UUID}']")

    def test_gsettings_failure_exits_nonzero(self):
        r = self.run_target(2, FAKE_GSETTINGS_FAIL="1")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("gsettings failed", r.stderr)


if __name__ == "__main__":
    unittest.main()
