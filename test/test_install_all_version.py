#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Sur quelle version « make install_odoo_all_version » laisse le checkout.

Chaque install_odoo_N récrit .odoo-version : la version active est celle de
la DERNIÈRE étape. Le service erplibre, relancé après l'installation, sert
cette version, et la restauration d'une base de référence cherche une image
odoo<version>_* qui n'existe que pour certaines versions. La cible doit donc
finir sur la version par défaut du catalogue, et non sur la dernière de sa
liste d'installations.
"""

import json
import re
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
MAKEFILE = RACINE / "conf/make.installation.Makefile"
VERSIONS = RACINE / "conf/supported_version_erplibre.json"


def _etapes(cible):
    """Les cibles que la recette de « cible » enchaîne par script/make.sh.

    :return: liste des noms de cibles, dans l'ordre de la recette
    """
    src = MAKEFILE.read_text("utf-8")
    recette = re.search(
        rf"^{re.escape(cible)}:[^\n]*\n((?:\t[^\n]*\n)+)", src, re.M
    )
    if recette is None:
        return []
    return re.findall(r"\./script/make\.sh (\S+)", recette.group(1))


def _version_par_defaut():
    """La version Odoo de l'entrée « default » du catalogue, ex. « 18 »."""
    with VERSIONS.open(encoding="utf-8") as fh:
        catalogue = json.load(fh)
    defauts = [
        e["odoo_version"] for e in catalogue.values() if e.get("default")
    ]
    if len(defauts) != 1:
        raise AssertionError(f"une seule version par défaut : {defauts}")
    return defauts[0].split(".")[0]


class FinDeLInstallationDeToutesLesVersions(unittest.TestCase):
    def test_it_ends_on_the_catalogue_default(self):
        etapes = _etapes("install_odoo_all_version")
        self.assertTrue(etapes, "recette introuvable : le test ne mesure rien")
        defaut = _version_par_defaut()
        self.assertIn(
            etapes[-1], (f"install_odoo_{defaut}", f"switch_odoo_{defaut}")
        )

    def test_the_last_step_is_a_target_that_exists(self):
        derniere = _etapes("install_odoo_all_version")[-1]
        src = MAKEFILE.read_text("utf-8")
        self.assertIn(f".PHONY: {derniere}\n{derniere}:", src)

    def test_the_default_is_installed_before_the_switch(self):
        """La version par défaut doit avoir été installée avant d'y basculer."""
        installees = {
            e.removeprefix("install_odoo_")
            for e in _etapes("install_odoo_all_version")
            if e.startswith("install_odoo_")
        }
        self.assertIn(_version_par_defaut(), installees)


if __name__ == "__main__":
    unittest.main()
