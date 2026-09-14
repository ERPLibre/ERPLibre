#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Les dépôts git que le miroir doit tenir, lus des manifestes du dépôt.

Le protocole git est une négociation : rien ne s'y cache, et c'est un MIROIR
qu'il faut tenir. À la demande, il se remplit au fil des requêtes — la première
machine paie chaque clonage. Pour un dépôt qui en tire trois cents, ce n'est
pas un coût supprimé mais déplacé, sur la machine qui attend.

La liste vient donc des manifestes, seule source qui dise ce que le dépôt clone
vraiment. Un manifeste Google Repo sépare la forge (« remote ») du projet
(« project ») : l'URL est la concaténation des deux, et un même projet figure
dans plusieurs manifestes, un par version d'Odoo.
"""

import sys
import tempfile
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

from script.todo.qemu_cache_menu import (  # noqa: E402
    depots_des_manifestes,
    manifeste_retenu,
)


def faux_depot(manifestes):
    """Un dépôt de manifestes en dur, pour ne pas dépendre des vrais."""
    d = tempfile.mkdtemp()
    (Path(d) / "manifest").mkdir()
    for nom, contenu in manifestes.items():
        (Path(d) / "manifest" / nom).write_text(contenu, encoding="utf-8")
    return d


def manifeste_de(projet):
    """Un manifeste minimal déclarant un seul projet."""
    return (
        "<manifest>"
        '<remote name="F" fetch="https://f.example/" />'
        f'<project name="{projet}.git" remote="F" />'
        "</manifest>"
    )


class TestLaBorneParVersion(unittest.TestCase):
    """Un déploiement n'installe qu'UNE version d'Odoo.

    Additionner les dépôts de toutes les versions — les dépréciées comprises
    — fait annoncer comme manquants des dépôts que personne ne clonera. Un
    avertissement qui crie pour rien cesse d'être lu, et c'est justement ce
    que le reste du pré-vol évite avec soin.

    Sans version, rien n'est soustrait : le remplissage des miroirs prend de
    l'avance pour toutes les versions à la fois, et lui retrancher un
    manifeste le ferait manquer plus tard, hors ligne, sans recours.
    """

    MANIFESTES = {
        "git_manifest_odoo18.0.xml": manifeste_de("dix-huit"),
        "git_manifest_odoo12.0.xml": manifeste_de("douze"),
        "git_manifest_erplibre.xml": manifeste_de("commun"),
        "default.staged.deprecated.xml": manifeste_de("deprecie"),
    }

    def test_une_version_retient_la_sienne_et_les_communs(self):
        urls = depots_des_manifestes(faux_depot(self.MANIFESTES), "18.0")
        self.assertIn("https://f.example/dix-huit.git", urls)
        self.assertIn("https://f.example/commun.git", urls)
        self.assertNotIn("https://f.example/douze.git", urls)

    def test_les_deprecies_sortent_des_quune_version_est_donnee(self):
        """Ils ne décrivent plus rien d'installable."""
        urls = depots_des_manifestes(faux_depot(self.MANIFESTES), "18.0")
        self.assertNotIn("https://f.example/deprecie.git", urls)

    def test_sans_version_rien_nest_soustrait(self):
        urls = depots_des_manifestes(faux_depot(self.MANIFESTES))
        self.assertEqual(len(urls), 4, urls)

    def test_la_regle_de_retenue(self):
        for nom, version, attendu in (
            ("git_manifest_odoo18.0.xml", "18.0", True),
            ("git_manifest_extra_odoo18.0.xml", "18.0", True),
            ("git_manifest_odoo12.0.xml", "18.0", False),
            # Sans numéro : vaut pour toutes les versions.
            ("git_manifest_erplibre_odoo.xml", "18.0", True),
            ("default.staged.deprecated.xml", "18.0", False),
            # Sans version demandée, tout passe — y compris le déprécié.
            ("default.staged.deprecated.xml", "", True),
            ("git_manifest_odoo12.0.xml", "", True),
        ):
            self.assertIs(
                manifeste_retenu(nom, version), attendu, f"{nom} / {version}"
            )


