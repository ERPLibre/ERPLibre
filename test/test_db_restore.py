#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""La restauration : place d'extraction, quota, et refus d'une base vide.

Rien ici ne touche PostgreSQL, Odoo ni le noyau : « psql », « odoo_bin.sh »,
« shutil.disk_usage » et l'appel « quotactl_fd » sont bouchonnés. Ce qui est
éprouvé, c'est la DÉCISION que le script prend sur leurs réponses.
"""

import argparse
import io
import os
import struct
import sys
import tempfile
import unittest
import zipfile
from collections import namedtuple
from contextlib import redirect_stdout
from unittest import mock

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
)

from script.analyse import lib_analyse  # noqa: E402
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


class TestRestoreEnv(_DansUnDossier):
    """Le temporaire par défaut s'il suffit, sinon le cache utilisateur."""

    def setUp(self):
        super().setUp()
        os.makedirs("image_db")
        with zipfile.ZipFile(os.path.join("image_db", "img.zip"), "w") as z:
            z.writestr("dump.sql", b"x" * 600)
            z.writestr("filestore/ab/cdef", b"y" * 400)
            z.writestr("manifest.json", b"z" * 5000)
        self.cache = os.path.join(self.dossier, "xdg")
        patcher = mock.patch.dict(os.environ, {"XDG_CACHE_HOME": self.cache})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.repli = os.path.join(self.cache, "erplibre_restore")

    def _places(self, defaut, repli):
        def espace(chemin):
            return repli if chemin == self.repli else defaut

        return mock.patch.object(
            db_restore, "espace_utilisable", side_effect=espace
        )

    def test_une_image_absente_ne_change_rien(self):
        self.assertIsNone(db_restore.restore_env("absente"))

    def test_le_defaut_qui_suffit_est_garde(self):
        # Besoin : 1000 octets (dump + filestore, le manifeste ne compte
        # pas), donc 1100 avec la marge.
        with self._places(defaut=1101, repli=10**9):
            self.assertIsNone(db_restore.restore_env("img"))
        self.assertFalse(os.path.exists(self.repli))

    def test_un_defaut_trop_petit_bascule_sur_le_cache_xdg(self):
        with self._places(defaut=1100, repli=10**9):
            env = db_restore.restore_env("img")
        self.assertEqual(env["TMPDIR"], self.repli)
        self.assertTrue(os.path.isdir(self.repli))

    def test_sans_xdg_le_repli_est_sous_le_home(self):
        with (
            mock.patch.dict(os.environ, {"HOME": self.dossier}),
            mock.patch.dict(os.environ, {"XDG_CACHE_HOME": ""}),
            mock.patch.object(
                db_restore, "espace_utilisable", side_effect=[0, 10**9]
            ),
        ):
            env = db_restore.restore_env("img")
        self.assertEqual(
            env["TMPDIR"],
            os.path.join(self.dossier, ".cache", "erplibre_restore"),
        )

    def test_deux_dossiers_trop_petits_avertissent_et_prennent_le_plus_grand(
        self,
    ):
        with (
            self._places(defaut=100, repli=500),
            self.assertLogs(db_restore._logger, "WARNING") as journal,
        ):
            env = db_restore.restore_env("img")
        self.assertEqual(env["TMPDIR"], self.repli)
        self.assertIn("risque d'échouer", "\n".join(journal.output))

    def test_un_repli_plus_petit_que_le_defaut_n_est_pas_pris(self):
        with (
            self._places(defaut=500, repli=100),
            self.assertLogs(db_restore._logger, "WARNING"),
        ):
            self.assertIsNone(db_restore.restore_env("img"))


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


