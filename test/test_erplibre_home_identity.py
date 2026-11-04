#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""The names of ERPLibre Home agree across the files that spell them.

The extension, its schema, its translations, the deck programs, the Claude
hook, the Makefile and the installer each spell one of the extension's
names: a D-Bus object, a dconf path, a gettext domain, a data directory, a
file prefix. A writer and a reader of the same file, or a client and the
object it calls, that spell it differently fail only at run time, on a
desktop session, and without an error: the reader finds nothing. These
tests read each spelling from the file that holds it and compare them.

The extension's previous identity is named only where the migration away
from it needs it, and in the history that records it.
"""

import ast
import importlib.util
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
EXT = ROOT / "script" / "gnome-extension" / "erplibre_home"
MAKEFILE = ROOT / "conf" / "make.streamdeck.Makefile"
INSTALLER = ROOT / "script" / "install" / "install_erplibre_home.sh"
HOOK = EXT / "hooks" / "erplibre-home-hook.py"
DOMAIN = "erplibre-home"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _text(path):
    return Path(path).read_text(encoding="utf-8")


def _metadata():
    return json.loads(_text(EXT / "metadata.json"))


def _schema_files():
    return sorted((EXT / "schemas").glob("*.gschema.xml"))


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


class TestMetadataAndSchema(unittest.TestCase):
    def test_name_and_description_are_those_of_erplibre_home(self):
        meta = _metadata()
        self.assertEqual(meta["name"], "ERPLibre Home")
        self.assertEqual(
            meta["description"], "ERPLibre for personal environment"
        )

    def test_schema_id_path_file_and_metadata_agree(self):
        """GNOME Shell finds the schema by the metadata's settings-schema,
        in the file named after the id; the migration copies the old
        settings to the path that schema reads."""
        files = _schema_files()
        self.assertEqual(len(files), 1)
        schemas = ET.parse(files[0]).getroot().findall("schema")
        self.assertEqual(len(schemas), 1)
        schema_id = schemas[0].get("id")
        self.assertEqual(schema_id, f"org.gnome.shell.extensions.{DOMAIN}")
        self.assertEqual(files[0].name, f"{schema_id}.gschema.xml")
        self.assertEqual(_metadata()["settings-schema"], schema_id)
        path = schemas[0].get("path")
        self.assertEqual(path, f"/org/gnome/shell/extensions/{DOMAIN}/")
        migrate = _load("migrate_legacy", EXT / "tools" / "migrate_legacy.py")
        self.assertEqual(migrate.NEW_DCONF, path)

    def test_gettext_domains_are_the_mo_basename(self):
        """The extension binds the metadata's gettext-domain and the
        schema its own: both must name the .mo the installer compiles,
        or the interface stays in English."""
        root = ET.parse(_schema_files()[0]).getroot()
        self.assertEqual(_metadata()["gettext-domain"], DOMAIN)
        self.assertEqual(root.get("gettext-domain"), DOMAIN)
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
        self.assertIn(
            f"{DOMAIN}.mo", _py_strings(EXT / "po/compile_locales.py")
        )
        self.assertTrue((EXT / "po" / f"{DOMAIN}.pot").is_file())


class TestDbusClients(unittest.TestCase):
    """Every caller of the extension's D-Bus object names the path and
    interface extension.js exports, and a method it declares."""

    def setUp(self):
        src = _text(EXT / "extension.js")
        exported = re.findall(r"\.export\(\s*[^,]+,\s*'([^']+)'\)", src)
        self.assertEqual(len(exported), 1)
        self.path = exported[0]
        ifaces = re.findall(r'<interface name="([^"]+)">', src)
        self.assertEqual(len(ifaces), 1)
        self.iface = ifaces[0]
        self.methods = set(re.findall(r'<method name="(\w+)"', src))
        self.assertEqual(
            (self.path, self.iface),
            (
                "/org/gnome/Shell/Extensions/ERPLibreHome",
                "org.gnome.Shell.Extensions.ERPLibreHome",
            ),
        )

    def test_python_clients_call_the_exported_object(self):
        clients = {
            ROOT / "script/stream_deck/translator.py": "GetFocusedWindowClass",
            HOOK: "GetFocusedWindowId",
        }
        for path, method in clients.items():
            with self.subTest(client=path.name):
                strings = _py_strings(path)
                self.assertIn(method, self.methods)
                self.assertIn(self.path, strings)
                self.assertIn(f"{self.iface}.{method}", strings)

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

    def test_the_nested_smoke_test_calls_the_exported_object(self):
        src = _text(EXT / "test" / "e2e_nested.sh")
        self.assertIn(f"--object-path {self.path} ", src)
        self.assertIn(f"--method {self.iface}.DebugClaudeIndex", src)
        self.assertIn("DebugClaudeIndex", self.methods)


class TestDataDirectories(unittest.TestCase):
    """The extension, the deck program and the Claude hook read and write
    the same directories under the XDG bases."""

    def _deck_state_name(self):
        """The deck's state directory, relative to $XDG_STATE_HOME."""
        paths = _load(
            "erplibre_streamdeck_paths",
            ROOT / "script/stream_deck/erplibre_streamdeck/paths.py",
        )
        with mock.patch.dict(os.environ, {"XDG_STATE_HOME": "/x/state"}):
            state = paths.state_dir()
        return str(state.relative_to("/x/state"))

    def test_the_state_directory_is_shared(self):
        name = self._deck_state_name()
        self.assertEqual(name, DOMAIN)
        state = _tmp(self)
        hook = _load("erplibre_home_hook", HOOK)
        with mock.patch.dict(os.environ, {"XDG_STATE_HOME": str(state)}):
            self.assertEqual(hook.state_dir(), state / name / "claude")
        self.assertEqual(
            _js_const(EXT / "lib/claude-state.js", "STATE_DIR_REL"),
            f"{name}/claude",
        )
        self.assertEqual(
            _js_const(EXT / "lib/mpv-state.js", "STATE_SUBDIR"), f"{name}/mpv"
        )
        self.assertIn(
            "`${base}/%s/log.jsonl`" % name, _text(EXT / "lib/log.js")
        )
        extension = _text(EXT / "extension.js")
        self.assertIn("`${base}/%s/mpv/${id}.json`" % name, extension)
        self.assertIn("`${base}/%s/claude`" % name, extension)
        erplibre = _text(EXT / "indicators/erplibre.js")
        self.assertIn("`${stateBase}/%s/todo`" % name, erplibre)
        self.assertIn("`${stateBase}/%s`" % name, erplibre)

    def test_the_controller_pid_file_is_shared(self):
        """The device indicator reads the pid the controller writes."""
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
        rel = f"{DOMAIN}/controller.pid"
        self.assertEqual(default, home / ".cache" / rel)
        self.assertEqual(followed, cache / rel)
        self.assertEqual(
            re.findall(
                r"const PIDFILE\s*=\s*`\$\{GLib\.get_user_cache_dir\(\)\}/"
                r"([^`]*)`",
                _text(EXT / "indicators/device.js"),
            ),
            [rel],
        )

    def test_the_nested_shell_sandbox_is_named_after_the_extension(self):
        found = re.findall(
            r'^SANDBOX="([^"]*)"', _text(EXT / "dev_nested.sh"), re.M
        )
        self.assertEqual(
            found, [f"${{XDG_RUNTIME_DIR:-/tmp}}/{DOMAIN}-nested"]
        )


