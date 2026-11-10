#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""The names of ERPLibre Home agree between ERPLibre and its extension.

The GNOME extension is a separate repository cloned at
script/gnome-extension/erplibre_home/. ERPLibre's installer, Makefile,
deck programs and translator each spell one of the extension's names: a
D-Bus object, a gettext domain, a data directory, a file prefix. A writer
and a reader of the same file, or a client and the object it calls, that
spell it differently fail only at run time, on a desktop session, and
without an error: the reader finds nothing. These tests read each spelling
from the file that holds it, on both sides, and compare them. The
extension's own names, among its files, are tested in its repository
(test/python/test_identity.py).

Every test that reads the extension is skipped when its clone is missing
(SANS_EXTENSION). The extension's previous identity is named in ERPLibre
only in the history that records it.
"""

import ast
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from erplibre_home_extension import EXTENSION, SANS_EXTENSION  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
EXT = EXTENSION
MAKEFILE = ROOT / "conf" / "make.streamdeck.Makefile"
INSTALLER = ROOT / "script" / "install" / "install_erplibre_home.sh"
DOMAIN = "erplibre-home"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _text(path):
    return Path(path).read_text(encoding="utf-8")


def _make_variable(name):
    """The value of a ``NAME := value`` line of the Stream Deck Makefile."""
    found = re.findall(
        r"^%s\s*:=\s*(\S+)\s*$" % re.escape(name), _text(MAKEFILE), re.M
    )
    if len(found) != 1:
        raise AssertionError(f"{name}: {len(found)} definitions")
    return found[0]


def _js_const(path, name):
    """The string literal assigned to ``const NAME`` in a JS file."""
    found = re.findall(
        r"\bconst %s\s*=\s*'([^']*)'" % re.escape(name), _text(path)
    )
    if len(found) != 1:
        raise AssertionError(f"{path.name} {name}: {len(found)} definitions")
    return found[0]


def _py_strings(path):
    """Every string constant of a Python file, implicit joins resolved."""
    tree = ast.parse(_text(path))
    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }


def _tmp(case):
    tmp = tempfile.TemporaryDirectory()
    case.addCleanup(tmp.cleanup)
    return Path(tmp.name)


class TestGettextDomain(unittest.TestCase):
    def test_the_installer_compiles_the_mo_of_the_metadata_domain(self):
        """The installer writes <domain>.mo where the extension binds it."""
        home = _tmp(self)
        env = {
            "HOME": str(home),
            "PATH": os.environ.get("PATH", ""),
            "INSTALLER": str(INSTALLER),
        }
        done = subprocess.run(
            [
                "bash",
                "-c",
                'ERPLIBRE_HOME_SOURCE_ONLY=1 source "$INSTALLER"\n'
                "mo_file fr\n",
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        mo = Path(done.stdout.strip())
        self.assertEqual(mo.name, f"{DOMAIN}.mo")
        self.assertEqual(mo.parent, EXT / "locale" / "fr" / "LC_MESSAGES")

    @SANS_EXTENSION
    def test_the_domain_is_the_one_of_metadata(self):
        meta = json.loads(_text(EXT / "metadata.json"))
        self.assertEqual(meta["gettext-domain"], DOMAIN)


@SANS_EXTENSION
class TestDbusClients(unittest.TestCase):
    """Every ERPLibre caller of the extension's D-Bus object names the path
    and interface extension.js exports, and a method it declares."""

    def setUp(self):
        src = _text(EXT / "extension.js")
        exported = re.findall(r"\.export\(\s*[^,]+,\s*'([^']+)'\)", src)
        self.assertEqual(len(exported), 1)
        self.path = exported[0]
        ifaces = re.findall(r'<interface name="([^"]+)">', src)
        self.assertEqual(len(ifaces), 1)
        self.iface = ifaces[0]
        self.methods = set(re.findall(r'<method name="(\w+)"', src))

    def test_the_translator_calls_the_exported_object(self):
        strings = _py_strings(ROOT / "script/stream_deck/translator.py")
        self.assertIn("GetFocusedWindowClass", self.methods)
        self.assertIn(self.path, strings)
        self.assertIn(f"{self.iface}.GetFocusedWindowClass", strings)

    def test_the_reload_targets_call_the_exported_object(self):
        self.assertEqual(_make_variable("ERPLIBRE_HOME_DBUS_PATH"), self.path)
        self.assertEqual(
            _make_variable("ERPLIBRE_HOME_DBUS_IFACE"), self.iface
        )
        self.assertEqual(
            _make_variable("ERPLIBRE_HOME_DBUS_DEST"), "org.gnome.Shell"
        )
        for method in ("HotReload", "HotExit"):
            with self.subTest(method=method):
                self.assertIn(method, self.methods)


class TestDataDirectories(unittest.TestCase):
    """The extension and the deck program read and write the same
    directories under the XDG bases."""

    def _deck_state_name(self):
        """The deck's state directory, relative to $XDG_STATE_HOME."""
        paths = _load(
            "erplibre_streamdeck_paths",
            ROOT / "script/stream_deck/erplibre_streamdeck/paths.py",
        )
        with mock.patch.dict(os.environ, {"XDG_STATE_HOME": "/x/state"}):
            state = paths.state_dir()
        return str(state.relative_to("/x/state"))

    def test_the_deck_state_directory_is_named_after_the_domain(self):
        self.assertEqual(self._deck_state_name(), DOMAIN)

    @SANS_EXTENSION
    def test_the_extension_reads_the_deck_state_directory(self):
        """The TODO indicator lists what the deck writes there."""
        name = self._deck_state_name()
        erplibre = _text(EXT / "indicators/erplibre.js")
        self.assertIn("`${stateBase}/%s/todo`" % name, erplibre)
        self.assertIn("`${stateBase}/%s`" % name, erplibre)

    def test_the_controller_pid_file_is_named_after_the_domain(self):
        self.assertEqual(self._pid_file_rel(), f"{DOMAIN}/controller.pid")

    @SANS_EXTENSION
    def test_the_device_indicator_reads_the_controller_pid_file(self):
        self.assertEqual(
            re.findall(
                r"const PIDFILE\s*=\s*`\$\{GLib\.get_user_cache_dir\(\)\}/"
                r"([^`]*)`",
                _text(EXT / "indicators/device.js"),
            ),
            [self._pid_file_rel()],
        )

    def _pid_file_rel(self):
        """The controller's PIDFILE, relative to $XDG_CACHE_HOME, after
        checking that it follows XDG_CACHE_HOME and defaults to ~/.cache."""
        tree = ast.parse(
            _text(ROOT / "script/stream_deck/erplibre_controller.py")
        )
        assigns = [
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Assign)
            and any(
                isinstance(t, ast.Name) and t.id == "PIDFILE"
                for t in node.targets
            )
        ]
        self.assertEqual(len(assigns), 1)
        # The controller's own expression, evaluated alone: importing the
        # module would load the Stream Deck and imaging libraries.
        code = compile(ast.Expression(assigns[0]), "PIDFILE", "eval")
        home = _tmp(self)
        cache = home / "cache"
        scope = {"os": os, "Path": Path}
        with mock.patch.dict(os.environ, {"HOME": str(home)}):
            os.environ.pop("XDG_CACHE_HOME", None)
            default = eval(code, scope)
            os.environ["XDG_CACHE_HOME"] = str(cache)
            followed = eval(code, scope)
        rel = str(followed.relative_to(cache))
        self.assertEqual(default, home / ".cache" / rel)
        return rel


