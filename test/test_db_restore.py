#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""La place qu'on peut écrire, quota de l'utilisateur compris.

Rien ici ne touche le noyau : « shutil.disk_usage » et l'appel
« quotactl_fd » sont bouchonnés. Ce qui est éprouvé, c'est la DÉCISION que
le script prend sur leurs réponses. Le choix du dossier d'extraction est
dans « test_db_restore_env.py », le nettoyage d'une restauration ratée dans
« test_db_restore_cleanup.py ».
"""

import os
import struct
import sys
import tempfile
import unittest
from collections import namedtuple
from unittest import mock

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
)

from script.database import db_restore  # noqa: E402

Usage = namedtuple("Usage", "total used free")
GIO = 1024**3


class _DansUnDossier(unittest.TestCase):
    """Un dossier de travail jetable, qui devient le dossier courant."""

    def setUp(self):
        dossier = tempfile.TemporaryDirectory()
        self.addCleanup(dossier.cleanup)
        self.dossier = dossier.name
        ancien = os.getcwd()
        os.chdir(self.dossier)
        self.addCleanup(os.chdir, ancien)


class _FausseLibc:
    """« syscall » qui remplit le tampon comme le ferait le noyau."""

    def __init__(self, code=0, dur=0, utilise=0):
        self.code = code
        self.dur = dur
        self.utilise = utilise
        self.appels = []

    def syscall(self, numero, fd, commande, uid, buf):
        self.appels.append((numero, commande, uid))
        entete = struct.pack("=3Q", self.dur, self.dur, self.utilise)
        buf.raw = entete + bytes(len(buf.raw) - len(entete))
        return self.code


class TestEspaceUtilisable(_DansUnDossier):
    """Le quota, quand il existe, plafonne la place du système de fichiers."""

    def _mesurer(self, libc, libre=50 * GIO):
        with (
            mock.patch.object(
                db_restore.shutil,
                "disk_usage",
                return_value=Usage(100 * GIO, 0, libre),
            ),
            mock.patch("ctypes.CDLL", return_value=libc),
        ):
            return db_restore.espace_utilisable(self.dossier)

    def test_le_quota_plafonne_la_place(self):
        # Limite en Kio, usage en octets.
        libc = _FausseLibc(dur=4 * 1024 * 1024, utilise=GIO)
        self.assertEqual(self._mesurer(libc), 3 * GIO)
        numero, commande, uid = libc.appels[0]
        self.assertEqual(numero, 443)
        self.assertEqual(commande, 0x800007 << 8)
        self.assertEqual(uid, os.getuid())

    def test_la_place_du_disque_gagne_si_elle_est_plus_basse(self):
        libc = _FausseLibc(dur=100 * 1024 * 1024, utilise=0)
        self.assertEqual(self._mesurer(libc, libre=2 * GIO), 2 * GIO)

    def test_un_quota_depasse_rend_zero(self):
        libc = _FausseLibc(dur=1024, utilise=2 * 1024 * 1024)
        self.assertEqual(self._mesurer(libc), 0)

    def test_sans_limite_dure_la_place_du_disque_est_rendue(self):
        self.assertEqual(self._mesurer(_FausseLibc(dur=0)), 50 * GIO)

    def test_un_appel_refuse_rend_la_place_du_disque(self):
        libc = _FausseLibc(code=-1, dur=1024, utilise=0)
        self.assertEqual(self._mesurer(libc), 50 * GIO)

    def test_une_libc_introuvable_rend_la_place_du_disque(self):
        with (
            mock.patch.object(
                db_restore.shutil,
                "disk_usage",
                return_value=Usage(100 * GIO, 0, 7),
            ),
            mock.patch("ctypes.CDLL", side_effect=OSError("absente")),
        ):
            self.assertEqual(db_restore.espace_utilisable(self.dossier), 7)


@unittest.skipIf(os.geteuid() == 0, "root lit tout : aucun refus à simuler")
class TestAccesImage(_DansUnDossier):
    """Une archive que le compte courant ne peut pas lire doit être dite
    comme telle : sans quoi elle passe pour absente, puis Odoo répond « Not
    a zipped dump file », qui accuse l'archive et non le droit qui manque.
    """

    def setUp(self):
        super().setUp()
        os.mkdir("image_db")
        with open("image_db/base.zip", "wb") as fichier:
            fichier.write(b"PK\x05\x06" + b"\x00" * 18)
        # Rendre les droits avant le nettoyage du dossier jetable. Les
        # nettoyages tournent du dernier au premier : le dossier redevient
        # traversable AVANT qu'on touche au fichier qu'il contient.
        self.addCleanup(os.chmod, "image_db/base.zip", 0o644)
        self.addCleanup(os.chmod, "image_db", 0o755)

    def test_une_archive_lisible_passe(self):
        self.assertIsNone(db_restore.acces_image("base"))
        self.assertIsNone(db_restore.acces_image("base.zip"))

    def test_une_archive_absente_n_est_pas_un_refus(self):
        # La restauration signale l'absence avec son propre message.
        self.assertIsNone(db_restore.acces_image("autre"))
        os.symlink("/inexistant/base.zip", "image_db/lien.zip")
        self.assertIsNone(db_restore.acces_image("lien"))

    def test_un_fichier_illisible_nomme_compte_proprietaire_et_mode(self):
        os.chmod("image_db/base.zip", 0o000)
        message = db_restore.acces_image("base")
        compte = db_restore._compte(os.geteuid())
        self.assertIn("n'est pas lisible par le compte " + compte, message)
        self.assertIn("mode 0000", message)
        # L'archive est au compte courant : un chmod suffit, sans sudo.
        self.assertIn("chmod u+r image_db/base.zip", message)
        self.assertNotIn("sudo", message)
        self.assertNotIn("introuvable", message)

    def test_un_dossier_non_traversable_est_nomme(self):
        # Le cas où « os.path.exists » rend faux : sans droit d'exécution
        # sur image_db, l'archive n'est même pas visible.
        os.chmod("image_db", 0o600)
        self.assertFalse(os.path.exists("image_db/base.zip"))
        message = db_restore.acces_image("base")
        self.assertIn("refuse le passage", message)
        self.assertIn("chmod u+x", message)
        self.assertIn(os.path.join(self.dossier, "image_db"), message)
        self.assertNotIn("introuvable", message)

    def test_l_archive_d_un_autre_compte_propose_chown(self):
        # Le cas réel : déposée sous un compte, lue sous celui d'Odoo.
        os.chmod("image_db/base.zip", 0o000)
        with mock.patch.object(db_restore, "_a_moi", return_value=False):
            message = db_restore.acces_image("base")
        compte = db_restore._compte(os.geteuid())
        self.assertIn(f"sudo chown {compte}: image_db/base.zip", message)

    def test_restaurer_s_arrete_avant_odoo(self):
        os.chmod("image_db/base.zip", 0o000)
        with (
            mock.patch.object(db_restore, "bases_existantes") as bases,
            mock.patch.object(db_restore, "charger") as charger,
        ):
            with self.assertRaises(SystemExit) as fin:
                db_restore.restaurer("./odoo_bin.sh db", "base", "cible")
        self.assertIn("n'est pas lisible", str(fin.exception.code))
        charger.assert_not_called()
        bases.assert_not_called()

    def test_sans_cache_l_arret_precede_le_mot_de_passe(self):
        os.chmod("image_db/base.zip", 0o000)
        argv = ["db_restore.py", "-d", "cible", "--ignore_cache"]
        argv += ["--image", "base"]
        with (
            mock.patch.object(sys, "argv", argv),
            mock.patch.object(db_restore, "ask_master_password") as mot,
            mock.patch("sys.stdout"),
        ):
            with self.assertRaises(SystemExit) as fin:
                db_restore.main()
        self.assertEqual(1, fin.exception.code)
        mot.assert_not_called()

    def test_avec_cache_l_archive_peut_manquer(self):
        # Le cache se clone sans le zip : main ne bloque pas d'avance.
        os.chmod("image_db/base.zip", 0o000)
        argv = ["db_restore.py", "-d", "cible", "--image", "base"]
        with (
            mock.patch.object(sys, "argv", argv),
            mock.patch.object(db_restore, "chemin_config", return_value=None),
            mock.patch.object(db_restore, "restaurer_cible") as restaurer,
        ):
            db_restore.main()
        restaurer.assert_called_once()


if __name__ == "__main__":
    unittest.main()
