#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Où extraire une image : le besoin réel, et le choix tmpfs ou disque.

Odoo extrait « dump.sql » et le filestore dans un dossier temporaire avant
de charger quoi que ce soit. Deux erreurs de calcul y mènent à un échec en
pleine extraction : compter les tailles brutes là où un tmpfs compte des
pages entières, et laisser une grosse extraction en mémoire vive pendant
que PostgreSQL charge la base.

Rien ici ne touche une base ni Odoo : les fonctions pures reçoivent leurs
mesures en arguments, et « restore_env » lit une archive fabriquée dans un
dossier jetable.
"""

import os
import shutil
import sys
import tempfile
import unittest
import zipfile
from unittest import mock

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
)

from script.database import db_restore  # noqa: E402

GIO = db_restore.GIO
MIO = 1048576


class TestBesoinExtraction(unittest.TestCase):
    def test_chaque_fichier_compte_en_pages_entieres(self):
        # Un octet coûte une page, une page plus un octet en coûte deux.
        besoin, entrees = db_restore.besoin_extraction(
            [("dump.sql", 1), ("filestore/ab/x", 4097)], page=4096, surcout=0
        )
        self.assertEqual(besoin, 4096 + 8192)
        self.assertEqual(entrees, 2 + 2)  # deux fichiers, deux dossiers

    def test_un_fichier_vide_ne_coute_aucune_page(self):
        besoin, _ = db_restore.besoin_extraction(
            [("dump.sql", 0)], page=4096, surcout=0
        )
        self.assertEqual(besoin, 0)

    def test_les_dossiers_sont_deduits_des_chemins(self):
        # L'archive ne liste pas ses dossiers ; l'extraction les crée
        # quand même, et chacun a son surcoût.
        _, entrees = db_restore.besoin_extraction(
            [
                ("filestore/ab/1", 10),
                ("filestore/ab/2", 10),
                ("filestore/cd/3", 10),
            ],
            page=4096,
            surcout=0,
        )
        # trois fichiers ; filestore, filestore/ab, filestore/cd
        self.assertEqual(entrees, 6)

    def test_un_dossier_liste_n_est_pas_compte_deux_fois(self):
        _, entrees = db_restore.besoin_extraction(
            [("filestore/", 0), ("filestore/ab/", 0), ("filestore/ab/1", 1)],
            page=4096,
            surcout=0,
        )
        self.assertEqual(entrees, 3)

    def test_le_surcout_s_ajoute_par_entree(self):
        besoin, entrees = db_restore.besoin_extraction(
            [("filestore/ab/1", 1)], page=4096, surcout=1000
        )
        self.assertEqual(entrees, 3)
        self.assertEqual(besoin, 4096 + 3 * 1000)

    def test_beaucoup_de_petits_fichiers_pesent_plus_que_leur_somme(self):
        # Le mode de défaillance : la somme brute dit 100 Mio, le tmpfs en
        # demande 400 — un quota jugé suffisant ne l'est pas.
        membres = [
            (f"filestore/{i % 256:02x}/{i}", 1000) for i in range(100000)
        ]
        brut = sum(taille for _, taille in membres)
        besoin, _ = db_restore.besoin_extraction(membres, page=4096)
        self.assertGreater(besoin, 4 * brut)


class TestSeuilTmpfs(unittest.TestCase):
    def test_sans_memoire_connue_le_seuil_fixe(self):
        self.assertEqual(db_restore.seuil_tmpfs(None), db_restore.SEUIL_TMPFS)

    def test_le_quart_de_la_memoire_quand_il_est_plus_bas(self):
        self.assertEqual(db_restore.seuil_tmpfs(2 * GIO), GIO // 2)

    def test_le_seuil_fixe_quand_la_memoire_abonde(self):
        self.assertEqual(db_restore.seuil_tmpfs(64 * GIO), GIO)


class TestRaisonDExtraireAilleurs(unittest.TestCase):
    def decide(self, besoin, **kw):
        valeurs = dict(
            entrees=10,
            fstype="ext4",
            memoire=16 * GIO,
            libre_fs=100 * GIO,
            quota=None,
            inodes=None,
        )
        valeurs.update(kw)
        return db_restore.raison_d_extraire_ailleurs(besoin, **valeurs)

    def test_une_petite_image_reste_en_tmpfs(self):
        self.assertIsNone(self.decide(50 * MIO, fstype="tmpfs"))

    def test_une_grosse_image_quitte_le_tmpfs_meme_si_elle_y_tient(self):
        raison = self.decide(3 * GIO, fstype="tmpfs", libre_fs=10 * GIO)
        self.assertEqual(raison[0], "tmpfs")
        self.assertIn("tmpfs", raison[1])

    def test_ramfs_est_aussi_de_la_memoire(self):
        self.assertEqual(self.decide(3 * GIO, fstype="ramfs")[0], "tmpfs")

    def test_le_seuil_suit_la_memoire_disponible(self):
        # 600 Mio passent sous 1 Gio, pas sous le quart de 2 Gio.
        self.assertIsNone(self.decide(600 * MIO, fstype="tmpfs"))
        raison = self.decide(600 * MIO, fstype="tmpfs", memoire=2 * GIO)
        self.assertEqual(raison[0], "tmpfs")

    def test_sur_disque_une_grosse_image_reste_si_la_place_suffit(self):
        self.assertIsNone(self.decide(20 * GIO, fstype="ext4"))

    def test_le_quota_plus_bas_que_la_place_est_nomme(self):
        raison = self.decide(
            500 * MIO, fstype="tmpfs", libre_fs=9 * GIO, quota=400 * MIO
        )
        self.assertEqual(raison[0], "quota")

    def test_la_marge_compte(self):
        # Le besoin brut tient dans le quota, pas avec sa marge.
        besoin = 400 * MIO
        quota = besoin + MIO
        self.assertLess(quota, db_restore.avec_marge(besoin))
        raison = self.decide(besoin, libre_fs=9 * GIO, quota=quota)
        self.assertEqual(raison[0], "quota")

    def test_la_place_manque(self):
        raison = self.decide(2 * GIO, libre_fs=GIO)
        self.assertEqual(raison[0], "place")

    def test_les_inodes_manquent(self):
        raison = self.decide(MIO, entrees=2000000, inodes=1000000)
        self.assertEqual(raison[0], "inodes")

    def test_tout_suffit(self):
        self.assertIsNone(
            self.decide(MIO, quota=8 * GIO, inodes=1000000, entrees=10)
        )


class TestTypeSystemeFichiers(unittest.TestCase):
    def setUp(self):
        self.dossier = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dossier)

    def mounts(self, texte):
        chemin = os.path.join(self.dossier, "mounts")
        with open(chemin, "w") as fichier:
            fichier.write(texte)
        return chemin

    def test_le_point_de_montage_le_plus_long_l_emporte(self):
        chemin = self.mounts(
            "/dev/vda1 / ext4 rw 0 0\n"
            "tmpfs /tmp tmpfs rw,usrquota 0 0\n"
            "/dev/vdb1 /tmpx xfs rw 0 0\n"
        )
        with mock.patch("os.path.realpath", side_effect=lambda p: p):
            self.assertEqual(
                db_restore.type_systeme_fichiers("/tmp/a/b", chemin), "tmpfs"
            )
            self.assertEqual(
                db_restore.type_systeme_fichiers("/tmp", chemin), "tmpfs"
            )
            # « /tmpx » n'est pas sous « /tmp » : un préfixe de texte ne
            # fait pas un sous-dossier.
            self.assertEqual(
                db_restore.type_systeme_fichiers("/tmpx/a", chemin), "xfs"
            )
            self.assertEqual(
                db_restore.type_systeme_fichiers("/home", chemin), "ext4"
            )

    def test_le_dernier_montage_au_meme_endroit_masque_l_autre(self):
        chemin = self.mounts(
            "/dev/vda1 / ext4 rw 0 0\n"
            "/dev/vda2 /tmp ext4 rw 0 0\n"
            "tmpfs /tmp tmpfs rw 0 0\n"
        )
        with mock.patch("os.path.realpath", side_effect=lambda p: p):
            self.assertEqual(
                db_restore.type_systeme_fichiers("/tmp", chemin), "tmpfs"
            )

    def test_l_espace_echappe_en_octal_est_decode(self):
        chemin = self.mounts(
            "/dev/vda1 / ext4 rw 0 0\ntmpfs /mnt/a\\040b tmpfs rw 0 0\n"
        )
        with mock.patch("os.path.realpath", side_effect=lambda p: p):
            self.assertEqual(
                db_restore.type_systeme_fichiers("/mnt/a b/c", chemin), "tmpfs"
            )

    def test_sans_proc_mounts_rien_n_est_affirme(self):
        absent = os.path.join(self.dossier, "absent")
        self.assertIsNone(db_restore.type_systeme_fichiers("/tmp", absent))


class TestMemoireDisponible(unittest.TestCase):
    def test_lit_memavailable_en_octets(self):
        with tempfile.NamedTemporaryFile("w", delete=False) as f:
            f.write("MemTotal: 100 kB\nMemAvailable:   2048 kB\n")
        self.addCleanup(os.remove, f.name)
        self.assertEqual(db_restore.memoire_disponible(f.name), 2048 * 1024)

    def test_absente_rend_none(self):
        with tempfile.NamedTemporaryFile("w", delete=False) as f:
            f.write("MemTotal: 100 kB\n")
        self.addCleanup(os.remove, f.name)
        self.assertIsNone(db_restore.memoire_disponible(f.name))


class TestRestoreEnv(unittest.TestCase):
    """« restore_env » sur une archive fabriquée, mesures bouchonnées."""

    def setUp(self):
        self.racine = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.racine)
        os.makedirs(os.path.join(self.racine, "image_db"))
        self.maison = os.path.join(self.racine, "maison")
        archive = os.path.join(self.racine, "image_db", "essai.zip")
        with zipfile.ZipFile(archive, "w") as z:
            z.writestr("dump.sql", "x" * 10)
            z.writestr("manifest.json", "{}" * 1000)
            z.writestr("filestore/ab/1", "y")
        avant = os.getcwd()
        os.chdir(self.racine)
        self.addCleanup(os.chdir, avant)

    def bouchonner(self, **valeurs):
        for nom, valeur in valeurs.items():
            patch = mock.patch.object(db_restore, nom, return_value=valeur)
            patch.start()
            self.addCleanup(patch.stop)
        patch = mock.patch.dict(
            os.environ, {"HOME": self.maison, "XDG_CACHE_HOME": ""}
        )
        patch.start()
        self.addCleanup(patch.stop)

    def test_le_manifeste_n_entre_pas_dans_le_besoin(self):
        membres = db_restore.membres_extraits(
            os.path.join("image_db", "essai.zip")
        )
        self.assertEqual(
            sorted(nom for nom, _ in membres), ["dump.sql", "filestore/ab/1"]
        )

    def test_le_temporaire_convient(self):
        self.bouchonner(
            type_systeme_fichiers="tmpfs",
            memoire_disponible=8 * GIO,
            quota_restant=None,
            inodes_libres=None,
        )
        self.assertIsNone(db_restore.restore_env("essai"))

    def test_le_quota_envoie_sur_disque_et_le_journal_le_nomme(self):
        self.bouchonner(
            type_systeme_fichiers="tmpfs",
            memoire_disponible=8 * GIO,
            quota_restant=1,
            inodes_libres=None,
        )
        with self.assertLogs(db_restore._logger, "INFO") as journal:
            env = db_restore.restore_env("essai")
        repli = os.path.join(self.maison, ".cache", "erplibre_restore")
        self.assertEqual(env["TMPDIR"], repli)
        self.assertTrue(os.path.isdir(repli))
        self.assertIn("(quota)", "\n".join(journal.output))

    def test_un_nom_qui_porte_deja_zip_designe_la_meme_archive(self):
        # « --image essai.zip » : Odoo n'ajoute pas un second « .zip ».
        self.bouchonner(
            type_systeme_fichiers="tmpfs",
            memoire_disponible=8 * GIO,
            quota_restant=1,
            inodes_libres=None,
        )
        with self.assertLogs(db_restore._logger, "INFO"):
            env = db_restore.restore_env("essai.zip")
        repli = os.path.join(self.maison, ".cache", "erplibre_restore")
        self.assertEqual(env["TMPDIR"], repli)

    def choisir(self, code, place_defaut, place_repli):
        """restore_env quand `code` écarte le défaut ; places en Mio."""
        self.bouchonner(
            raison_d_extraire_ailleurs=(code, "mesure bouchonnée"),
            type_systeme_fichiers="ext4",
            memoire_disponible=8 * GIO,
            quota_restant=None,
            inodes_libres=None,
        )
        repli = os.path.join(self.maison, ".cache", "erplibre_restore")

        def place(chemin):
            return (place_repli if chemin == repli else place_defaut) * MIO

        with (
            mock.patch.object(db_restore, "espace_utilisable", place),
            self.assertLogs(db_restore._logger, "INFO") as journal,
        ):
            env = db_restore.restore_env("essai")
        return env, repli, "\n".join(journal.output)

    def test_un_repli_plus_petit_que_le_defaut_n_est_pas_pris(self):
        env, _, journal = self.choisir("place", 500, 100)
        self.assertIsNone(env)
        self.assertIn("reste dans", journal)

    def test_un_repli_trop_petit_mais_plus_grand_que_le_defaut_est_pris(self):
        env, repli, journal = self.choisir("place", 100, 200)
        self.assertEqual(env["TMPDIR"], repli)
        self.assertIn("risque d'y échouer aussi", journal)

    def test_un_manque_d_inodes_prend_le_repli_meme_plus_petit(self):
        # La place en octets ne dit rien des inodes : le défaut en manque.
        env, repli, _ = self.choisir("inodes", 500, 100)
        self.assertEqual(env["TMPDIR"], repli)

    def test_xdg_cache_home_l_emporte_sur_le_home(self):
        xdg = os.path.join(self.racine, "xdg")
        with mock.patch.dict(os.environ, {"XDG_CACHE_HOME": xdg}):
            self.assertEqual(
                db_restore.dossier_travail(),
                os.path.join(xdg, "erplibre_restore"),
            )

    def test_chemin_image_suit_la_regle_d_odoo(self):
        attendu = os.path.join("image_db", "essai.zip")
        self.assertEqual(db_restore.chemin_image("essai"), attendu)
        self.assertEqual(db_restore.chemin_image("essai.zip"), attendu)
        # Un chemin est gardé tel quel, « .zip » ajouté s'il manque.
        self.assertEqual(
            db_restore.chemin_image("sous/essai"), "sous/essai.zip"
        )
        self.assertEqual(
            db_restore.chemin_image("/abs/essai.zip"), "/abs/essai.zip"
        )

    def test_x_et_x_zip_partagent_un_cache_un_chemin_n_en_a_pas(self):
        self.assertEqual(db_restore.nom_cache("essai"), "_cache_essai")
        self.assertEqual(db_restore.nom_cache("essai.zip"), "_cache_essai")
        self.assertIsNone(db_restore.nom_cache("sous/essai.zip"))

    def test_une_archive_illisible_est_laissee_a_odoo(self):
        with open(os.path.join("image_db", "tronquee.zip"), "wb") as f:
            f.write(b"PK\x03\x04 tronquee")
        with self.assertLogs(db_restore._logger, "WARNING"):
            self.assertIsNone(db_restore.restore_env("tronquee"))

    def test_sans_image_rien_a_decider_mais_le_journal_le_dit(self):
        with self.assertLogs(db_restore._logger, "WARNING") as journal:
            self.assertIsNone(db_restore.restore_env("absente"))
        self.assertIn("introuvable", "\n".join(journal.output))


if __name__ == "__main__":
    unittest.main()
