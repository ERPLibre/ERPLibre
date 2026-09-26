#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Emplacements du hub web : un jeu par checkout, privés à l'utilisateur.

HOME et XDG_RUNTIME_DIR pointent vers un répertoire temporaire : aucun test
ne touche le vrai ~/.erplibre ni le vrai répertoire d'exécution.
"""

import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from script.todo.web import paths


def _mode(path) -> int:
    return stat.S_IMODE(os.stat(path).st_mode)


def _short_tmp() -> str:
    """Base des répertoires temporaires : celle du système si elle tient en
    40 octets, /tmp sinon. Le chemin de ctl.sock y ajoute 56 octets, et
    AF_UNIX n'en accepte que 103 à 107."""
    base = tempfile.gettempdir()
    return base if len(os.fsencode(base)) <= 40 else "/tmp"


class TestPaths(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(dir=_short_tmp())
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.home = self.tmp / "home"
        self.run = self.tmp / "run"
        self.home.mkdir()
        self.run.mkdir(mode=0o700)
        self.root = self.tmp / "checkout"
        self.root.mkdir()
        env = {"HOME": str(self.home), "XDG_RUNTIME_DIR": str(self.run)}
        patcher = patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_checkout_id_is_short_stable_and_follows_symlinks(self):
        link = self.tmp / "link"
        link.symlink_to(self.root)
        cid = paths.checkout_id(self.root)
        self.assertRegex(cid, r"^[0-9a-f]{12}$")
        self.assertEqual(paths.checkout_id(link), cid)
        other = self.tmp / "other"
        other.mkdir()
        self.assertNotEqual(paths.checkout_id(other), cid)

    def test_runtime_dir_under_xdg_is_private_parent_included(self):
        rdir = paths.runtime_dir(self.root)
        cid = paths.checkout_id(self.root)
        self.assertEqual(rdir, self.run / paths.APP / cid)
        self.assertEqual(_mode(rdir), 0o700)
        self.assertEqual(_mode(rdir.parent), 0o700)

    def test_existing_loose_directory_is_tightened(self):
        loose = self.run / paths.APP
        loose.mkdir(mode=0o755)
        os.chmod(loose, 0o755)
        paths.runtime_dir(self.root)
        self.assertEqual(_mode(loose), 0o700)

    def test_fallback_without_xdg_runtime_dir(self):
        del os.environ["XDG_RUNTIME_DIR"]
        rdir = paths.runtime_dir(self.root)
        cid = paths.checkout_id(self.root)
        base = self.home / ".erplibre" / "todo_web"
        self.assertEqual(rdir, base / cid / "run")
        for path in (rdir, rdir.parent, base):
            self.assertEqual(_mode(path), 0o700, path)

    def test_fallback_when_xdg_runtime_dir_is_read_only(self):
        if os.geteuid() == 0:
            self.skipTest("root : os.access ignore le mode 0500")
        os.chmod(self.run, 0o500)
        self.addCleanup(os.chmod, self.run, 0o700)
        rdir = paths.runtime_dir(self.root)
        self.assertTrue(str(rdir).startswith(str(self.home)))

    def test_data_dir_and_log_are_private(self):
        ddir = paths.data_dir(self.root)
        self.assertEqual(ddir.parent, self.home / ".erplibre" / "todo_web")
        self.assertEqual(_mode(ddir), 0o700)
        fd = paths.open_log(self.root)
        os.write(fd, b"one\n")
        os.close(fd)
        log = paths.log_path(self.root)
        self.assertEqual(_mode(log), 0o600)
        os.chmod(log, 0o644)
        fd = paths.open_log(self.root)
        os.write(fd, b"two\n")
        os.close(fd)
        self.assertEqual(_mode(log), 0o600)
        self.assertEqual(log.read_bytes(), b"one\ntwo\n")

    def test_runtime_files_live_in_the_runtime_dir(self):
        rdir = paths.runtime_dir(self.root)
        self.assertEqual(paths.ctl_path(self.root), rdir / "ctl.sock")
        self.assertEqual(paths.lock_path(self.root), rdir / "hub.lock")
        self.assertEqual(paths.state_path(self.root), rdir / "state.json")
        self.assertEqual(
            paths.redirect_path(self.root), rdir / "redirect.html"
        )

    def test_write_private_replaces_with_mode_0600(self):
        target = paths.runtime_dir(self.root) / "note.txt"
        target.write_text("old", encoding="utf-8")
        os.chmod(target, 0o644)
        paths.write_private(target, "new")
        self.assertEqual(target.read_text(encoding="utf-8"), "new")
        self.assertEqual(_mode(target), 0o600)
        self.assertEqual(
            sorted(p.name for p in target.parent.iterdir()), ["note.txt"]
        )

    def test_ctl_path_too_long_is_refused(self):
        deep = self.run / ("x" * 100)
        deep.mkdir()
        os.environ["XDG_RUNTIME_DIR"] = str(deep)
        limit = f"AF_UNIX allows {paths.MAX_SOCK_PATH}"
        with self.assertRaisesRegex(ValueError, limit):
            paths.ctl_path(self.root)


if __name__ == "__main__":
    unittest.main()