class TestHotReload(unittest.TestCase):
    def test_the_makefile_prefix_is_named_after_the_domain(self):
        self.assertEqual(
            _make_variable("ERPLIBRE_HOME_EXT_TMP_PREFIX"), f"{DOMAIN}-reload-"
        )

    @SANS_EXTENSION
    def test_extension_and_makefile_share_the_copy_prefix(self):
        """The Makefile's clean-up removes the copies the extension makes;
        another prefix would leave them loaded."""
        prefix = _js_const(EXT / "extension.js", "RELOAD_UUID_PREFIX")
        self.assertEqual(
            _make_variable("ERPLIBRE_HOME_EXT_TMP_PREFIX"), prefix
        )


@unittest.skipUnless(
    shutil.which("git") and (ROOT / ".git").exists(), "not a git checkout"
)
class TestLegacyNames(unittest.TestCase):
    """The previous identity stays in ERPLibre's history only; anywhere
    else it is a name the rename missed. The extension's own files are
    checked in its repository."""

    ALLOWED = (
        "CHANGELOG.base.md",
        "CHANGELOG.md",
        "CHANGELOG.fr.md",
    )
    # The deck program's former make target stays an alias.
    ALIASES = {"streamdeck_tiler", "streamdeck_tiler_unittest"}

    def test_only_the_history_names_the_old_identity(self):
        done = subprocess.run(
            [
                "git",
                "grep",
                "-I",
                "-n",
                "-o",
                "-i",
                "-E",
                r"stream[-_ ]?deck[-_ ]?tiler[A-Za-z0-9_-]*",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertIn(done.returncode, (0, 1), done.stderr)
        stray = []
        for line in done.stdout.splitlines():
            path, _, match = line.split(":", 2)
            if path in self.ALLOWED:
                continue
            if match in self.ALIASES:
                continue
            stray.append(line)
        self.assertEqual(stray, [])


if __name__ == "__main__":
    unittest.main()
