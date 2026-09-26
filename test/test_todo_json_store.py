#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Fichiers JSON de ~/.erplibre écrits par plusieurs processus TODO à la fois.

Un verrou ou un remplacement atomique ne se prouve pas dans un seul processus :
les tests de concurrence lancent de vrais interpréteurs, avec un HOME
temporaire pour ne jamais toucher les fichiers de l'utilisateur.
"""

import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from script.todo import json_store

REPO = Path(__file__).resolve().parent.parent


def _spawn(code, home):
    """Lance `code` dans un interpréteur neuf, HOME redirigé."""
    env = dict(os.environ, HOME=str(home), PYTHONPATH=str(REPO))
    return subprocess.Popen([sys.executable, "-c", code], env=env, cwd=REPO)


class TestJsonStore(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.path = self.dir / "store.json"

    def tearDown(self):
        self._tmp.cleanup()

    def test_missing_file_gives_the_default(self):
        self.assertEqual(json_store.read(self.path, dict), {})

    def test_the_default_is_a_fresh_object_each_time(self):
        first = json_store.read(self.path, dict)
        first["x"] = 1
        self.assertEqual(json_store.read(self.path, dict), {})

    def test_corrupt_file_gives_the_default_and_update_repairs_it(self):
        self.path.write_text("{", encoding="utf-8")
        self.assertEqual(json_store.read(self.path, dict), {})
        json_store.update(self.path, lambda d: {**d, "n": 1}, dict)
        self.assertEqual(json.loads(self.path.read_text()), {"n": 1})

    def test_update_writes_and_returns_what_fn_returns(self):
        out = json_store.update(
            self.path, lambda d: {"n": d.get("n", 0) + 1}, dict
        )
        self.assertEqual(out, {"n": 1})
        self.assertEqual(json_store.read(self.path, dict), {"n": 1})

    def test_written_file_is_private_and_no_temporary_remains(self):
        json_store.write(self.path, {"a": 1})
        mode = stat.S_IMODE(self.path.stat().st_mode)
        self.assertEqual(mode & 0o077, 0)
        leftovers = [p.name for p in self.dir.iterdir() if p.suffix == ".tmp"]
        self.assertEqual(leftovers, [])

    def test_symlinked_store_stays_a_symlink(self):
        """Un magasin visé par un lien symbolique (dotfiles gérant
        ~/.erplibre, par exemple) garde ce lien après écriture : `os.replace`
        remplace l'inode de son second argument, jamais celui d'une cible
        qu'on aurait dû suivre à la place."""
        cible = self.dir / "reel.json"
        lien = self.dir / "store_lie.json"
        json_store.write(cible, {"n": 1})
        lien.symlink_to(cible)
        json_store.update(lien, lambda d: {**d, "n": d["n"] + 1}, dict)
        self.assertTrue(lien.is_symlink())
        self.assertEqual(os.readlink(lien), str(cible))
        self.assertEqual(json.loads(cible.read_text()), {"n": 2})

    def test_two_processes_lose_no_increment(self):
        code = (
            "from pathlib import Path\n"
            "from script.todo import json_store\n"
            f"p = Path({str(self.path)!r})\n"
            "for _ in range(300):\n"
            "    json_store.update(p, lambda d: {'n': d.get('n', 0) + 1},"
            " dict)\n"
        )
        procs = [_spawn(code, self.dir) for _ in range(2)]
        # Attend TOUS les processus avant de rien affirmer : une assertion
        # sur le premier `wait` laisserait le second tourner sans jamais être
        # attendu (zombie) si elle échouait.
        codes = [proc.wait(timeout=60) for proc in procs]
        for code in codes:
            self.assertEqual(code, 0)
        self.assertEqual(json_store.read(self.path, dict), {"n": 600})

    def test_a_reader_never_sees_a_half_written_file(self):
        json_store.write(self.path, {"n": 0, "pad": "x" * 20000})
        code = (
            "from pathlib import Path\n"
            "from script.todo import json_store\n"
            f"p = Path({str(self.path)!r})\n"
            "for _ in range(300):\n"
            "    json_store.update(p, lambda d: {**d, 'n': d['n'] + 1},"
            " dict)\n"
        )
        proc = _spawn(code, self.dir)
        reads = bad = 0
        while proc.poll() is None:
            data = json_store.read(self.path, lambda: None)
            reads += 1
            if not isinstance(data, dict) or "pad" not in data:
                bad += 1
        self.assertEqual(proc.wait(timeout=60), 0)
        self.assertGreater(reads, 0)
        self.assertEqual(bad, 0)


