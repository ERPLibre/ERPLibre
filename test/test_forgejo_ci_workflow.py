#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le workflow de CI de la forge, .forgejo/workflows/unit_test.yml, lu.

Propriétés gardées :
- le déclencheur est « pull_request » SEUL : un « push » lancerait la CI à
  chaque fast-forward du minuteur des miroirs ;
- le job vise l'étiquette du runner que pose la forge, sans « uses: » (le
  mode hôte n'a ni Node.js ni accès aux dépôts d'actions) ;
- les valeurs de l'évènement et le jeton n'arrivent au shell que par
  l'environnement, jamais interpolés dans un « run: » ni passés à git par
  « -c » ;
- chaque bloc « run: » est un shell valide.
"""

import os
import pathlib
import re
import subprocess
import unittest

import yaml

from script.forgejo import forge_vm

RACINE = pathlib.Path(__file__).resolve().parent.parent
WORKFLOW = RACINE / ".forgejo/workflows/unit_test.yml"


class TestLeWorkflow(unittest.TestCase):
    def setUp(self):
        self.texte = WORKFLOW.read_text()
        self.doc = yaml.safe_load(self.texte)
        self.job = self.doc["jobs"]["unit"]
        self.etapes = self.job["steps"]

    def test_pull_request_is_the_only_trigger(self):
        # YAML 1.1 lit la clé « on » comme le booléen True.
        declencheurs = self.doc.get("on", self.doc.get(True))
        self.assertEqual(set(declencheurs), {"pull_request"})

    def test_it_targets_the_forge_runner_without_actions(self):
        self.assertEqual(self.job["runs-on"], forge_vm.LABEL_CI)
        self.assertTrue(self.job["timeout-minutes"])
        for etape in self.etapes:
            self.assertNotIn("uses", etape, etape.get("name"))

    def test_the_venv_then_the_unit_tests(self):
        commandes = [e.get("run", "") for e in self.etapes]
        for script in (
            "./script/forgejo/ci_venv.sh",
            "./script/test/run_unit_test.sh",
        ):
            self.assertTrue(any(script in c for c in commandes), script)
            self.assertTrue(os.access(RACINE / script, os.X_OK), script)

    def test_event_values_reach_the_shell_through_env_only(self):
        for etape in self.etapes:
            self.assertNotIn("${{", etape.get("run", ""), etape.get("name"))
        secrets = [
            (nom, valeur)
            for etape in self.etapes
            for nom, valeur in (etape.get("env") or {}).items()
            if "secrets." in str(valeur)
        ]
        self.assertEqual(len(secrets), 1)
        self.assertEqual(self.texte.count("secrets."), 1)
        self.assertNotIn("secrets.", str(self.job.get("env")))
        self.assertIsNone(re.search(r"-c\s+http\.extraHeader", self.texte))

    def test_every_run_block_is_valid_bash(self):
        for etape in self.etapes:
            res = subprocess.run(
                ["bash", "-n"],
                input=etape.get("run", ""),
                capture_output=True,
                text=True,
            )
            self.assertEqual(res.returncode, 0, res.stderr)

    def test_every_email_is_invented(self):
        courriels = re.findall(r"[\w.+-]+@[\w.-]+", self.texte)
        self.assertTrue(courriels)
        for courriel in courriels:
            self.assertTrue(courriel.endswith(".invalid"), courriel)


if __name__ == "__main__":
    unittest.main()
