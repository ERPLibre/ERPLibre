#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La table des ERP dont Google Repo récupère la source (erp_sources).

Propriétés gardées :
- chaque entrée de la vraie table est cohérente avec le dépôt : sa liste
  CSV cite son manifeste, et ce manifeste déclare un projet dont le chemin
  est le checkout ;
- l'entrée Dolibarr garde les chemins que la fusion lisait en dur ;
- la fusion ne connaît aucun ERP d'avance : pour « dolibarr » comme pour
  « acme », ERP inventé, la table seule donne le drapeau --with_<erp>, son
  aide, le fragment ajouté par le drapeau ou d'office par le checkout ;
- plusieurs ERP entrent dans la fusion dans l'ordre de la table.

Les tests de la fusion lancent `default_input_paths` dans une racine
jetable : elle lit ses listes par chemins relatifs au dossier courant.
"""

import csv
import io
import os
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

from script.git import erp_sources  # noqa: E402
from script.git import git_merge_repo_manifest as fusion  # noqa: E402

# « acme » et « zeta » sont des ERP inventés.
ERPS = ("dolibarr", "acme")


def source(erp):
    return erp_sources.Source(
        label=erp.capitalize(),
        checkout=os.path.join(erp, erp),
        conf=os.path.join("conf", f"git_manifest_{erp}.csv"),
        manifest=os.path.join("manifest", f"git_manifest_{erp}.xml"),
    )


def table(*erps):
    return mock.patch.dict(
        erp_sources.ERP_SOURCES, {e: source(e) for e in erps}, clear=True
    )


def filepaths(chemin):
    with open(chemin, newline="") as fh:
        return [row["filepath"] for row in csv.DictReader(fh)]


class TestVraieTable(unittest.TestCase):
    def test_l_entree_dolibarr_garde_ses_chemins(self):
        self.assertEqual(
            erp_sources.ERP_SOURCES["dolibarr"],
            erp_sources.Source(
                "Dolibarr",
                "dolibarr/dolibarr",
                "conf/git_manifest_dolibarr.csv",
                "manifest/git_manifest_dolibarr.xml",
            ),
        )

    def test_chaque_liste_cite_son_manifeste(self):
        for erp, src in erp_sources.ERP_SOURCES.items():
            with self.subTest(erp=erp):
                self.assertIn(src.manifest, filepaths(RACINE / src.conf))

    def test_chaque_manifeste_declare_son_checkout(self):
        for erp, src in erp_sources.ERP_SOURCES.items():
            with self.subTest(erp=erp):
                racine = ET.parse(RACINE / src.manifest).getroot()
                chemins = [p.get("path") for p in racine.iter("project")]
                self.assertIn(src.checkout, chemins)


class Banc(unittest.TestCase):
    """Une racine jetable, dossier courant le temps du test."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.racine = Path(tmp.name)
        cwd = os.getcwd()
        os.chdir(self.racine)
        self.addCleanup(os.chdir, cwd)

    def lister(self, erp):
        src = source(erp)
        chemin = self.racine / src.conf
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_text(f'"filepath"\n{src.manifest}\n')
        return src.manifest


class TestTableGenerique(Banc):
    def test_drapeau_et_checkouts(self):
        for erp in ERPS:
            with self.subTest(erp=erp), table(erp):
                self.assertEqual(erp_sources.flag(erp), f"with_{erp}")
                self.assertEqual(
                    erp_sources.checkouts(), (os.path.join(erp, erp),)
                )

    def test_present_suit_le_checkout(self):
        for erp in ERPS:
            with self.subTest(erp=erp), table(erp):
                self.assertEqual(erp_sources.present(), [])
                self.assertEqual(erp_sources.present(str(self.racine)), [])
                (self.racine / erp / erp).mkdir(parents=True)
                self.assertEqual(erp_sources.present(), [erp])
                self.assertEqual(erp_sources.present(str(self.racine)), [erp])


class TestFusionGenerique(Banc):
    def test_le_drapeau_et_son_aide_viennent_de_la_table(self):
        for erp in ERPS:
            with self.subTest(erp=erp), table(erp):
                self.assertTrue(
                    getattr(
                        fusion.get_config([f"--with_{erp}"]), f"with_{erp}"
                    )
                )
                self.assertFalse(getattr(fusion.get_config([]), f"with_{erp}"))
                aide = io.StringIO()
                with redirect_stdout(aide), self.assertRaises(SystemExit):
                    fusion.get_config(["--help"])
                texte = " ".join(aide.getvalue().split())
                self.assertIn(
                    f"--with_{erp} Add the pinned {erp.capitalize()} project"
                    " manifest",
                    texte,
                )

    def test_le_drapeau_ajoute_le_fragment(self):
        for erp in ERPS:
            with self.subTest(erp=erp), table(erp):
                attendu = self.lister(erp)
                self.assertNotIn(
                    attendu, fusion.default_input_paths(with_new_manifest=True)
                )
                self.assertIn(
                    attendu,
                    fusion.default_input_paths(
                        with_erps=[erp], with_new_manifest=True
                    ),
                )

    def test_le_checkout_ajoute_le_fragment_d_office(self):
        for erp in ERPS:
            with self.subTest(erp=erp), table(erp):
                attendu = self.lister(erp)
                self.assertNotIn(attendu, fusion.default_input_paths())
                (self.racine / erp / erp).mkdir(parents=True)
                self.assertIn(attendu, fusion.default_input_paths())
                # with_new_manifest ignore le checkout.
                self.assertNotIn(
                    attendu, fusion.default_input_paths(with_new_manifest=True)
                )

    def test_l_ordre_est_celui_de_la_table(self):
        for ordre in (("acme", "zeta"), ("zeta", "acme")):
            with self.subTest(ordre=ordre), table(*ordre):
                attendus = [self.lister(erp) for erp in ordre]
                for erp in ordre:
                    (self.racine / erp / erp).mkdir(
                        parents=True, exist_ok=True
                    )
                chemins = fusion.default_input_paths()
                self.assertEqual(
                    [c for c in chemins if c in attendus], attendus
                )


if __name__ == "__main__":
    unittest.main()
