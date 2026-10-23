#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""La provenance des forks : ce qui est déclaré, et ce qui se déduit.

Aucun accès réseau. Le lecteur d'amont est injecté partout où l'état
dépend de ce que l'amont répond, pour que la suite unitaire reste
lançable en quelques secondes sur une machine hors ligne.
"""

import os
import tempfile
import unittest
import xml.etree.ElementTree as ET

from script.git import repo_upgrade
from script.git.git_tool import GitTool

VERSION = "18.0"


class TestUrlAmont(unittest.TestCase):
    def test_barre_finale_presente(self):
        self.assertEqual(
            repo_upgrade.url_amont("https://example.org/org/", "d.git"),
            "https://example.org/org/d.git",
        )

    def test_barre_finale_absente(self):
        """Un « fetch » sans barre finale ne doit pas coller deux segments.

        Un seul remote du dépôt est écrit sans elle ; l'oublier produit
        une URL qui ne résout nulle part.
        """
        self.assertEqual(
            repo_upgrade.url_amont("https://example.org/org", "d.git"),
            "https://example.org/org/d.git",
        )

    def test_jamais_de_double_barre(self):
        for fetch in ("https://example.org/org/", "https://example.org/org"):
            url = repo_upgrade.url_amont(fetch, "d.git")
            self.assertNotIn("//d.git", url)

    def test_vide_si_rien(self):
        self.assertEqual(repo_upgrade.url_amont("", "d.git"), "")
        self.assertEqual(repo_upgrade.url_amont("https://e.org/", ""), "")


class TestCle(unittest.TestCase):
    def test_nom_et_chemin(self):
        """Le nom SEUL confond un dépôt servi par plusieurs versions."""
        a = {"name": "web.git", "path": "odoo17.0/addons/OCA_web"}
        b = {"name": "web.git", "path": "odoo18.0/addons/OCA_web"}
        self.assertNotEqual(repo_upgrade.cle(a), repo_upgrade.cle(b))


class TestResoudreAmont(unittest.TestCase):
    REMOTES = {
        "Amont": "https://example.org/amont/",
        "Prop_origin_Amont": "https://example.org/prop/",
    }

    def test_non_fork_rend_none(self):
        projet = {"name": "d.git", "remote": "Amont"}
        self.assertIsNone(repo_upgrade.resoudre_amont(projet, self.REMOTES))

    def test_attribut_prioritaire(self):
        projet = {
            "name": "d.git",
            "remote": "Prop_origin_Amont",
            "fork-upstream-remote": "Amont",
            "fork-upstream": "18.0",
        }
        amont = repo_upgrade.resoudre_amont(projet, self.REMOTES)
        self.assertEqual(amont["source"], "declare")
        self.assertEqual(amont["branche"], "18.0")
        self.assertEqual(amont["url"], "https://example.org/amont/d.git")

    def test_convention_en_repli(self):
        projet = {"name": "d.git", "remote": "Prop_origin_Amont"}
        amont = repo_upgrade.resoudre_amont(projet, self.REMOTES)
        self.assertEqual(amont["source"], "convention")
        self.assertEqual(amont["remote"], "Amont")
        self.assertIsNone(amont["branche"])

    def test_nom_amont_different(self):
        """Un fork renommé porte un nom que l'amont n'a pas."""
        projet = {
            "name": "amont_d.git",
            "remote": "Prop_origin_Amont",
            "fork-upstream-remote": "Amont",
            "fork-upstream-name": "d.git",
            "fork-upstream": "18.0",
        }
        amont = repo_upgrade.resoudre_amont(projet, self.REMOTES)
        self.assertEqual(amont["url"], "https://example.org/amont/d.git")

    def test_remote_amont_non_declare(self):
        projet = {"name": "d.git", "remote": "Prop_origin_Absent"}
        amont = repo_upgrade.resoudre_amont(projet, self.REMOTES)
        self.assertFalse(amont["remote_declare"])

    def test_branche_absente_reste_none(self):
        """Un amont sans branche pour la version n'invente pas de branche."""
        projet = {
            "name": "d.git",
            "remote": "Prop_origin_Amont",
            "fork-upstream-remote": "Amont",
        }
        amont = repo_upgrade.resoudre_amont(projet, self.REMOTES)
        self.assertIsNone(amont["branche"])
        self.assertEqual(amont["source"], "declare")


MANIFESTE_A = """<?xml version="1.0" encoding="UTF-8" ?>
<manifest>
    <remote name="Prop_origin_Amont" fetch="https://example.org/prop/" />
    <project
        name="d.git"
        path="odooX/addons/Amont_d"
        remote="Prop_origin_Amont"
        fork-upstream-remote="Amont"
        fork-upstream="X"
        revision="X_dev"
    />
    <!--    <project name="mort.git" path="odooX/addons/mort"
             remote="Prop_origin_Amont" />-->
</manifest>
"""

MANIFESTE_DEV = """<?xml version="1.0" encoding="UTF-8" ?>
<manifest>
    <remote name="Amont" fetch="https://example.org/amont/" />
</manifest>
"""