class TestSharedTodoStores(unittest.TestCase):
    """La télémétrie et les préférences passent par json_store."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_two_todo_processes_add_up_their_telemetry(self):
        code = (
            "from script.todo import todo_telemetry as tt\n"
            "for _ in range(150):\n"
            "    tt.record('TODO › A')\n"
            "    tt.record('TODO › B')\n"
        )
        procs = [_spawn(code, self.home) for _ in range(2)]
        codes = [proc.wait(timeout=60) for proc in procs]
        for code in codes:
            self.assertEqual(code, 0)
        data = json.loads(
            (self.home / ".erplibre" / "todo_telemetry.json").read_text()
        )
        self.assertEqual(data["paths"], {"TODO › A": 300, "TODO › B": 300})

    def test_two_processes_keep_every_preference(self):
        code = (
            "import sys\n"
            "from script.todo import todo_prefs\n"
            "tag = sys.argv[1]\n"
            "for i in range(100):\n"
            "    todo_prefs.set(f'k{tag}_{i}', i)\n"
        )
        env = dict(os.environ, HOME=str(self.home), PYTHONPATH=str(REPO))
        procs = [
            subprocess.Popen(
                [sys.executable, "-c", code, tag], env=env, cwd=REPO
            )
            for tag in ("a", "b")
        ]
        codes = [proc.wait(timeout=60) for proc in procs]
        for code in codes:
            self.assertEqual(code, 0)
        data = json.loads(
            (self.home / ".erplibre" / "todo_prefs.json").read_text()
        )
        self.assertEqual(len(data), 200)

    def test_json_that_is_not_an_object_reads_as_empty(self):
        from script.todo import todo_prefs, todo_telemetry

        base = self.home / ".erplibre"
        base.mkdir()
        (base / "todo_prefs.json").write_text("[1, 2]")
        (base / "todo_telemetry.json").write_text("[1, 2]")
        # _LAST[0] dédupe les ré-affichages consécutifs d'un même menu : le
        # remettre à sa valeur d'avant évite qu'un test suivant, dans le même
        # processus, hérite silencieusement de « TODO › X ».
        self.addCleanup(
            todo_telemetry._LAST.__setitem__, 0, todo_telemetry._LAST[0]
        )
        with patch.dict(os.environ, {"HOME": str(self.home)}):
            self.assertEqual(todo_prefs.load(), {})
            todo_prefs.set("k", 1)
            self.assertEqual(todo_prefs.load(), {"k": 1})
            todo_telemetry._LAST[0] = None
            todo_telemetry.record("TODO › X")
            self.assertEqual(todo_telemetry.load()["paths"], {"TODO › X": 1})

    def test_prefs_reset_counts_and_clears(self):
        from script.todo import todo_prefs

        with patch.dict(os.environ, {"HOME": str(self.home)}):
            todo_prefs.set("a", 1)
            todo_prefs.set("b", 2)
            self.assertEqual(todo_prefs.reset(), 2)
            self.assertEqual(todo_prefs.load(), {})

    def test_a_read_only_directory_never_raises(self):
        from script.todo import todo_prefs, todo_telemetry

        # Racine : chmod ne bloque plus rien, `set()` réussirait et
        # l'assertion « défaut » échouerait pour une raison étrangère au
        # module (un shell Docker de développement tourne souvent ainsi).
        if os.geteuid() == 0:
            self.skipTest(
                "racine : les permissions de répertoire ne bloquent rien"
            )

        self.addCleanup(
            todo_telemetry._LAST.__setitem__, 0, todo_telemetry._LAST[0]
        )
        base = self.home / ".erplibre"
        base.mkdir()
        base.chmod(0o500)
        try:
            with patch.dict(os.environ, {"HOME": str(self.home)}):
                todo_telemetry._LAST[0] = None
                todo_telemetry.record("TODO › Y")
                todo_prefs.set("k", 1)
                self.assertEqual(todo_prefs.get("k", "défaut"), "défaut")
        finally:
            base.chmod(0o700)


if __name__ == "__main__":
    unittest.main()