class TestClaudeHook(unittest.TestCase):
    def setUp(self):
        self.installer = _load(
            "install_claude_hooks", EXT / "hooks" / "install_claude_hooks.py"
        )

    def test_the_installed_command_is_the_erplibre_home_hook(self):
        self.assertEqual(self.installer.HOOK_PATH, HOOK)
        self.assertTrue(os.access(HOOK, os.X_OK))

    def test_the_backup_carries_the_erplibre_home_tag(self):
        tmp = _tmp(self)
        self.installer.SETTINGS = tmp / "settings.json"
        self.installer.SETTINGS.write_text("{}", encoding="utf-8")
        target = self.installer.backup({"hooks": {}})
        self.assertRegex(
            target.name, r"^settings\.json\.bak-erplibre-home-\d{8}-\d{6}$"
        )
        self.assertEqual(target.parent, tmp)


class TestHotReload(unittest.TestCase):
    def test_extension_and_makefile_share_the_copy_prefix(self):
        """The Makefile's clean-up removes the copies the extension makes;
        another prefix would leave them loaded."""
        prefix = _js_const(EXT / "extension.js", "RELOAD_UUID_PREFIX")
        self.assertEqual(prefix, f"{DOMAIN}-reload-")
        self.assertEqual(
            _make_variable("ERPLIBRE_HOME_EXT_TMP_PREFIX"), prefix
        )


