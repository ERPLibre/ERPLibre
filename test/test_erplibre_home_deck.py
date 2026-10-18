#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le point d'entrée du service Stream Deck et ses réglages.

erplibre_home_deck.sh tourne ici dans une copie du dépôt dont le chemin
porte une espace, sous un HOME temporaire : le venv est un faux python qui
écrit ses arguments, et l'arbre sysfs un faux, désigné par
ERPLIBRE_HOME_SYSFS. Rien ne touche ni au vrai venv ni au vrai /sys.

Ce que ces tests gardent :

- --check rend 0 seulement avec un programme, le venv et un deck du vendeur
  0fd9 ; chaque manque rend 1 et le dit sur une ligne ;
- sans option, le script remplace son processus par le python du venv sur
  le programme de DECK_PROGRAM, tiler par défaut ;
- une valeur inconnue sort en 1 et nomme le fichier ; « none » ne lance
  rien ;
- les réglages se lisent sans être sourcés, la dernière ligne d'une clé
  l'emporte, et $XDG_CONFIG_HOME prime sur ~/.config.
"""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
INSTALL = RACINE / "script/install"
SCRIPTS = ("erplibre_home_deck.sh", "erplibre_home_settings.sh")


class Copie(unittest.TestCase):
    """Une copie du dépôt réduite aux deux scripts, un HOME et un /sys
    jetables."""

    def setUp(self):
        dossier = tempfile.TemporaryDirectory()
        self.addCleanup(dossier.cleanup)
        self.tmp = Path(dossier.name)
        self.depot = self.tmp / "copie du depot"
        (self.depot / "script/install").mkdir(parents=True)
        for nom in SCRIPTS:
            shutil.copy2(INSTALL / nom, self.depot / "script/install" / nom)
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.sysfs = self.tmp / "sys"
        (self.sysfs / "bus/usb/devices").mkdir(parents=True)
        self.reglages = self.home / ".config/erplibre-home/streamdeck.conf"

    def venv(self):
        """Pose le faux python du venv : il écrit son répertoire courant
        puis chacun de ses arguments, un par ligne."""
        python = self.depot / ".venv.streamdeck/bin/python"
        python.parent.mkdir(parents=True)
        python.write_text(
            '#!/bin/sh\npwd\nfor a in "$@"; do echo "$a"; done\n',
            encoding="utf-8",
        )
        python.chmod(0o755)

    def usb(self, nom, vendeur):
        """Un périphérique USB dans le faux sysfs."""
        appareil = self.sysfs / "bus/usb/devices" / nom
        appareil.mkdir()
        (appareil / "idVendor").write_text(vendeur + "\n", encoding="utf-8")

    def regler(self, texte):
        self.reglages.parent.mkdir(parents=True, exist_ok=True)
        self.reglages.write_text(texte, encoding="utf-8")

    def lancer(self, *options, env=None):
        environ = {
            k: v for k, v in os.environ.items() if k != "XDG_CONFIG_HOME"
        }
        environ["HOME"] = str(self.home)
        environ["ERPLIBRE_HOME_SYSFS"] = str(self.sysfs)
        environ.update(env or {})
        return subprocess.run(
            [
                str(self.depot / "script/install/erplibre_home_deck.sh"),
                *options,
            ],
            capture_output=True,
            text=True,
            env=environ,
            cwd="/",
            timeout=30,
        )


class LeCheck(Copie):
    def test_everything_present_exits_zero(self):
        self.venv()
        self.usb("1-1", "1d6b")
        self.usb("3-2", "0fd9")
        fini = self.lancer("--check")
        self.assertEqual(0, fini.returncode, fini.stderr)
        self.assertEqual("", fini.stdout)

    def test_games_off_never_gates_the_deck_entry_point(self):
        """GAMES ne touche pas le programme du deck : --check rend la même
        chose avec GAMES=off qu'avec GAMES=on."""
        self.venv()
        self.usb("1-1", "1d6b")
        self.usb("3-2", "0fd9")
        rendu = {}
        for valeur in ("on", "off"):
            self.regler(f"GAMES={valeur}\n")
            fini = self.lancer("--check")
            rendu[valeur] = (fini.returncode, fini.stdout)
        self.assertEqual(0, rendu["on"][0])
        self.assertEqual(rendu["on"], rendu["off"])

    def test_no_deck_exits_one_and_says_so(self):
        self.venv()
        self.usb("1-1", "1d6b")
        fini = self.lancer("--check")
        self.assertEqual(1, fini.returncode)
        self.assertIn("no Stream Deck plugged in", fini.stderr)
        self.assertEqual(1, len(fini.stderr.strip().splitlines()))

    def test_no_venv_exits_one_and_names_the_install(self):
        self.usb("3-2", "0fd9")
        fini = self.lancer("--check")
        self.assertEqual(1, fini.returncode)
        self.assertIn("make erplibre_home_streamdeck_install", fini.stderr)

    def test_program_none_exits_one(self):
        self.venv()
        self.usb("3-2", "0fd9")
        self.regler("DECK_PROGRAM=none\n")
        fini = self.lancer("--check")
        self.assertEqual(1, fini.returncode)
        self.assertIn("DECK_PROGRAM=none", fini.stderr)

    def test_an_unknown_program_exits_one_naming_the_file(self):
        self.venv()
        self.usb("3-2", "0fd9")
        self.regler("DECK_PROGRAM=exemple\n")
        for options in (("--check",), ()):
            with self.subTest(options=options):
                fini = self.lancer(*options)
                self.assertEqual(1, fini.returncode)
                self.assertIn("DECK_PROGRAM=exemple", fini.stderr)
                self.assertIn(str(self.reglages), fini.stderr)
                self.assertEqual("", fini.stdout)

    def test_an_unknown_option_exits_one(self):
        fini = self.lancer("--exemple")
        self.assertEqual(1, fini.returncode)
        self.assertIn("--exemple", fini.stderr)


