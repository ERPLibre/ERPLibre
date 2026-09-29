#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les modules de neutralisation qu'installe update_prod_to_dev.sh.

disable_auto_backup ne s'installe que sur une base où auto_backup est
installé : ailleurs il tirerait auto_backup avec lui, ou échouerait sur le
modèle db.backup absent. Le script tourne pour de vrai, avec un faux psql
et de faux scripts d'installation qui notent la liste reçue.
"""

import os
import shutil
import subprocess
import tempfile
import unittest

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(RACINE, "script", "addons", "update_prod_to_dev.sh")


class TestLaListe(unittest.TestCase):
    def lancer(self, installe, present):
        racine = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, racine)
        addons = os.path.join(racine, "script", "addons")
        os.makedirs(addons)
        shutil.copy(SCRIPT, addons)
        trace = os.path.join(racine, "trace")
        faux = os.path.join(racine, "bin")
        os.makedirs(faux)
        corps = {
            os.path.join(faux, "psql"): f"echo '{'1' if installe else ''}'",
            os.path.join(addons, "check_addons_exist.py"): (
                f"exit {0 if present else 1}"
            ),
            os.path.join(addons, "install_addons_dev.sh"): (
                f'echo "install $2" >> "{trace}"'
            ),
            os.path.join(addons, "uninstall_addons.sh"): (
                f'echo "uninstall $2" >> "{trace}"'
            ),
        }
        for chemin, code in corps.items():
            with open(chemin, "w") as handle:
                handle.write("#!/bin/bash\n" + code + "\n")
            os.chmod(chemin, 0o755)
        done = subprocess.run(
            ["bash", "script/addons/update_prod_to_dev.sh", "copie"],
            cwd=racine,
            env={"PATH": faux + ":/usr/bin:/bin"},
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, done.returncode, done.stdout + done.stderr)
        with open(trace) as handle:
            return handle.read().splitlines(), done.stdout

    def test_auto_backup_installe_et_present(self):
        lignes, _ = self.lancer(installe=True, present=True)
        self.assertIn("disable_auto_backup", lignes[0])
        self.assertIn("disable_auto_backup", lignes[1])

    def test_auto_backup_absent_de_la_base(self):
        lignes, sortie = self.lancer(installe=False, present=True)
        self.assertNotIn("disable_auto_backup", lignes[0])
        self.assertIn("user_test", lignes[0])
        self.assertIn("pas installe", sortie)

    def test_auto_backup_sans_code_dans_cette_version(self):
        lignes, sortie = self.lancer(installe=True, present=False)
        self.assertNotIn("disable_auto_backup", lignes[0])
        self.assertIn("absent de cette version", sortie)


if __name__ == "__main__":
    unittest.main()
