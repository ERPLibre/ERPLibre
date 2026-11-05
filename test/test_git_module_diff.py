#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Les modules qui diffèrent entre HEAD et `<distant>/<V>`, sur de vrais
dépôts git jetables."""

import os
import subprocess
import tempfile
import unittest
from unittest import mock

from script.git import git_freeze_diff
from script.git import git_module_diff as gmd

ENV = dict(
    os.environ,
    GIT_AUTHOR_NAME="essai",
    GIT_AUTHOR_EMAIL="essai@exemple.invalid",
    GIT_COMMITTER_NAME="essai",
    GIT_COMMITTER_EMAIL="essai@exemple.invalid",
    GIT_CONFIG_GLOBAL=os.devnull,
    GIT_CONFIG_SYSTEM=os.devnull,
)


def git(chemin, *args):
    return subprocess.run(
        ["git", "-C", chemin, *args],
        check=True,
        capture_output=True,
        text=True,
        env=ENV,
    ).stdout.strip()


def ecrire(chemin, relatif, texte="x\n"):
    fichier = os.path.join(chemin, relatif)
    os.makedirs(os.path.dirname(fichier), exist_ok=True)
    with open(fichier, "w") as fh:
        fh.write(texte)


def depot(chemin):
    os.makedirs(chemin, exist_ok=True)
    git(chemin, "init", "-q", "-b", "travail")
    return chemin


def committer(chemin, message="c"):
    git(chemin, "add", "-A")
    git(chemin, "commit", "-q", "-m", message)
    return git(chemin, "rev-parse", "HEAD")


class TestModuleDe(unittest.TestCase):
    def test_le_dossier_le_plus_profond_gagne(self):
        dossiers = {"a", "a/tests/b"}
        self.assertEqual(
            gmd.module_de("a/tests/b/x.py", dossiers), "a/tests/b"
        )
        self.assertEqual(gmd.module_de("a/models/m.py", dossiers), "a")

    def test_un_fichier_hors_module_ne_compte_pas(self):
        self.assertIsNone(gmd.module_de("README.md", {"a"}))
        self.assertIsNone(gmd.module_de("setup/a/setup.py", {"a"}))

    def test_un_depot_qui_est_un_module(self):
        self.assertEqual(gmd.module_de("models/m.py", {""}), "")


class TestDepot(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.d = depot(os.path.join(self.tmp.name, "depot"))
        for m in ("mod_change", "mod_intact", "mod_retire"):
            ecrire(self.d, f"{m}/__manifest__.py", "{}\n")
            ecrire(self.d, f"{m}/models/m.py")
        ecrire(self.d, "README.md")
        self.base = committer(self.d)
        # La branche distante de la version : une ref de suivi, comme
        # après un fetch, sans dépôt distant réel.
        git(self.d, "update-ref", "refs/remotes/OCA/18.0", self.base)
        ecrire(self.d, "mod_change/models/m.py", "y\n")
        ecrire(self.d, "mod_nouveau/__openerp__.py", "{}\n")
        ecrire(self.d, "README.md", "autre\n")
        git(self.d, "rm", "-q", "-r", "mod_retire")
        self.tete = committer(self.d)
        self.attendus = ["mod_change", "mod_nouveau", "mod_retire"]

    def analyser(self, *depots, mode=gmd.MODE_BRANCHE):
        return gmd.analyser(self.tmp.name, "18.0", list(depots), mode)

    def test_les_modules_changes_ajoutes_et_retires(self):
        self.assertEqual(
            gmd.modules_differents(self.d, "refs/remotes/OCA/18.0"),
            set(self.attendus),
        )

    def test_aucun_module_quand_head_est_la_branche(self):
        self.assertEqual(gmd.modules_differents(self.d, "HEAD"), set())

    def test_une_ref_inconnue_est_un_echec(self):
        self.assertIsNone(gmd.modules_differents(self.d, "refs/remotes/x/1"))

    def test_seule_une_branche_distante_compte(self):
        git(self.d, "branch", "17.0")
        self.assertEqual(
            gmd.reference(self.d, "17.0", "OCA"), (None, ["OCA/17.0"])
        )
        self.assertEqual(
            gmd.reference(self.d, "18.0", "OCA"),
            ("refs/remotes/OCA/18.0", ["OCA/18.0"]),
        )
        self.assertEqual(gmd.reference(self.d, "18.0", None), (None, []))

    def test_la_branche_du_manifeste_en_repli(self):
        git(self.d, "update-ref", "refs/remotes/F/18.0_dev", self.base)
        self.assertEqual(
            gmd.reference(self.d, "18.0", "F", "18.0_dev")[0],
            "refs/remotes/F/18.0_dev",
        )
        # Un commit à la place de la branche ne se cherche pas.
        self.assertEqual(
            gmd.reference(self.d, "18.0", "F", self.base),
            (None, ["F/18.0"]),
        )
        r = self.analyser(
            {"path": "depot", "remote": "F", "branch": "18.0_dev"}
        )
        self.assertEqual(r["modules"], self.attendus)
        self.assertEqual(r["repli"], [("depot", "F/18.0_dev")])

    def test_analyser_regroupe_et_signale_la_branche_absente(self):
        r = self.analyser(
            {"path": "depot", "remote": "OCA", "branch": "18.0"},
            {"path": "depot", "remote": "ERPLibre", "branch": "18.0_dev"},
        )
        self.assertEqual(r["modules"], self.attendus)
        self.assertEqual(list(r["par_depot"]), ["depot"])
        self.assertEqual(r["repli"], [])
        self.assertEqual(
            r["sans_branche"],
            [("depot", "ERPLibre/18.0 · ERPLibre/18.0_dev")],
        )

    def test_le_gel_compare_l_ancien_au_nouveau(self):
        # HEAD est sur la branche : le mode branche ne voit rien, le mode
        # gel voit ce que la comparaison a changé.
        git(self.d, "update-ref", "refs/remotes/OCA/18.0", self.tete)
        entree = {
            "path": "depot",
            "remote": "OCA",
            "branch": "18.0",
            "old": self.base,
            "new": self.tete,
        }
        self.assertEqual(self.analyser(entree)["modules"], [])
        r = self.analyser(entree, mode=gmd.MODE_GEL)
        self.assertEqual(r["modules"], self.attendus)

    def test_le_gel_met_a_part_l_apparu_et_l_absent(self):
        apparu = {"path": "depot", "remote": "OCA", "old": None}
        apparu["new"] = self.tete
        absent = dict(apparu, old="0" * 40)
        r = self.analyser(apparu, absent, mode=gmd.MODE_GEL)
        self.assertEqual(r["modules"], [])
        self.assertEqual(r["sans_ancien"], ["depot"])
        self.assertEqual(r["absents"], [("depot", "00000000")])

    def test_hors_manifeste_garde_sa_branche_en_mode_gel(self):
        git(self.d, "remote", "add", "origin", "https://exemple.invalid/o")
        git(self.d, "update-ref", "refs/remotes/origin/18.0", self.base)
        entree = gmd.depot_hors_manifeste(self.tmp.name, self.d)
        self.assertEqual(entree, {"path": "depot", "remote": None})
        r = self.analyser(entree, mode=gmd.MODE_GEL)
        self.assertEqual(r["modules"], self.attendus)


class TestDistantParDefaut(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.d = depot(os.path.join(self.tmp.name, "d"))

    def test_origin_d_abord(self):
        git(self.d, "remote", "add", "amont", "https://exemple.invalid/a")
        git(self.d, "remote", "add", "origin", "https://exemple.invalid/b")
        self.assertEqual(gmd.distant_par_defaut(self.d), "origin")

    def test_le_seul_distant(self):
        git(self.d, "remote", "add", "amont", "https://exemple.invalid/a")
        self.assertEqual(gmd.distant_par_defaut(self.d), "amont")

    def test_rien_ne_tranche(self):
        self.assertIsNone(gmd.distant_par_defaut(self.d))
        git(self.d, "remote", "add", "a", "https://exemple.invalid/a")
        git(self.d, "remote", "add", "b", "https://exemple.invalid/b")
        self.assertIsNone(gmd.distant_par_defaut(self.d))


class TestAddonsAddons(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.racine = self.tmp.name
        self.base = gmd.dossier_addons_addons(self.racine, "18.0")

    def test_absent_ou_sans_git(self):
        self.assertEqual(gmd.depots_addons_addons(self.racine, "18.0"), [])
        os.makedirs(os.path.join(self.base, "un_module"))
        self.assertEqual(gmd.depots_addons_addons(self.racine, "18.0"), [])

    def test_le_dossier_et_ses_sous_depots(self):
        depot(self.base)
        depot(os.path.join(self.base, "prive"))
        os.makedirs(os.path.join(self.base, "simple_dossier"))
        self.assertEqual(
            gmd.depots_addons_addons(self.racine, "18.0"),
            [self.base, os.path.join(self.base, "prive")],
        )


class TestDepotsDuChoix(unittest.TestCase):
    def test_seuls_les_clones_changes_ou_apparus(self):
        def ligne(chemin, statut, gauche=None, droite=None):
            return {
                "path": chemin,
                "status": statut,
                "old": "1" * 40 if gauche else None,
                "new": "2" * 40,
                "left": {"remote": gauche, "branch": "18.0"} if gauche else {},
                "right": (
                    {"remote": droite, "branch": "18.0_dev"} if droite else {}
                ),
            }

        rapport = {
            "rows": [
                ligne("a", git_freeze_diff.STATUS_CHANGED, "OCA", "OCA"),
                ligne("b", git_freeze_diff.STATUS_SAME, "OCA", "OCA"),
                ligne("c", git_freeze_diff.STATUS_NEW, None, "ERPLibre"),
                ligne("d", git_freeze_diff.STATUS_NOT_CLONED, "OCA"),
                ligne("e", git_freeze_diff.STATUS_CHANGED, "OCA", "OCA"),
            ]
        }
        with (
            mock.patch.object(git_freeze_diff, "build", return_value=rapport),
            mock.patch.object(
                git_freeze_diff,
                "is_clone",
                side_effect=lambda c: not c.endswith("/e"),
            ),
        ):
            depots = gmd.depots_du_choix("/r", "HEAD", "clones")
        self.assertEqual([x["path"] for x in depots], ["a", "c"])
        self.assertEqual(
            depots[0],
            {
                "path": "a",
                "remote": "OCA",
                "branch": "18.0_dev",
                "old": "1" * 40,
                "new": "2" * 40,
            },
        )
        self.assertEqual(depots[1]["remote"], "ERPLibre")
        self.assertIsNone(depots[1]["old"])


if __name__ == "__main__":
    unittest.main()
