#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""script/git/freeze_resolution.py sur de vrais dépôts jetables.

Un dépôt nu tient lieu de remote, à une URL de fichier ; le clone est rangé
sous une racine factice, au chemin qu'un manifeste lui donnerait. Aucun
réseau.
"""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from script.git import freeze_resolution as fr

CHEMIN = "odoo18.0/addons/R_test"
ENV_GIT = {
    **os.environ,
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "test@example.invalid",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "test@example.invalid",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
}


def git(cwd, *args):
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        env=ENV_GIT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


class Banc(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        self.nu = base / "remote.git"
        git(base, "init", "-q", "--bare", "-b", "18.0", str(self.nu))
        travail = base / "travail"
        git(base, "init", "-q", "-b", "18.0", str(travail))
        self.travail = travail
        self.c1 = self.commit("un")
        self.c2 = self.commit("deux")
        git(travail, "push", "-q", str(self.nu), "18.0")
        self.racine = base / "racine"
        self.clone = self.racine / CHEMIN
        self.clone.parent.mkdir(parents=True)
        git(base, "clone", "-q", str(self.nu), str(self.clone))
        self.url = str(self.nu)

    def commit(self, nom, cwd=None):
        cwd = cwd or self.travail
        (Path(cwd) / f"{nom}.txt").write_text(nom)
        git(cwd, "add", f"{nom}.txt")
        git(cwd, "commit", "-q", "-m", nom)
        return git(cwd, "rev-parse", "HEAD")

    def depot(self, gel, alignement, **extra):
        d = {
            "path": CHEMIN,
            "name": "R/test",
            "url": self.url,
            "head": git(self.clone, "rev-parse", "HEAD"),
            "branch": None,
            "manifest_branch": "18.0",
            "freeze_revision": gel,
            "freeze": {"alignment": alignement},
        }
        d.update(extra)
        return d

    def head(self):
        return git(self.clone, "rev-parse", "HEAD")


class TestClasser(unittest.TestCase):
    def test_classes(self):
        def d(chemin, alignement):
            return {"path": chemin, "freeze": {"alignment": alignement}}

        depots = [
            d("a", "en_retard"),
            d("b", "introuvable"),
            d("c", "en_avance"),
            d("d", "decale"),
            d("e", "conforme"),
            d("f", "en_retard"),
            {"path": "g", "freeze": None},
        ]
        classes = fr.classer(depots, lambda depot: depot["path"] == "f")
        chemins = {k: [x["path"] for x in v] for k, v in classes.items()}
        self.assertEqual(chemins[fr.REMETTRE], ["a", "b"])
        self.assertEqual(chemins[fr.MAJ_GEL], ["c"])
        self.assertEqual(chemins[fr.MANUELS], ["d"])
        self.assertEqual(chemins[fr.SALES], ["f"])


class TestRemettre(Banc):
    def test_en_retard_detache_sur_le_gel(self):
        git(self.clone, "checkout", "-q", "--detach", self.c1)
        ok, _ = fr.remettre_au_gel(
            self.racine, self.depot(self.c2, "en_retard")
        )
        self.assertTrue(ok)
        self.assertEqual(self.head(), self.c2)

    def test_commit_absent_rapatrie_depuis_l_url_du_manifeste(self):
        # Le remote du clone ne connaît pas le commit : seule l'URL du
        # manifeste le porte, comme pour un projet passé à un autre fork.
        c3 = self.commit("trois")
        git(self.travail, "push", "-q", self.url, "18.0")
        git(self.clone, "remote", "set-url", "origin", "/nulle/part")
        ok, message = fr.remettre_au_gel(
            self.racine, self.depot(c3, "introuvable")
        )
        self.assertTrue(ok, message)
        self.assertEqual(self.head(), c3)

    def test_chaque_commande_est_notee_depuis_la_racine(self):
        git(self.clone, "checkout", "-q", "--detach", self.c1)
        notees = []
        fr.remettre_au_gel(
            self.racine,
            self.depot(self.c2, "en_retard"),
            noter=notees.append,
        )
        self.assertEqual(notees[0], f"git -C {CHEMIN} status --porcelain")
        self.assertEqual(
            notees[-1], f"git -C {CHEMIN} checkout --quiet --detach {self.c2}"
        )

    def test_clone_modifie_jamais_touche(self):
        git(self.clone, "checkout", "-q", "--detach", self.c1)
        (self.clone / "un.txt").write_text("modifié")
        ok, message = fr.remettre_au_gel(
            self.racine, self.depot(self.c2, "en_retard")
        )
        self.assertFalse(ok)
        self.assertEqual(message, "modified files")
        self.assertEqual(self.head(), self.c1)

    def test_une_branche_locale_reste_ou_elle_etait(self):
        git(self.clone, "checkout", "-q", "-b", "travail", self.c1)
        fr.remettre_au_gel(self.racine, self.depot(self.c2, "en_retard"))
        self.assertEqual(git(self.clone, "rev-parse", "travail"), self.c1)
        self.assertEqual(self.head(), self.c2)


class TestPublication(Banc):
    def test_pointe_publiee(self):
        publie, detail = fr.publication(
            self.racine, self.depot(self.c1, "en_avance")
        )
        self.assertTrue(publie)
        self.assertIn("18.0", detail)

    def test_ancetre_de_la_branche_du_manifeste(self):
        git(self.clone, "checkout", "-q", "--detach", self.c1)
        publie, _ = fr.publication(self.racine, self.depot(None, "en_avance"))
        self.assertTrue(publie)

    def test_commit_local_sur_une_branche_a_pousser(self):
        git(self.clone, "checkout", "-q", "-b", "travail")
        self.commit("local", cwd=self.clone)
        publie, detail = fr.publication(
            self.racine, self.depot(self.c2, "en_avance", branch="travail")
        )
        self.assertFalse(publie)
        self.assertIn(f"push {self.url} travail", detail)

    def test_commit_local_detache(self):
        git(self.clone, "checkout", "-q", "--detach")
        self.commit("local", cwd=self.clone)
        publie, detail = fr.publication(
            self.racine, self.depot(self.c2, "en_avance")
        )
        self.assertFalse(publie)
        self.assertEqual(detail, "detached HEAD")

    def test_url_injoignable(self):
        publie, _ = fr.publication(
            self.racine, self.depot(self.c2, "en_avance", url="/nulle/part")
        )
        self.assertIsNone(publie)


class TestMettreAJourGel(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.racine = Path(tmp.name)
        (self.racine / "manifest").mkdir()
        self.ancien, self.neuf, self.autre = "a" * 40, "b" * 40, "c" * 40
        self.fichier = self.racine / "manifest" / "git_manifest_odoo18.0.xml"
        self.fichier.write_text(
            "<manifest>\n"
            "  <!-- un commentaire gardé -->\n"
            f'  <project name="R/test" path="{CHEMIN}" revision="18.0"'
            f' freeze-revision="{self.ancien}"'
            f' fork-upstream-freeze-revision="{self.autre}"/>\n'
            '  <project name="R/autre" path="odoo18.0/addons/R_autre"'
            f' revision="18.0" freeze-revision="{self.ancien}"/>\n'
            "</manifest>\n"
        )
        self.depot = {
            "path": CHEMIN,
            "name": "R/test",
            "head": self.neuf,
            "freeze_revision": self.ancien,
        }

    def test_seul_le_projet_vise_change(self):
        changes, sans_base = fr.mettre_a_jour_gel(self.racine, [self.depot])
        texte = self.fichier.read_text()
        self.assertEqual(
            changes,
            {"manifest/git_manifest_odoo18.0.xml": [f"R/test+{CHEMIN}"]},
        )
        self.assertIn(f'freeze-revision="{self.neuf}"', texte)
        # L'autre projet garde son gel, le commentaire reste.
        self.assertEqual(texte.count(f'freeze-revision="{self.ancien}"'), 1)
        self.assertIn("un commentaire gardé", texte)
        # La base amont ne vaut que pour l'ancien gel : retirée, et dite.
        self.assertNotIn("fork-upstream-freeze-revision", texte)
        self.assertEqual(sans_base, [f"R/test+{CHEMIN}"])

    def test_apercu_sans_ecrire(self):
        avant = self.fichier.read_text()
        changes, _ = fr.mettre_a_jour_gel(
            self.racine, [self.depot], ecrire=False
        )
        self.assertTrue(changes)
        self.assertEqual(self.fichier.read_text(), avant)

    def test_un_gel_qui_a_deja_change_n_est_pas_ecrase(self):
        self.depot["freeze_revision"] = "d" * 40
        changes, _ = fr.mettre_a_jour_gel(self.racine, [self.depot])
        self.assertEqual(changes, {})


if __name__ == "__main__":
    unittest.main()