class LeLancement(Copie):
    def test_the_tiler_runs_by_default_under_the_venv(self):
        self.venv()
        fini = self.lancer()
        self.assertEqual(0, fini.returncode, fini.stderr)
        self.assertEqual(
            [
                str(self.depot),
                str(self.depot / "script/stream_deck/erplibre_streamdeck"),
            ],
            fini.stdout.splitlines(),
        )

    def test_each_program_maps_to_its_script(self):
        self.venv()
        attendus = {
            "tiler": "script/stream_deck/erplibre_streamdeck",
            "controller": "script/stream_deck/erplibre_controller.py",
        }
        for programme, script in attendus.items():
            with self.subTest(programme=programme):
                self.regler(f"DECK_PROGRAM={programme}\n")
                fini = self.lancer()
                self.assertEqual(0, fini.returncode, fini.stderr)
                self.assertEqual(
                    str(self.depot / script), fini.stdout.splitlines()[-1]
                )

    def test_the_program_replaces_the_script(self):
        """exec : le PID du programme est celui du script, et aucun bash ne
        reste pour tenir le verrou du deck."""
        python = self.depot / ".venv.streamdeck/bin/python"
        python.parent.mkdir(parents=True)
        python.write_text("#!/bin/sh\necho $$\n", encoding="utf-8")
        python.chmod(0o755)
        environ = {
            k: v for k, v in os.environ.items() if k != "XDG_CONFIG_HOME"
        }
        environ["HOME"] = str(self.home)
        script = self.depot / "script/install/erplibre_home_deck.sh"
        proc = subprocess.Popen(
            [str(script)],
            stdout=subprocess.PIPE,
            text=True,
            env=environ,
        )
        sortie, _ = proc.communicate(timeout=30)
        self.assertEqual(str(proc.pid), sortie.strip())

    def test_none_runs_nothing(self):
        self.venv()
        self.regler("DECK_PROGRAM=none\n")
        fini = self.lancer()
        self.assertEqual(0, fini.returncode, fini.stderr)
        self.assertNotIn("erplibre_streamdeck", fini.stdout)
        self.assertIn("nothing to run", fini.stdout)

    def test_without_the_venv_it_exits_one(self):
        fini = self.lancer()
        self.assertEqual(1, fini.returncode)
        self.assertIn("make erplibre_home_streamdeck_install", fini.stderr)