class TestLireManifestes(unittest.TestCase):
    def setUp(self):
        self.dossier = tempfile.mkdtemp()
        with open(
            os.path.join(self.dossier, "git_manifest_odooX.xml"), "w"
        ) as fh:
            fh.write(MANIFESTE_A)
        with open(
            os.path.join(self.dossier, "git_manifest_odooX_dev.xml"), "w"
        ) as fh:
            fh.write(MANIFESTE_DEV)

    def test_fusionne_les_fichiers(self):
        """Le remote amont d'un fork peut vivre dans un AUTRE fichier.

        Une résolution fichier par fichier le déclarerait inconnu à tort.
        """
        remotes, projets = repo_upgrade.lire_manifestes("X", self.dossier)
        self.assertIn("Amont", remotes)
        self.assertIn("Prop_origin_Amont", remotes)
        self.assertEqual(len(projets), 1)

    def test_projet_en_commentaire_ignore(self):
        """Un <project> mis en commentaire n'est pas un projet vivant."""
        _remotes, projets = repo_upgrade.lire_manifestes("X", self.dossier)
        self.assertFalse(
            any("mort" in (p.get("path") or "") for p in projets.values())
        )

    def test_etat_declare_sans_reseau(self):
        lst = repo_upgrade.etat_forks("X", self.dossier, verifier=False)
        self.assertEqual([x["etat"] for x in lst], ["declare"])

    def test_etat_confirme_avec_lecteur_injecte(self):
        lst = repo_upgrade.etat_forks(
            "X", self.dossier, verifier=True, lecteur=lambda url: {"X"}
        )
        self.assertEqual(lst[0]["etat"], "confirme")

    def test_etat_branche_absente(self):
        lst = repo_upgrade.etat_forks(
            "X", self.dossier, verifier=True, lecteur=lambda url: {"autre"}
        )
        self.assertEqual(lst[0]["etat"], "branche_absente")

    def test_injoignable_distinct_de_vide(self):
        """None et l'ensemble vide ne disent pas la même chose.

        Les confondre ferait passer une coupure réseau pour un amont
        légitimement dépourvu de la branche.
        """
        injoignable = repo_upgrade.etat_forks(
            "X", self.dossier, verifier=True, lecteur=lambda url: None
        )
        vide = repo_upgrade.etat_forks(
            "X", self.dossier, verifier=True, lecteur=lambda url: set()
        )
        self.assertEqual(injoignable[0]["etat"], "injoignable")
        self.assertEqual(vide[0]["etat"], "branche_absente")


class TestManifestesDuDepot(unittest.TestCase):
    """La garde qui attrape la dérive : les manifestes réels du dépôt."""

    def setUp(self):
        self.remotes, self.projets = repo_upgrade.lire_manifestes(VERSION)
        self.forks = [
            p for p in self.projets.values() if repo_upgrade.est_fork(p)
        ]

    def test_des_forks_existent(self):
        self.assertGreater(len(self.forks), 0)

    def test_chaque_fork_declare_son_remote_amont(self):
        muets = [
            p.get("path")
            for p in self.forks
            if not p.get("fork-upstream-remote")
        ]
        self.assertEqual(muets, [], "forks sans amont déclaré")

    def test_chaque_remote_amont_est_declare(self):
        """Un « fork-upstream-remote » qui ne nomme aucun <remote> ne
        résout aucune URL, et la mise à niveau ignorerait le dépôt."""
        absents = [
            (p.get("path"), p["fork-upstream-remote"])
            for p in self.forks
            if p.get("fork-upstream-remote")
            and p["fork-upstream-remote"] not in self.remotes
        ]
        self.assertEqual(absents, [])

    def test_aucun_amont_devine(self):
        lst = repo_upgrade.etat_forks(VERSION, verifier=False)
        a_corriger = [
            (x["chemin"], x["etat"])
            for x in lst
            if x["etat"] in repo_upgrade.ETATS_A_CORRIGER
        ]
        self.assertEqual(a_corriger, [])

    def test_attributs_jamais_vides(self):
        for p in self.forks:
            for attr in (
                "fork-upstream-remote",
                "fork-upstream-name",
                "fork-upstream",
            ):
                if attr in p:
                    self.assertTrue(p[attr].strip(), f"{p.get('path')} {attr}")


class TestAllerRetourGenerateur(unittest.TestCase):
    """La provenance doit survivre à la régénération du manifeste local.

    Le générateur recopie une liste blanche d'attributs ; tout ce qui n'y
    figure pas disparaît en silence entre le manifeste source et celui
    que git-repo lit vraiment.
    """

    def test_les_trois_attributs_survivent(self):
        dossier = tempfile.mkdtemp()
        sortie = os.path.join(dossier, "sortie.xml")
        GitTool().generate_repo_manifest(
            output=sortie,
            remotes_config={
                "Amont": {
                    "@name": "Amont",
                    "@fetch": "https://example.org/amont/",
                }
            },
            projects_config={
                "d.git+odooX/addons/Amont_d": {
                    "@name": "amont_d.git",
                    "@path": "odooX/addons/Amont_d",
                    "@remote": "Prop_origin_Amont",
                    "@revision": "X_dev",
                    "@fork-upstream-remote": "Amont",
                    "@fork-upstream-name": "d.git",
                    "@fork-upstream": "X",
                }
            },
        )
        projet = ET.parse(sortie).getroot().find("project")
        self.assertEqual(projet.get("fork-upstream-remote"), "Amont")
        self.assertEqual(projet.get("fork-upstream-name"), "d.git")
        self.assertEqual(projet.get("fork-upstream"), "X")


if __name__ == "__main__":
    unittest.main()
