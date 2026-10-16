#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les réglages du service Stream Deck, vus de TODO.

TODO lit et réécrit le même fichier que l'installateur, le point d'entrée
du service et l'outil de passation : ces tests gardent les mêmes règles des
deux côtés, et comparent l'écriture de Python à celle de l'installateur sur
les mêmes entrées.
"""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

from script.todo import erplibre_home_service as service  # noqa: E402

INSTALLEUR = RACINE / "script/install/install_erplibre_home.sh"
BIBLIOTHEQUE = RACINE / "script/install/erplibre_home_settings.sh"


class LesChemins(unittest.TestCase):
    def test_under_dot_config_by_default(self):
        env = {"HOME": "/exemple/maison"}
        self.assertEqual(
            "/exemple/maison/.config/erplibre-home/streamdeck.conf",
            service.settings_path(env),
        )
        self.assertEqual(
            "/exemple/maison/.config/systemd/user/"
            "erplibre-home-streamdeck.service",
            service.unit_path(env),
        )

    def test_xdg_config_home_wins_and_empty_means_unset(self):
        env = {"HOME": "/exemple/maison", "XDG_CONFIG_HOME": "/exemple/cfg"}
        self.assertEqual(
            "/exemple/cfg/erplibre-home/streamdeck.conf",
            service.settings_path(env),
        )
        env["XDG_CONFIG_HOME"] = ""
        self.assertTrue(
            service.settings_path(env).startswith("/exemple/maison/.config/")
        )


class LaLecture(unittest.TestCase):
    def test_a_missing_file_gives_the_defaults(self):
        self.assertEqual(
            {"DECK_PROGRAM": "tiler", "RESTART_AFTER_GAME": "yes"},
            service.read_settings("/exemple/absent.conf"),
        )

    def test_the_last_line_wins_and_comments_are_skipped(self):
        with tempfile.TemporaryDirectory() as dossier:
            chemin = Path(dossier, "streamdeck.conf")
            chemin.write_text(
                "# DECK_PROGRAM=none\nDECK_PROGRAM=tiler\n"
                "sans egal\nDECK_PROGRAM=controller\n",
                encoding="utf-8",
            )
            reglages = service.read_settings(str(chemin))
        self.assertEqual("controller", reglages["DECK_PROGRAM"])
        self.assertEqual("yes", reglages["RESTART_AFTER_GAME"])

    def test_python_and_the_shell_library_read_the_same_value(self):
        """read_settings et deck_setting de la bibliothèque shell rendent
        la même valeur, y compris sur un « \\r » et sans retour final."""
        contenus = (
            "DECK_PROGRAM=none\n",
            "DECK_PROGRAM=a\nDECK_PROGRAM=controller",
            "# DECK_PROGRAM=none\nDECK_PROGRAM=\n",
            "DECK_PROGRAM=none\rRESTART_AFTER_GAME=no\n",
            "sans egal\nRESTART_AFTER_GAME=no\n",
        )
        for contenu in contenus:
            with self.subTest(contenu=contenu):
                with tempfile.TemporaryDirectory() as dossier:
                    chemin = Path(
                        dossier, ".config/erplibre-home/streamdeck.conf"
                    )
                    chemin.parent.mkdir(parents=True)
                    chemin.write_bytes(contenu.encode("utf-8"))
                    env = {
                        k: v
                        for k, v in os.environ.items()
                        if k != "XDG_CONFIG_HOME"
                    }
                    env.update({"HOME": dossier, "BIB": str(BIBLIOTHEQUE)})
                    lu = {}
                    for cle, defaut in service.DEFAULTS.items():
                        fini = subprocess.run(
                            [
                                "bash",
                                "-c",
                                '. "$BIB"; deck_setting %s %s' % (cle, defaut),
                            ],
                            capture_output=True,
                            env=env,
                            timeout=30,
                        )
                        self.assertEqual(0, fini.returncode, fini.stderr)
                        lu[cle] = fini.stdout.decode().rstrip("\n")
                    self.assertEqual(
                        lu,
                        service.read_settings(str(chemin)),
                    )


class LEcriture(unittest.TestCase):
    def test_a_key_is_replaced_in_place_and_others_stay(self):
        self.assertEqual(
            "# note\nDECK_PROGRAM=none\nEXEMPLE=1\nRESTART_AFTER_GAME=no\n",
            service.settings_text(
                "# note\nDECK_PROGRAM=tiler\nEXEMPLE=1\n",
                {"DECK_PROGRAM": "none", "RESTART_AFTER_GAME": "no"},
            ),
        )

    def test_write_creates_then_leaves_an_unchanged_file_alone(self):
        with tempfile.TemporaryDirectory() as dossier:
            chemin = Path(dossier, "erplibre-home", "streamdeck.conf")
            self.assertTrue(
                service.write_settings(str(chemin), {"DECK_PROGRAM": "none"})
            )
            self.assertEqual("DECK_PROGRAM=none\n", chemin.read_text())
            avant = chemin.stat().st_mtime_ns
            self.assertFalse(
                service.write_settings(str(chemin), {"DECK_PROGRAM": "none"})
            )
            self.assertEqual(avant, chemin.stat().st_mtime_ns)

    def test_python_and_the_installer_write_the_same_text(self):
        """settings_text, write_settings et settings_content de
        l'installateur, sur les mêmes entrées, rendent le même texte. Le
        shell ne coupe les lignes que sur « \\n » : un « \\r », un
        « \\x0b », un « \\x1c » ou un « \\u2028 » reste dans sa ligne,
        des deux côtés."""
        entrees = (
            "",
            "DECK_PROGRAM=none\n",
            "# note\nEXEMPLE=1\nRESTART_AFTER_GAME=yes\nDECK_PROGRAM=tiler",
            "DECK_PROGRAM=none\r\nEXEMPLE=1\r\n",
            "DECK_PROGRAM=none\rRESTART_AFTER_GAME=yes\n",
            "EXEMPLE=a\x0bDECK_PROGRAM=none\n",
            "EXEMPLE=a\x1cRESTART_AFTER_GAME=yes\x1d\x1e\x85\n",
            "EXEMPLE=a\u2028DECK_PROGRAM=none\u2029\n",
            "\n\nEXEMPLE=1\n\n",
        )
        maj = {"DECK_PROGRAM": "controller", "RESTART_AFTER_GAME": "no"}
        for entree in entrees:
            with self.subTest(entree=entree):
                with tempfile.TemporaryDirectory() as dossier:
                    chemin = Path(dossier, "streamdeck.conf")
                    copie = Path(dossier, "copie.conf")
                    if entree:
                        chemin.write_bytes(entree.encode("utf-8"))
                        copie.write_bytes(entree.encode("utf-8"))
                    service.write_settings(str(copie), maj)
                    ecrit = copie.read_bytes().decode("utf-8")
                    env = {
                        k: v
                        for k, v in os.environ.items()
                        if k != "XDG_CONFIG_HOME"
                    }
                    env.update(
                        {
                            "HOME": dossier,
                            "INSTALLEUR": str(INSTALLEUR),
                            "FICHIER": str(chemin),
                        }
                    )
                    fini = subprocess.run(
                        [
                            "bash",
                            "-c",
                            'ERPLIBRE_HOME_SOURCE_ONLY=1 . "$INSTALLEUR"\n'
                            'settings_content "$FICHIER"'
                            " DECK_PROGRAM=controller RESTART_AFTER_GAME=no\n",
                        ],
                        capture_output=True,
                        env=env,
                        timeout=30,
                    )
                self.assertEqual(0, fini.returncode, fini.stderr)
                attendu = fini.stdout.decode("utf-8")
                self.assertEqual(attendu, service.settings_text(entree, maj))
                self.assertEqual(attendu, ecrit)


class LaCommande(unittest.TestCase):
    def test_code_and_stdout(self):
        self.assertEqual(
            (3, "sortie\n"),
            service.run_command(["sh", "-c", "echo sortie; exit 3"]),
        )

    def test_a_missing_command_gives_none(self):
        self.assertEqual(
            (None, ""), service.run_command(["/exemple/commande-absente"])
        )

    def test_a_timeout_gives_none(self):
        self.assertEqual(
            (None, ""), service.run_command(["sleep", "5"], timeout=0.2)
        )


if __name__ == "__main__":
    unittest.main()
