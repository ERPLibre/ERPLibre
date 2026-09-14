#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Le menu des versions lit-il les clés que le fichier des versions écrit ?

`get_odoo_version()` rend les entrées de `conf/supported_version_erplibre.json`
TELLES QUELLES, plus une clé synthétisée. Le menu les interroge par
`version_info.get("...")`, et `dict.get` sur une clé absente rend None sans
rien dire : une étiquette qui ne s'affiche jamais, et aucun message.

C'est arrivé — `get("Default")` avec une majuscule contre `"default"` dans le
JSON, à deux endroits : l'étiquette « - Default » ne paraissait ni au choix de
version, ni au choix d'environnement, et la version par défaut passait donc
pour une version ordinaire.

Le test apparie les deux côtés plutôt que de vérifier ce seul cas : toute clé
que le menu lit doit exister dans le fichier, quelle que soit celle qu'on
ajoutera demain.
"""

import json
import re
import sys
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

TODO_PY = RACINE / "script" / "todo" / "todo.py"
VERSIONS = RACINE / "conf" / "supported_version_erplibre.json"

# Ce que `get_odoo_version` ajoute aux entrées du fichier.
SYNTHETISEES = {"erplibre_version"}


def cles_du_fichier():
    with VERSIONS.open(encoding="utf-8") as fh:
        data = json.load(fh)
    cles = set(SYNTHETISEES)
    for entree in data.values():
        cles |= set(entree)
    return cles


def cles_lues_par_le_menu():
    src = TODO_PY.read_text(encoding="utf-8")
    return set(re.findall(r'version_info\.get\(\s*["\']([^"\']+)["\']', src))


class TestClesDuMenuDesVersions(unittest.TestCase):
    def test_le_menu_ne_lit_que_des_cles_qui_existent(self):
        lues = cles_lues_par_le_menu()
        self.assertTrue(
            lues, "aucune lecture trouvée : le test ne mesure rien"
        )
        inconnues = sorted(lues - cles_du_fichier())
        self.assertEqual(
            inconnues,
            [],
            "le menu interroge des clés que le fichier des versions n'écrit "
            f"pas : {inconnues} — dict.get rend None sans rien dire, donc "
            "l'étiquette ne paraît jamais",
        )

    def test_la_casse_compte(self):
        """La panne d'origine tenait à une seule majuscule."""
        self.assertNotIn(
            "Default",
            cles_lues_par_le_menu(),
            "« Default » est relu avec une majuscule, alors que le fichier "
            "écrit « default »",
        )

    def test_une_seule_version_par_defaut(self):
        with VERSIONS.open(encoding="utf-8") as fh:
            data = json.load(fh)
        defauts = [k for k, v in data.items() if v.get("default")]
        self.assertEqual(
            len(defauts),
            1,
            f"{len(defauts)} versions marquées par défaut : {defauts}",
        )

    def test_letiquette_par_defaut_est_atteignable(self):
        """La clé lue et la valeur du fichier doivent se rencontrer : c'est ce
        que la panne empêchait."""
        from script.todo.version_manager import get_odoo_version

        versions, _installees, _actuelle = get_odoo_version()
        marquees = [v for v in versions if v.get("default")]
        self.assertEqual(
            len(marquees),
            1,
            "aucune entrée rendue par get_odoo_version ne porte « default »",
        )


if __name__ == "__main__":
    unittest.main()
