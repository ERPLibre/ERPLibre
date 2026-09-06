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

from script.todo.qemu_cache_menu import depots_des_manifestes  # noqa: E402


def faux_depot(manifestes):
    """Un dépôt de manifestes en dur, pour ne pas dépendre des vrais."""
    d = tempfile.mkdtemp()
    (Path(d) / "manifest").mkdir()
    for nom, contenu in manifestes.items():
        (Path(d) / "manifest" / nom).write_text(contenu, encoding="utf-8")
    return d


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
