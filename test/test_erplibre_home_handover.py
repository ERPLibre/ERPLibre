#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La passation du Stream Deck entre le service et un jeu.

erplibre_home_handover.sh tourne sous un HOME temporaire, un faux systemctl
en tête du PATH : il note chaque appel dans un journal et garde l'état de
l'unité dans un fichier. Le « jeu » est une commande sh qui note son tour
dans le même journal, si bien que l'ordre arrêt, jeu, relance se lit d'un
coup.

Ce que ces tests gardent :

- une unité active est arrêtée avant le jeu et relancée après ;
- une unité arrêtée le reste, et RESTART_AFTER_GAME=no la laisse arrêtée ;
- le code du jeu est celui du script ;
- sans fichier d'unité, systemctl n'est jamais appelé ;
- un jeu interrompu (SIGINT, SIGTERM) rend quand même le deck au service ;
- le réglage se lit après la partie.
"""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
PASSATION = RACINE / "script/install/erplibre_home_handover.sh"
UNITE = "erplibre-home-streamdeck.service"

SYSTEMCTL = """#!/bin/sh
echo "systemctl $*" >>"$JOURNAL"
case "$2" in
    is-active) [ "$(cat "$ETAT")" = active ] ;;
    stop) [ -z "${ECHEC_STOP:-}" ] && echo inactive >"$ETAT" ;;
    start) echo active >"$ETAT" ;;
esac
"""


class Passation(unittest.TestCase):
    def setUp(self):
        dossier = tempfile.TemporaryDirectory()
        self.addCleanup(dossier.cleanup)
        self.tmp = Path(dossier.name)
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.journal = self.tmp / "journal"
        self.journal.touch()
        self.etat = self.tmp / "etat"
        bin_ = self.tmp / "bin"
        bin_.mkdir()
        (bin_ / "systemctl").write_text(SYSTEMCTL, encoding="utf-8")
        (bin_ / "systemctl").chmod(0o755)
        self.path = "%s:%s" % (bin_, os.environ.get("PATH", ""))
        self.reglages = self.home / ".config/erplibre-home/streamdeck.conf"

    def unite(self, etat):
        """Pose le fichier d'unité et l'état que rend le faux systemctl."""
        fichier = self.home / ".config/systemd/user" / UNITE
        fichier.parent.mkdir(parents=True, exist_ok=True)
        fichier.write_text("[Unit]\n", encoding="utf-8")
        self.etat.write_text(etat + "\n", encoding="utf-8")

    def regler(self, texte):
        self.reglages.parent.mkdir(parents=True, exist_ok=True)
        self.reglages.write_text(texte, encoding="utf-8")

    def jouer(self, jeu='echo jeu >>"$JOURNAL"; exit 7', env=None):
        environ = {
            k: v for k, v in os.environ.items() if k != "XDG_CONFIG_HOME"
        }
        environ.update(
            {
                "HOME": str(self.home),
                "PATH": self.path,
                "JOURNAL": str(self.journal),
                "ETAT": str(self.etat),
                "REGLAGES": str(self.reglages),
            }
        )
        environ.update(env or {})
        fini = subprocess.run(
            [str(PASSATION), "sh", "-c", jeu],
            capture_output=True,
            text=True,
            env=environ,
            timeout=30,
        )
        return fini, self.journal.read_text(encoding="utf-8").splitlines()

    def test_an_active_unit_is_stopped_then_started_again(self):
        self.unite("active")
        fini, journal = self.jouer()
        self.assertEqual(7, fini.returncode, fini.stderr)
        self.assertEqual(
            [
                f"systemctl --user is-active --quiet {UNITE}",
                f"systemctl --user stop {UNITE}",
                "jeu",
                f"systemctl --user start {UNITE}",
            ],
            journal,
        )
        self.assertEqual("active", self.etat.read_text().strip())

    def test_a_stopped_unit_stays_stopped(self):
        self.unite("inactive")
        fini, journal = self.jouer()
        self.assertEqual(7, fini.returncode, fini.stderr)
        self.assertEqual(
            [f"systemctl --user is-active --quiet {UNITE}", "jeu"], journal
        )

    def test_restart_after_game_no_leaves_it_stopped(self):
        self.unite("active")
        self.regler("RESTART_AFTER_GAME=no\n")
        fini, journal = self.jouer()
        self.assertEqual(7, fini.returncode, fini.stderr)
        self.assertNotIn(f"systemctl --user start {UNITE}", journal)
        self.assertEqual("inactive", self.etat.read_text().strip())

    def test_the_setting_is_read_after_the_game(self):
        self.unite("active")
        fini, journal = self.jouer(
            'echo jeu >>"$JOURNAL"; mkdir -p "$(dirname "$REGLAGES")";'
            ' echo RESTART_AFTER_GAME=no >"$REGLAGES"'
        )
        self.assertEqual(0, fini.returncode, fini.stderr)
        self.assertNotIn(f"systemctl --user start {UNITE}", journal)

    def test_without_the_unit_only_the_command_runs(self):
        fini, journal = self.jouer()
        self.assertEqual(7, fini.returncode, fini.stderr)
        self.assertEqual(["jeu"], journal)

    def test_an_interrupted_game_still_gives_the_deck_back(self):
        """Le signal frappe le script et le jeu ensemble, comme un Ctrl-C
        au terminal : le jeu meurt du signal, le script relance le service
        puis sort avec le code du jeu, 128 + le numéro du signal."""
        for signal_, code in (("INT", 130), ("TERM", 143)):
            with self.subTest(signal=signal_):
                self.journal.write_text("", encoding="utf-8")
                self.unite("active")
                fini, journal = self.jouer(
                    f'echo jeu >>"$JOURNAL"; kill -{signal_} $PPID $$;'
                    " sleep 5"
                )
                self.assertEqual(code, fini.returncode, fini.stderr)
                self.assertEqual(
                    f"systemctl --user start {UNITE}", journal[-1]
                )

    def test_a_failed_stop_runs_the_game_and_restarts_nothing(self):
        self.unite("active")
        fini, journal = self.jouer(env={"ECHEC_STOP": "1"})
        self.assertEqual(7, fini.returncode)
        self.assertIn("could not stop", fini.stderr)
        self.assertIn("jeu", journal)
        self.assertNotIn(f"systemctl --user start {UNITE}", journal)

    def test_no_command_is_a_usage_error(self):
        fini = subprocess.run(
            [str(PASSATION)], capture_output=True, text=True, timeout=30
        )
        self.assertEqual(1, fini.returncode)
        self.assertIn("usage", fini.stderr)


class LeScript(unittest.TestCase):
    def test_it_is_executable_valid_shell(self):
        self.assertTrue(os.access(PASSATION, os.X_OK))
        fini = subprocess.run(
            ["bash", "-n", str(PASSATION)], capture_output=True, text=True
        )
        self.assertEqual(0, fini.returncode, fini.stderr)


if __name__ == "__main__":
    unittest.main()
