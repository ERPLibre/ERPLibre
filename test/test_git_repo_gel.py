#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Le gel des versions, et les deux lectures qu'un seul fichier permet.

Un fichier de gel porte le COMMIT dans « revision » et la BRANCHE dans
« upstream ». Épingler et suivre sont donc deux PROJECTIONS du même
fichier, et non deux fichiers à tenir alignés. Ce que ces tests vérifient
est que les deux projections partent bien de la même source et n'inventent
rien pour un projet qu'elle ne mentionne pas.
"""

import json
import os
import tempfile
import unittest
from unittest.mock import patch

from script.git import git_merge_repo_manifest as fusion
from script.version import erplibre_state

GEL = """<?xml version="1.0" encoding="UTF-8" ?>
<manifest>
  <project name="a.git" path="odooX/addons/A_a" remote="R"
           revision="1111111111111111111111111111111111111111"
           upstream="X_dev" dest-branch="X_dev"/>
  <project name="b.git" path="odooX/addons/A_b" remote="R"
           revision="2222222222222222222222222222222222222222"
           upstream="X"/>
  <project name="c.git" path="odooX/addons/A_c" remote="R"
           revision="3333333333333333333333333333333333333333"/>
</manifest>
"""


class TestLireGel(unittest.TestCase):
    def setUp(self):
        self.dossier = tempfile.mkdtemp()
        self.gel = os.path.join(self.dossier, "gel.xml")
        with open(self.gel, "w") as fh:
            fh.write(GEL)

    def test_cle_par_nom_et_chemin(self):
        lu = fusion.lire_gel(self.gel)
        self.assertIn("a.git+odooX/addons/A_a", lu)
        self.assertEqual(len(lu), 3)

    def test_le_commit_et_la_branche_sont_lus(self):
        lu = fusion.lire_gel(self.gel)
        revision, upstream = lu["a.git+odooX/addons/A_a"]
        self.assertTrue(revision.startswith("1111"))
        self.assertEqual(upstream, "X_dev")

    def test_fichier_absent_rend_vide(self):
        self.assertEqual(fusion.lire_gel("/nulle/part.xml"), {})
        self.assertEqual(fusion.lire_gel(None), {})

    def test_fichier_illisible_rend_vide_sans_lever(self):
        """Un gel abîmé ne doit pas empêcher la fusion : sans lui, le plan
        de travail suit simplement ses branches."""
        casse = os.path.join(self.dossier, "casse.xml")
        with open(casse, "w") as fh:
            fh.write("<manifest><project")
        self.assertEqual(fusion.lire_gel(casse), {})


class TestProjeterGel(unittest.TestCase):
    def setUp(self):
        self.dossier = tempfile.mkdtemp()
        self.gel = os.path.join(self.dossier, "gel.xml")
        with open(self.gel, "w") as fh:
            fh.write(GEL)

    def projets(self):
        return {
            "a.git+odooX/addons/A_a": {"@revision": "X_dev"},
            "b.git+odooX/addons/A_b": {"@revision": "X"},
            "neuf.git+odooX/addons/A_neuf": {"@revision": "X"},
        }

    def test_mode_fige_pose_le_commit(self):
        projets = self.projets()
        touches = fusion.projeter_gel(projets, "fige", self.gel)
        self.assertEqual(touches, 2)
        self.assertTrue(
            projets["a.git+odooX/addons/A_a"]["@revision"].startswith("1111")
        )

    def test_mode_dev_pose_la_branche(self):
        """La MÊME source donne la branche : un seul fichier, deux
        lectures, aucun second manifeste à tenir aligné."""
        projets = self.projets()
        fusion.projeter_gel(projets, "dev", self.gel)
        self.assertEqual(
            projets["a.git+odooX/addons/A_a"]["@revision"], "X_dev"
        )

    def test_un_projet_absent_du_gel_n_est_pas_touche(self):
        """Il est arrivé APRÈS le gel ; lui inventer une révision le
        sortirait de son manifeste."""
        projets = self.projets()
        fusion.projeter_gel(projets, "fige", self.gel)
        self.assertEqual(
            projets["neuf.git+odooX/addons/A_neuf"]["@revision"], "X"
        )

    def test_un_gel_sans_upstream_ne_touche_rien_en_mode_dev(self):
        projets = {"c.git+odooX/addons/A_c": {"@revision": "X"}}
        self.assertEqual(fusion.projeter_gel(projets, "dev", self.gel), 0)
        self.assertEqual(projets["c.git+odooX/addons/A_c"]["@revision"], "X")

    def test_sans_gel_rien_ne_bouge(self):
        projets = self.projets()
        self.assertEqual(fusion.projeter_gel(projets, "fige", None), 0)
        self.assertEqual(
            projets["a.git+odooX/addons/A_a"]["@revision"], "X_dev"
        )


class TestEtatDuMode(unittest.TestCase):
    def setUp(self):
        self.dossier = tempfile.mkdtemp()
        self.fichier = os.path.join(self.dossier, ".erplibre-state.json")
        self.patch = patch.object(erplibre_state, "STATE_FILE", self.fichier)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()

    def test_defaut_sans_fichier(self):
        """Un plan de travail qui précède ce réglage doit continuer à
        suivre ses branches plutôt que d'échouer."""
        self.assertEqual(
            erplibre_state.get_git_repo(),
            {"mode": erplibre_state.MODE_DEV, "gel": None},
        )

    def test_defaut_sur_un_etat_ancien(self):
        with open(self.fichier, "w") as fh:
            json.dump({"current_odoo_version": "X"}, fh)
        self.assertEqual(
            erplibre_state.get_git_repo()["mode"], erplibre_state.MODE_DEV
        )

    def test_aller_retour(self):
        erplibre_state.set_git_repo_mode(erplibre_state.MODE_FIGE)
        self.assertEqual(
            erplibre_state.get_git_repo()["mode"], erplibre_state.MODE_FIGE
        )
        erplibre_state.set_git_repo_mode(erplibre_state.MODE_DEV)
        self.assertEqual(
            erplibre_state.get_git_repo()["mode"], erplibre_state.MODE_DEV
        )

    def test_le_gel_survit_au_changement_de_mode(self):
        erplibre_state.set_git_repo_gel("manifest/snapshot/x.xml")
        erplibre_state.set_git_repo_mode(erplibre_state.MODE_FIGE)
        self.assertEqual(
            erplibre_state.get_git_repo()["gel"], "manifest/snapshot/x.xml"
        )

    def test_un_mode_inconnu_est_refuse(self):
        """La fusion lit cette valeur pour décider de la révision de chaque
        projet : une faute de frappe y déplacerait tout le plan de travail
        sans rien dire."""
        with self.assertRaises(ValueError):
            erplibre_state.set_git_repo_mode("fgie")

    def test_une_valeur_abimee_retombe_sur_dev(self):
        with open(self.fichier, "w") as fh:
            json.dump({"git_repo": {"mode": "n'importe quoi"}}, fh)
        self.assertEqual(
            erplibre_state.get_git_repo()["mode"], erplibre_state.MODE_DEV
        )

    def test_les_autres_reglages_ne_sont_pas_perdus(self):
        erplibre_state.set_version_switched("X")
        erplibre_state.set_git_repo_mode(erplibre_state.MODE_FIGE)
        self.assertEqual(erplibre_state.get_current_version(), "X")


if __name__ == "__main__":
    unittest.main()
