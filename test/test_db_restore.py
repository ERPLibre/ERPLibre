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


if __name__ == "__main__":
    unittest.main()