class TestVerifyLoaded(unittest.TestCase):
    """Une base vide restaurée par ce lancement est supprimée, puis refusée."""

    def setUp(self):
        patcher = mock.patch.object(db_restore, "drop_database")
        self.drop = patcher.start()
        self.addCleanup(patcher.stop)

    def _psql(self, **kwargs):
        return mock.patch.object(lib_analyse, "run_psql", **kwargs)

    def test_la_requete_lit_pg_class_et_non_information_schema(self):
        with self._psql(return_value="t\n") as psql:
            db_restore.verify_loaded("_cache_img", "./odoo_bin.sh db")
        sql = psql.call_args.args[1]
        self.assertIn("to_regclass('public.ir_module_module')", sql)
        self.assertNotIn("information_schema", sql)

    def test_une_base_pleine_passe(self):
        with self._psql(return_value="t\n"):
            db_restore.verify_loaded("_cache_img", "./odoo_bin.sh db")
        self.drop.assert_not_called()

    def test_une_base_vide_est_supprimee_puis_refusee(self):
        with (
            self._psql(return_value="f\n"),
            self.assertLogs(db_restore._logger, "ERROR"),
            self.assertRaises(SystemExit) as arret,
        ):
            db_restore.verify_loaded("_cache_img", "./odoo_bin.sh db")
        self.drop.assert_called_once_with("./odoo_bin.sh db", "_cache_img")
        self.assertIn("supprimée", str(arret.exception))

    def test_un_psql_injoignable_avertit_et_laisse_continuer(self):
        erreur = lib_analyse.AnalyseError("connection refused")
        with (
            self._psql(side_effect=erreur),
            self.assertLogs(db_restore._logger, "WARNING") as journal,
        ):
            db_restore.verify_loaded("_cache_img", "./odoo_bin.sh db")
        self.drop.assert_not_called()
        self.assertIn("non vérifié", "\n".join(journal.output))


class TestCheckCacheSource(unittest.TestCase):
    """Un « _cache_ » déjà là est contrôlé avant d'être cloné."""

    def test_un_cache_vide_est_refuse(self):
        with (
            mock.patch.object(lib_analyse, "run_psql", return_value="f\n"),
            self.assertRaises(SystemExit) as arret,
        ):
            db_restore.check_cache_source("_cache_img")
        self.assertIn("--clean_cache", str(arret.exception))

    def test_un_cache_plein_passe(self):
        with mock.patch.object(lib_analyse, "run_psql", return_value="t\n"):
            db_restore.check_cache_source("_cache_img")

    def test_un_psql_muet_laisse_passer(self):
        erreur = lib_analyse.AnalyseError("no password supplied")
        with (
            mock.patch.object(lib_analyse, "run_psql", side_effect=erreur),
            self.assertLogs(db_restore._logger, "WARNING"),
        ):
            db_restore.check_cache_source("_cache_img")


def _config(**kwargs):
    valeurs = dict(
        database="cible",
        image="img",
        clean_cache=False,
        ignore_cache=False,
        only_drop=False,
        neutralize=False,
    )
    valeurs.update(kwargs)
    return argparse.Namespace(**valeurs)


class TestRestoreOrClone(unittest.TestCase):
    def setUp(self):
        self.verifie = []
        for nom, effet in (
            ("check_output", lambda *a, **k: b""),
            ("restore_env", lambda image: None),
            ("verify_filestore", lambda *a: None),
            ("verify_loaded", lambda base, arg: self.verifie.append(base)),
        ):
            patcher = mock.patch.object(db_restore, nom, side_effect=effet)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _lancer(self, config, caches):
        with redirect_stdout(io.StringIO()):
            db_restore.restore_or_clone(
                config, "./odoo_bin.sh db", "_cache_img", caches
            )

    def test_ignore_cache_verifie_la_base_restauree(self):
        self._lancer(_config(ignore_cache=True), [])
        self.assertEqual(self.verifie, ["cible"])

    def test_un_nouveau_cache_est_verifie_avant_le_clone(self):
        self._lancer(_config(), [])
        self.assertEqual(self.verifie, ["_cache_img"])

    def test_un_clone_ne_reverifie_pas_la_copie(self):
        self._lancer(_config(), ["_cache_img"])
        self.assertEqual(self.verifie, [])


class TestMainRefusesEmptyCache(_DansUnDossier):
    """Le refus d'un cache vide arrive AVANT la suppression de la cible."""

    def test_la_cible_n_est_pas_supprimee(self):
        with open("config.conf", "w") as fichier:
            fichier.write("[options]\nadmin_passwd = admin\n")
        with (
            mock.patch.object(
                db_restore, "get_config", return_value=_config()
            ),
            mock.patch.object(
                db_restore,
                "get_list_db_cache",
                return_value=(["cible", "_cache_img"], ["_cache_img"]),
            ),
            mock.patch.object(db_restore, "drop_database") as drop,
            mock.patch.object(lib_analyse, "run_psql", return_value="f\n"),
            self.assertRaises(SystemExit) as sortie,
        ):
            db_restore.main()
        self.assertIn("--clean_cache", str(sortie.exception))
        drop.assert_not_called()


if __name__ == "__main__":
    unittest.main()