class TestExtraction(unittest.TestCase):
    def test_lurl_est_la_forge_plus_le_projet(self):
        d = faux_depot(
            {
                "a.xml": "<manifest>"
                '<remote name="F" fetch="https://forge.example/org/" />'
                '<project name="outil.git" remote="F" />'
                "</manifest>"
            }
        )
        self.assertEqual(
            depots_des_manifestes(d), ["https://forge.example/org/outil.git"]
        )

    def test_un_projet_dans_deux_manifestes_ne_compte_quune_fois(self):
        """Un même projet figure dans un manifeste par version d'Odoo : le
        cloner deux fois ne ferait que perdre du temps."""
        commun = (
            '<manifest><remote name="F" fetch="https://f.example/" />'
            '<project name="p.git" remote="F" /></manifest>'
        )
        d = faux_depot({"odoo17.xml": commun, "odoo18.xml": commun})
        self.assertEqual(depots_des_manifestes(d), ["https://f.example/p.git"])

    def test_les_barres_obliques_ne_se_doublent_pas(self):
        d = faux_depot(
            {
                "a.xml": "<manifest>"
                '<remote name="F" fetch="https://f.example/org/" />'
                '<project name="/p.git" remote="F" /></manifest>'
            }
        )
        self.assertEqual(
            depots_des_manifestes(d), ["https://f.example/org/p.git"]
        )

    def test_un_projet_sans_forge_connue_est_saute(self):
        """Sinon l'URL serait un nom de projet nu, que git ne sait pas
        cloner et dont l'échec ne se lirait qu'à l'exécution."""
        d = faux_depot(
            {
                "a.xml": "<manifest>"
                '<remote name="F" fetch="https://f.example/" />'
                '<project name="orphelin.git" remote="INCONNUE" />'
                '<project name="bon.git" remote="F" /></manifest>'
            }
        )
        self.assertEqual(
            depots_des_manifestes(d), ["https://f.example/bon.git"]
        )

    def test_un_manifeste_illisible_est_saute(self):
        """La liste sert à prendre de l'avance : en perdre une part vaut
        mieux que de ne rien prendre."""
        d = faux_depot(
            {
                "casse.xml": "<manifest><project",
                "bon.xml": "<manifest>"
                '<remote name="F" fetch="https://f.example/" />'
                '<project name="p.git" remote="F" /></manifest>',
            }
        )
        self.assertEqual(depots_des_manifestes(d), ["https://f.example/p.git"])

    def test_aucun_manifeste_rend_une_liste_vide(self):
        self.assertEqual(depots_des_manifestes(tempfile.mkdtemp()), [])


class TestLeRepliSurLaVersionDuDepot(unittest.TestCase):
    """Sans version donnée, le verdict prend celle que le checkout porte.

    C'est ce qu'un déploiement pose par défaut. Sans ce repli, la lecture
    redeviendrait celle de TOUS les manifestes, et l'avertissement se
    remettrait à nommer des dépôts qu'aucun déploiement ne clonera — ce qui
    apprend à ne plus le lire.
    """

    def test_le_verdict_est_borne_par_defaut(self):
        from script.todo.deploy_form_lib import _depots_declares

        tous = depots_des_manifestes(str(RACINE))
        bornes = _depots_declares()
        self.assertTrue(tous, "aucun manifeste lu")
        self.assertTrue(bornes, "la borne a tout supprimé")
        self.assertLess(
            len(bornes),
            len(tous),
            "la lecture par défaut n'est pas bornée à une version",
        )

    def test_la_version_lue_est_celle_du_fichier(self):
        """« .odoo-version » est la source, et non une constante figée :
        changer de version d'Odoo doit changer le verdict."""
        from script.todo.deploy_form_lib import _depots_declares

        version = (
            (RACINE / ".odoo-version").read_text(encoding="utf-8").strip()
        )
        self.assertEqual(
            sorted(_depots_declares()),
            sorted(depots_des_manifestes(str(RACINE), version)),
        )


class TestLesVraisManifestes(unittest.TestCase):
    """Le dépôt lui-même : la liste ne doit pas se vider en silence."""

    def test_le_depot_declare_bien_des_projets(self):
        depots = depots_des_manifestes(str(RACINE))
        self.assertGreater(
            len(depots), 100, "les manifestes ne déclarent presque rien"
        )

    def test_toutes_les_urls_sont_absolues(self):
        for u in depots_des_manifestes(str(RACINE)):
            self.assertTrue(
                u.startswith(("https://", "http://", "git@", "ssh://")),
                f"« {u} » n'est pas une URL que git sait cloner",
            )


if __name__ == "__main__":
    unittest.main()
