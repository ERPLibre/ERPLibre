#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Emplacements du hub web : un jeu par checkout, privés à l'utilisateur.

HOME et XDG_RUNTIME_DIR pointent vers un répertoire temporaire : aucun test
ne touche le vrai ~/.erplibre ni le vrai répertoire d'exécution.
"""

import os
import stat
import subprocess
import sys
import threading
import time
import unittest
from pathlib import Path

from todo_web_env import private_env

from script.todo.web import paths

REPO = Path(__file__).resolve().parent.parent
WRITES = 300
# Écrivain d'un autre processus : il annonce qu'il est prêt, attend le fichier
# de départ commun, puis écrit sa valeur WRITES fois.
WRITER = """\
import os, sys, time
from pathlib import Path
from script.todo.web import paths
target, go, value, count = sys.argv[1:]
print("ready", flush=True)
deadline = time.monotonic() + 30
while not os.path.exists(go):
    if time.monotonic() > deadline:
        sys.exit("no start signal")
    time.sleep(0.001)
for _ in range(int(count)):
    paths.write_private(Path(target), value)
"""


def _mode(path) -> int:
    return stat.S_IMODE(os.stat(path).st_mode)


class TestPaths(unittest.TestCase):
    def setUp(self):
        self.tmp = private_env(self.addCleanup)
        self.home = self.tmp / "home"
        self.run = self.tmp / "run"
        self.root = self.tmp / "checkout"
        self.root.mkdir()

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

    def test_concurrent_writers_share_no_temporary_file(self):
        # Deux threads et deux processus écrivent le même fichier en même
        # temps : aucun n'échoue, et le contenu final est entier, celui de
        # l'un d'eux.
        target = paths.runtime_dir(self.root) / "redirect.html"
        go = self.tmp / "go"
        values = [
            f"{name}\n" * 512
            for name in ("thread-a", "thread-b", "process-a", "process-b")
        ]
        env = dict(os.environ, PYTHONPATH=str(REPO))
        procs = []
        for value in values[2:]:
            proc = subprocess.Popen(
                [sys.executable, "-c", WRITER, str(target), str(go), value]
                + [str(WRITES)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
            )
            self.addCleanup(proc.wait)
            self.addCleanup(proc.kill)
            procs.append(proc)
        for proc in procs:
            self.assertEqual(proc.stdout.readline(), "ready\n")
        errors = []
        start = threading.Event()

        def write(value):
            start.wait(30)
            try:
                for _ in range(WRITES):
                    paths.write_private(target, value)
            except Exception as exc:
                errors.append(exc)

        threads = [
            threading.Thread(target=write, args=(value,))
            for value in values[:2]
        ]
        for thread in threads:
            thread.start()
        go.touch()
        start.set()
        for thread in threads:
            thread.join(60)
        for proc in procs:
            _out, err = proc.communicate(timeout=60)
            self.assertEqual((proc.returncode, err), (0, ""))
        self.assertEqual(errors, [])
        self.assertIn(target.read_text(encoding="utf-8"), values)
        self.assertEqual(_mode(target), 0o600)
        self.assertEqual(
            [p.name for p in target.parent.iterdir()], ["redirect.html"]
        )

    def test_a_failed_write_leaves_no_temporary_file(self):
        target = paths.runtime_dir(self.root) / "redirect.html"
        target.mkdir()
        with self.assertRaises(OSError):
            paths.write_private(target, "new")
        self.assertEqual(
            [p.name for p in target.parent.iterdir()], ["redirect.html"]
        )

    def test_tasks_dir_is_private_under_the_data_dir(self):
        tasks = paths.tasks_dir(self.root)
        self.assertEqual(tasks, paths.data_dir(self.root) / "tasks")
        self.assertEqual(_mode(tasks), 0o700)

    def test_only_old_temporary_files_are_orphans(self):
        rdir = paths.runtime_dir(self.root)
        old = rdir / "state.json.a1.tmp"
        fresh = rdir / "redirect.html.b2.tmp"
        kept = rdir / "state.json"
        for path in (old, fresh, kept):
            path.write_text("x", encoding="utf-8")
        past = time.time() - paths.ORPHAN_SECONDS - 1
        os.utime(old, (past, past))
        os.utime(kept, (past, past))
        self.assertEqual(paths.remove_orphans(rdir), 1)
        self.assertEqual(
            sorted(p.name for p in rdir.iterdir()),
            ["redirect.html.b2.tmp", "state.json"],
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
