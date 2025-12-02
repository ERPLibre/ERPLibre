#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""run_init_cmd de docker/entrypoint.sh, sans Docker : la fonction est
extraite du script et lancée seule dans un bash, sous « set -e » comme dans
l'entrypoint, suivie d'un écho qui prouve que la suite (Odoo) est atteinte."""

import os
import re
import subprocess
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "docker", "entrypoint.sh")


def fonction():
    with open(SCRIPT, encoding="utf-8") as fh:
        texte = fh.read()
    trouve = re.search(r"^run_init_cmd\(\) \{\n.*?^\}\n", texte, re.S | re.M)
    if not trouve:
        raise AssertionError("run_init_cmd absent de docker/entrypoint.sh")
    return trouve.group(0)


class TestRunInitCmd(unittest.TestCase):
    def lancer(self, init_cmd=None):
        env = {k: v for k, v in os.environ.items() if k != "INIT_CMD"}
        if init_cmd is not None:
            env["INIT_CMD"] = init_cmd
        with tempfile.TemporaryDirectory() as d:
            env["HOME"] = d
            return subprocess.run(
                [
                    "bash",
                    "-c",
                    f"set -e\n{fonction()}run_init_cmd\necho SUITE",
                ],
                env=env,
                cwd=d,
                capture_output=True,
                text=True,
                timeout=30,
            )

    def test_absente_ou_vide_ne_fait_rien(self):
        for valeur in (None, ""):
            r = self.lancer(valeur)
            self.assertEqual(r.returncode, 0)
            self.assertEqual(r.stdout, "SUITE\n")

    def test_la_commande_tourne_puis_odoo_suit(self):
        r = self.lancer("echo un && echo deux")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, "INIT_CMD: running\nun\ndeux\nSUITE\n")

    def test_bash_comprend_source(self):
        r = self.lancer('printf "X=7\\n" > f.sh; source f.sh; echo "$X"')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("7\n", r.stdout)

    def test_un_echec_arrete_avant_odoo(self):
        r = self.lancer("echo avant; exit 3")
        self.assertEqual(r.returncode, 1)
        self.assertNotIn("SUITE", r.stdout)
        self.assertIn("INIT_CMD failed", r.stderr)

    def test_le_journal_ne_montre_pas_la_commande(self):
        r = self.lancer("true --mot-de-passe-invente-9f3k")
        self.assertEqual(r.returncode, 0)
        self.assertNotIn("9f3k", r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