class LesReglages(Copie):
    def lire(self, cle, defaut, env=None):
        environ = {
            k: v for k, v in os.environ.items() if k != "XDG_CONFIG_HOME"
        }
        environ.update(
            {
                "HOME": str(self.home),
                "BIBLIO": str(INSTALL / "erplibre_home_settings.sh"),
                "CLE": cle,
                "DEFAUT": defaut,
            }
        )
        environ.update(env or {})
        fini = subprocess.run(
            ["bash", "-c", '. "$BIBLIO"; deck_setting "$CLE" "$DEFAUT"'],
            capture_output=True,
            text=True,
            env=environ,
            timeout=30,
        )
        self.assertEqual(0, fini.returncode, fini.stderr)
        return fini.stdout.rstrip("\n")

    def test_a_missing_file_gives_the_default(self):
        self.assertEqual("tiler", self.lire("DECK_PROGRAM", "tiler"))

    def test_the_last_line_of_a_key_wins_and_comments_are_skipped(self):
        self.regler(
            "# DECK_PROGRAM=none\n"
            "DECK_PROGRAM=tiler\n"
            "RESTART_AFTER_GAME=no\n"
            "DECK_PROGRAM=controller"
        )
        self.assertEqual("controller", self.lire("DECK_PROGRAM", "tiler"))
        self.assertEqual("no", self.lire("RESTART_AFTER_GAME", "yes"))

    def test_a_key_prefix_is_not_the_key(self):
        self.regler("DECK_PROGRAM_OLD=none\n")
        self.assertEqual("tiler", self.lire("DECK_PROGRAM", "tiler"))

    def test_the_file_is_never_sourced(self):
        temoin = self.tmp / "execute"
        self.regler(f"DECK_PROGRAM=$(touch {temoin})\n")
        self.assertEqual(
            f"$(touch {temoin})", self.lire("DECK_PROGRAM", "tiler")
        )
        self.assertFalse(temoin.exists())

    def test_xdg_config_home_wins_over_dot_config(self):
        ailleurs = self.tmp / "config ailleurs"
        (ailleurs / "erplibre-home").mkdir(parents=True)
        (ailleurs / "erplibre-home/streamdeck.conf").write_text(
            "DECK_PROGRAM=controller\n", encoding="utf-8"
        )
        self.regler("DECK_PROGRAM=none\n")
        self.assertEqual(
            "controller",
            self.lire(
                "DECK_PROGRAM", "tiler", {"XDG_CONFIG_HOME": str(ailleurs)}
            ),
        )


class LesScripts(unittest.TestCase):
    def test_the_entry_point_is_executable_valid_shell(self):
        script = INSTALL / "erplibre_home_deck.sh"
        self.assertTrue(os.access(script, os.X_OK))
        for nom in SCRIPTS:
            with self.subTest(nom=nom):
                fini = subprocess.run(
                    ["bash", "-n", str(INSTALL / nom)],
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(0, fini.returncode, fini.stderr)


class LesProgrammesExistent(unittest.TestCase):
    """deck_program_path nomme, pour chaque programme, un fichier du
    dépôt : un renommage oublié dans la bibliothèque arrête le service."""

    def test_each_program_names_a_file_that_exists(self):
        bib = RACINE / "script/install/erplibre_home_settings.sh"
        for programme in ("tiler", "controller"):
            with self.subTest(programme=programme):
                fini = subprocess.run(
                    [
                        "bash",
                        "-c",
                        '. "$0"; deck_program_path "$1"',
                        str(bib),
                        programme,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                self.assertEqual(0, fini.returncode, fini.stderr)
                chemin = RACINE / fini.stdout.strip()
                self.assertTrue(
                    chemin.is_file() or (chemin / "__main__.py").is_file(),
                    chemin,
                )
        fini = subprocess.run(
            ["bash", "-c", ". \"$0\"; deck_program_path tiler", str(bib)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(
            "script/stream_deck/erplibre_streamdeck", fini.stdout.strip()
        )


if __name__ == "__main__":
    unittest.main()
