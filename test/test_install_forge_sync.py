#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""L'installateur du minuteur des miroirs, lu sans être lancé : syntaxe,
durcissement de l'unité, jeton jamais affiché, jamais de force."""

import re
import shutil
import subprocess
import unittest
from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "script"
    / "forgejo"
    / "install_forge_sync.sh"
)


class TestInstallForgeSync(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.texte = SCRIPT.read_text(encoding="utf-8")

    @unittest.skipUnless(shutil.which("bash"), "bash absent")
    def test_la_syntaxe(self):
        fini = subprocess.run(
            ["bash", "-n", str(SCRIPT)], capture_output=True, text=True
        )
        self.assertEqual(fini.returncode, 0, fini.stderr)

    def test_l_unite_et_le_jeton(self):
        for attendu in (
            "set -euo pipefail",
            "LoadCredential=token:/etc/erplibre-forge-sync/token",
            "ConditionPathExists=/etc/erplibre-forge-sync/token",
            "ConditionPathExists=/etc/erplibre-forge-sync/config.json",
            "ProtectSystem=strict",
            "NoNewPrivileges=true",
            "Type=oneshot",
            "Persistent=true",
            "--raw",
            "^[0-9a-f]{40}$",
            "pipefail",
            "umask 077",
        ):
            with self.subTest(attendu=attendu):
                self.assertIn(attendu, self.texte)

    def test_le_jeton_n_est_jamais_affiche(self):
        for ligne in self.texte.splitlines():
            if re.search(r"\b(echo|say)\b", ligne):
                with self.subTest(ligne=ligne):
                    self.assertIsNone(re.search(r"\$\{?(tok|out)\b", ligne))

    def test_forgejo_s_ordonne_sans_se_demarrer(self):
        """Wants= relancerait une forge arrêtée exprès à chaque passe ;
        After= ordonne seul."""
        self.assertIn("After=forgejo.service", self.texte)
        self.assertNotIn("Wants=forgejo.service", self.texte)

    @unittest.skipUnless(shutil.which("bash"), "bash absent")
    def test_une_racine_cachee_par_protecthome_est_refusee(self):
        """ProtectHome=true cache /home, /root et /run/user au service :
        une racine des dépôts rangée là est refusée avec un message."""
        self.assertIn("ProtectHome=true", self.texte)
        bloc = re.search(
            r'^case "\$ROOT" in\n    /home\|.*?^esac$',
            self.texte,
            re.M | re.S,
        )
        self.assertIsNotNone(bloc)
        for racine, refusee in (
            ("/home/git/depots", True),
            ("/home", True),
            ("/root/depots", True),
            ("/run/user/1000/depots", True),
            ("/var/lib/forgejo/data/forgejo-repositories", False),
            ("/homes/depots", False),
            ("/srv/home/depots", False),
        ):
            with self.subTest(racine=racine):
                # Le bloc n'appelle que des commandes internes de bash :
                # aucun PATH, aucune commande externe atteinte.
                fini = subprocess.run(
                    [
                        shutil.which("bash"),
                        "-c",
                        'die() { echo "$*" >&2; exit 1; }\n' + bloc.group(0),
                    ],
                    env={"ROOT": racine},
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(fini.returncode != 0, refusee)
                if refusee:
                    self.assertIn("ProtectHome", fini.stderr)

    def test_jamais_de_force(self):
        self.assertNotIn("--force", self.texte)

    def test_aucun_env_var(self):
        self.assertNotIn("env_var.sh", self.texte.split("set -euo")[1])


if __name__ == "__main__":
    unittest.main()
