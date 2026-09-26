#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""« make install_os » sur Fedora garde-t-il les bases existantes ?

Le script initialise le cluster PostgreSQL quand il n'existe pas encore, et
efface pour cela /var/lib/pgsql/data. Ce répertoire appartient à postgres, en
mode 700 : un test lancé par l'utilisateur n'y voit rien, conclut à un
cluster absent à CHAQUE exécution, et l'effacement emportait toutes les bases
de la machine. Le test d'existence doit donc passer par sudo.
"""

import re
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
SCRIPT = (RACINE / "script/install/install_fedora_dependency.sh").read_text(
    encoding="utf-8"
)


class TestLeClusterExistantEstGarde(unittest.TestCase):
    def test_l_existence_est_testee_par_sudo(self):
        self.assertIn("sudo test -f /var/lib/pgsql/data/PG_VERSION", SCRIPT)

    def test_aucun_test_sans_sudo_sur_le_repertoire_de_postgres(self):
        sans_sudo = re.findall(r"\[ !? ?-[fde] /var/lib/pgsql", SCRIPT)
        self.assertEqual([], sans_sudo)

    def test_l_effacement_est_garde_par_ce_test(self):
        garde = SCRIPT.index("sudo test -f /var/lib/pgsql/data/PG_VERSION")
        efface = SCRIPT.index("sudo rm -rf /var/lib/pgsql/data")
        fin = SCRIPT.index("\nfi", garde)
        self.assertLess(garde, efface)
        self.assertLess(efface, fin)


if __name__ == "__main__":
    unittest.main()