class TestGitSync(unittest.TestCase):
    def test_export_and_import_go_through_the_git_sync_names(self):
        """lib/git-sync.js holds the file name and the fallback to the
        former one; the extension spells neither itself."""
        src = _text(EXT / "extension.js")
        imports = re.findall(
            r"import \{([^}]*)\} from './lib/git-sync.js'", src
        )
        self.assertEqual(len(imports), 1)
        names = {name.strip() for name in imports[0].split(",")}
        self.assertLessEqual({"SYNC_FILE", "syncImportPath"}, names)
        self.assertIn("Gio.File.new_for_path(`${repo}/${SYNC_FILE}`)", src)
        self.assertRegex(src, r"const path = syncImportPath\(repo\b")
        self.assertNotIn(f"{DOMAIN}.json", src)


class TestStyleClasses(unittest.TestCase):
    def test_dialog_and_button_classes_are_erplibre_home(self):
        classes = []
        for path in sorted(EXT.rglob("*.js")):
            if "test" in path.relative_to(EXT).parts:
                continue
            classes += re.findall(
                r"(?:styleClass|style_class)\s*:\s*'([^']*)'", _text(path)
            )
        own = [c for c in classes if re.search(r"-(dialog|btn)\b", c)]
        self.assertIn(f"{DOMAIN}-dialog", own)
        self.assertIn(f"{DOMAIN}-btn", own)
        self.assertEqual(
            [c for c in own if c not in (f"{DOMAIN}-dialog", f"{DOMAIN}-btn")],
            [],
        )
        for path in sorted((EXT / "ui").glob("*-dialog.js")):
            with self.subTest(dialog=path.name):
                self.assertIn(
                    f"super._init({{styleClass: '{DOMAIN}-dialog'}})",
                    _text(path),
                )


class TestReadme(unittest.TestCase):
    def test_relative_paths_resolve_from_the_extension(self):
        found = re.findall(r"`(\.\./[^`\s]+)`", _text(EXT / "README.base.md"))
        self.assertIn("../../stream_deck/screenshots/", found)
        for rel in found:
            with self.subTest(path=rel):
                self.assertTrue((EXT / rel).exists())


@unittest.skipUnless(
    shutil.which("git") and (ROOT / ".git").exists(), "not a git checkout"
)
class TestLegacyNames(unittest.TestCase):
    """The previous identity stays where the migration needs it and in the
    history; anywhere else it is a name the rename missed."""

    ALLOWED = (
        "CHANGELOG.base.md",
        "CHANGELOG.md",
        "CHANGELOG.fr.md",
        "script/gnome-extension/erplibre_home/CHANGELOG.md",
        "script/gnome-extension/erplibre_home/tools/migrate_legacy.py",
        "script/gnome-extension/erplibre_home/lib/git-sync.js",
        "script/gnome-extension/erplibre_home/test/unit/git-sync.test.js",
        "test/test_erplibre_home_migrate_legacy.py",
    )
    # Design documents record the decisions, under their names of the time.
    ALLOWED_DIRS = ("docs/superpowers/",)
    # The deck program's former make target stays an alias.
    ALIASES = {"streamdeck_tiler", "streamdeck_tiler_unittest"}

    def test_only_the_migration_and_the_history_name_the_old_identity(self):
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
            if path in self.ALLOWED or path.startswith(self.ALLOWED_DIRS):
                continue
            if match in self.ALIASES:
                continue
            stray.append(line)
        self.assertEqual(stray, [])


if __name__ == "__main__":
    unittest.main()
