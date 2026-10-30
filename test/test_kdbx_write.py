#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'écriture du coffre KeePass sous verrou, relecture et renommage.

`HOME` pointe vers un dossier temporaire : les verrous vivent sous
`~/.erplibre/locks`. Les coffres sont créés dans le test, avec la
dérivation rapide d'`argon2_rapide` ; les sous-processus l'installent
aussi, sans quoi ils ne rouvriraient pas ces coffres.
"""

import io
import os
import stat
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# Argon2 remplacé pour tout le module : voir argon2_rapide.py.
from argon2_rapide import setUpModule  # noqa: E402,F401

from script.todo import kdbx_write  # noqa: E402
from script.todo.mail.rules.lock import file_lock  # noqa: E402
from script.todo.mail.secrets import SecretStore, create_kdbx  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
TEST_DIR = Path(__file__).resolve().parent
MAITRE = "maitre-essai"


def ouvrir(path):
    from pykeepass import PyKeePass

    return PyKeePass(str(path), password=MAITRE)


def titres(path) -> set:
    return {e.title for e in ouvrir(path).entries}


class KdbxCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dossier = Path(tmp.name)
        maison = mock.patch.dict(os.environ, {"HOME": str(self.dossier)})
        maison.start()
        self.addCleanup(maison.stop)
        self.path = self.dossier / "coffre.kdbx"
        create_kdbx(str(self.path), MAITRE)

    def ajouter(self, kp, titre, secret="s"):
        with kdbx_write.writing(kp) as write:
            write.kp.add_entry(write.kp.root_group, titre, "", secret)


class TestLockPath(KdbxCase):
    def test_two_spellings_of_one_file_share_one_lock(self):
        lien = self.dossier / "lien.kdbx"
        lien.symlink_to(self.path)
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(self.dossier)
        verrous = {
            kdbx_write.lock_path_for(chemin)
            for chemin in ("coffre.kdbx", str(self.path), str(lien))
        }
        self.assertEqual(len(verrous), 1)
        verrou = verrous.pop()
        self.assertEqual(verrou.parent, self.dossier / ".erplibre" / "locks")
        self.assertEqual(stat.S_IMODE(verrou.parent.stat().st_mode), 0o700)
        autre = self.dossier / "autre.kdbx"
        self.assertNotEqual(kdbx_write.lock_path_for(autre), verrou)

    def test_a_held_lock_raises_busy_after_the_wait(self):
        verrou = kdbx_write.lock_path_for(self.path)
        with file_lock(verrou, wait=0) as tenu:
            self.assertTrue(tenu)
            debut = time.monotonic()
            with self.assertRaises(kdbx_write.KdbxBusy):
                with kdbx_write.writing(ouvrir(self.path), wait=0.1):
                    self.fail("bloc exécuté sans le verrou")
            self.assertLess(time.monotonic() - debut, 2.0)

    def test_the_refresh_lock_is_distinct_from_the_vault_lock(self):
        ref = "kdbx:ERPLibre/Mail/perso/oauth-token"
        self.assertNotEqual(
            kdbx_write.refresh_lock_path(ref),
            kdbx_write.lock_path_for(self.path),
        )
        with kdbx_write.refresh_lock(ref):
            self.ajouter(ouvrir(self.path), "pendant")
            with self.assertRaises(kdbx_write.KdbxBusy):
                with kdbx_write.refresh_lock(ref, wait=0.1):
                    pass
        self.assertIn("pendant", titres(self.path))


class TestSave(KdbxCase):
    def test_the_saved_vault_is_0600_whatever_the_umask(self):
        os.chmod(self.path, 0o644)
        ancien = os.umask(0o022)
        try:
            self.ajouter(ouvrir(self.path), "entree")
        finally:
            os.umask(ancien)
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        self.assertIn("entree", titres(self.path))

    def test_a_failed_save_leaves_the_vault_intact_and_no_temporary(self):
        avant = self.path.read_bytes()
        kp = ouvrir(self.path)
        with mock.patch.object(
            kdbx_write.os, "replace", side_effect=OSError("disque plein")
        ):
            with self.assertRaises(OSError):
                self.ajouter(kp, "perdue")
        self.assertEqual(self.path.read_bytes(), avant)
        self.assertEqual(
            sorted(os.listdir(self.dossier)),
            [
                ".erplibre",
                "coffre.kdbx",
            ],
        )
        with self.assertRaises(RuntimeError):
            with kdbx_write.writing(ouvrir(self.path)) as write:
                write.kp.add_entry(write.kp.root_group, "x", "", "")
                raise RuntimeError("bloc interrompu")
        self.assertEqual(self.path.read_bytes(), avant)

    def test_writing_rereads_before_writing(self):
        a = ouvrir(self.path)
        b = ouvrir(self.path)
        self.ajouter(a, "p1")
        self.ajouter(b, "p2")
        self.assertEqual(titres(self.path), {"p1", "p2"})

    def test_a_stream_or_double_keeps_the_plain_save(self):
        double = mock.MagicMock()
        with kdbx_write.writing(double) as write:
            self.assertIs(write.kp, double)
        double.save.assert_called_once_with()
        double.reload.assert_not_called()
        flux = SimpleNamespace(
            filename=io.BytesIO(), save=mock.Mock(), reload=mock.Mock()
        )
        with kdbx_write.writing(flux) as write:
            write.skip()
        flux.save.assert_not_called()
        flux.reload.assert_not_called()
        self.assertFalse((self.dossier / ".erplibre").exists())

    def test_a_symlinked_vault_is_written_through_the_link(self):
        cible = self.dossier / "synchro"
        cible.mkdir()
        reel = cible / "coffre.kdbx"
        os.replace(self.path, reel)
        self.path.symlink_to(reel)
        self.ajouter(ouvrir(self.path), "a-travers")
        self.assertTrue(self.path.is_symlink())
        self.assertIn("a-travers", titres(reel))
        self.assertEqual(stat.S_IMODE(reel.stat().st_mode), 0o600)

    def test_an_orphan_temporary_is_removed_on_the_next_write(self):
        orphelin = self.dossier / ".coffre.kdbx.zz.tmp.kdbx"
        orphelin.write_bytes(b"copie du coffre")
        voisin = self.dossier / ".autre.kdbx.zz.tmp.kdbx"
        voisin.write_bytes(b"autre coffre")
        self.ajouter(ouvrir(self.path), "entree")
        self.assertFalse(orphelin.exists())
        self.assertTrue(voisin.exists())

    def test_skip_writes_nothing(self):
        avant = self.path.stat().st_mtime_ns, self.path.stat().st_ino
        with kdbx_write.writing(ouvrir(self.path)) as write:
            write.skip()
        self.assertEqual(
            (self.path.stat().st_mtime_ns, self.path.stat().st_ino), avant
        )


class TestTwoProcesses(KdbxCase):
    SCRIPT = textwrap.dedent(
        """
        import os, sys, time
        sys.path.insert(0, {test_dir!r})
        import argon2_rapide
        argon2_rapide.setUpModule()
        from types import SimpleNamespace
        from pykeepass import PyKeePass
        from script.todo.mail.secrets import SecretStore

        kp = PyKeePass({path!r}, password={maitre!r})
        store = SecretStore(
            kdbx_manager=SimpleNamespace(get_kdbx=lambda: kp),
            use_keyring=False,
        )
        while not os.path.exists({depart!r}):
            time.sleep(0.01)
        for i in range(3):
            store.set(f"kdbx:ERPLibre/Mail/{{sys.argv[1]}}-{{i}}", "s")
        """
    )

    def test_two_processes_writing_together_lose_nothing(self):
        depart = self.dossier / "depart"
        script = self.SCRIPT.format(
            test_dir=str(TEST_DIR),
            path=str(self.path),
            maitre=MAITRE,
            depart=str(depart),
        )
        env = dict(os.environ, PYTHONPATH=str(REPO), HOME=str(self.dossier))
        processus = [
            subprocess.Popen(
                [sys.executable, "-c", script, nom],
                cwd=str(REPO),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            for nom in ("perso", "boite-regles")
        ]
        time.sleep(0.5)
        depart.write_text("go")
        for proc in processus:
            sortie, erreur = proc.communicate(timeout=60)
            self.assertEqual(proc.returncode, 0, erreur.decode())
        store = SecretStore(
            kdbx_manager=SimpleNamespace(get_kdbx=lambda: ouvrir(self.path)),
            use_keyring=False,
        )
        for nom in ("perso", "boite-regles"):
            for i in range(3):
                self.assertEqual(
                    store.get(f"kdbx:ERPLibre/Mail/{nom}-{i}"), "s"
                )


if __name__ == "__main__":
    unittest.main()
