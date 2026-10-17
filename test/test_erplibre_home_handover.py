#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La passation du Stream Deck entre le service et un jeu.

erplibre_home_handover.sh tourne sous un HOME temporaire, un faux systemctl
en tête du PATH : il note chaque appel dans un journal et garde l'état de
l'unité dans un fichier. Le « jeu » est une commande sh qui note son tour
dans le même journal, si bien que l'ordre arrêt, jeu, relance se lit d'un
coup.

Le verrou du deck vit sous un XDG_RUNTIME_DIR temporaire : jamais celui du
compte qui lance les tests.

Ce que ces tests gardent :

- une unité active, ou qui attend de redémarrer, est arrêtée avant le jeu
  et relancée après, son compteur de démarrages remis à zéro ;
- le jeu tourne sous le verrou du deck, au nom de « game » ; un deck déjà
  pris ne lance pas le jeu ;
- une unité arrêtée le reste, et RESTART_AFTER_GAME=no la laisse arrêtée ;
- le code du jeu est celui du script ;
- sans fichier d'unité, systemctl n'est jamais appelé ;
- un jeu interrompu (SIGINT, SIGTERM au groupe) rend quand même le deck au
  service ; un SIGTERM au seul script laisse le jeu finir ;
- le réglage se lit après la partie.
"""

import importlib.util
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
PASSATION = RACINE / "script/install/erplibre_home_handover.sh"
UNITE = "erplibre-home-streamdeck.service"
DECK_DIR = RACINE / "script/stream_deck"

# Comme systemctl is-active : l'état sur la sortie, 0 pour « active » seul.
SYSTEMCTL = """#!/bin/sh
echo "systemctl $*" >>"$JOURNAL"
case "$2" in
    is-active) cat "$ETAT"; [ "$(cat "$ETAT")" = active ] ;;
    stop) [ -z "${ECHEC_STOP:-}" ] && echo inactive >"$ETAT" ;;
    start) echo active >"$ETAT" ;;
esac
"""

# Le jeu qui note le détenteur du verrou vu de l'intérieur.
VU_DU_JEU = (
    "import sys; sys.path.insert(0, sys.argv[1]); import deck_lock;"
    " print(deck_lock.holder()[1])"
)


def charger_verrou():
    spec = importlib.util.spec_from_file_location(
        "deck_lock", DECK_DIR / "deck_lock.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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
        self.run_dir = self.tmp / "run"
        self.run_dir.mkdir(mode=0o700)

    def unite(self, etat):
        """Pose le fichier d'unité et l'état que rend le faux systemctl."""
        fichier = self.home / ".config/systemd/user" / UNITE
        fichier.parent.mkdir(parents=True, exist_ok=True)
        fichier.write_text("[Unit]\n", encoding="utf-8")
        self.etat.write_text(etat + "\n", encoding="utf-8")

    def regler(self, texte):
        self.reglages.parent.mkdir(parents=True, exist_ok=True)
        self.reglages.write_text(texte, encoding="utf-8")

    def environ(self, env=None):
        environ = {
            k: v for k, v in os.environ.items() if k != "XDG_CONFIG_HOME"
        }
        environ.update(
            {
                "HOME": str(self.home),
                "PATH": self.path,
                "XDG_RUNTIME_DIR": str(self.run_dir),
                "JOURNAL": str(self.journal),
                "ETAT": str(self.etat),
                "REGLAGES": str(self.reglages),
            }
        )
        environ.update(env or {})
        return environ

    def jouer(self, jeu='echo jeu >>"$JOURNAL"; exit 7', env=None, **kw):
        fini = subprocess.run(
            [str(PASSATION), "sh", "-c", jeu],
            capture_output=True,
            text=True,
            env=self.environ(env),
            timeout=30,
            **kw,
        )
        return fini, self.journal.read_text(encoding="utf-8").splitlines()

    def test_an_active_unit_is_stopped_then_started_again(self):
        self.unite("active")
        fini, journal = self.jouer()
        self.assertEqual(7, fini.returncode, fini.stderr)
        self.assertEqual(
            [
                f"systemctl --user is-active {UNITE}",
                f"systemctl --user stop {UNITE}",
                "jeu",
                f"systemctl --user reset-failed {UNITE}",
                f"systemctl --user start {UNITE}",
            ],
            journal,
        )
        self.assertEqual("active", self.etat.read_text().strip())

    def test_a_unit_waiting_to_restart_is_stopped_too(self):
        """Pendant RestartSec, l'unité est « activating » : laissée seule,
        son redémarrage prendrait le deck en pleine partie."""
        self.unite("activating")
        fini, journal = self.jouer()
        self.assertEqual(7, fini.returncode, fini.stderr)
        self.assertEqual(f"systemctl --user stop {UNITE}", journal[1])
        self.assertEqual(f"systemctl --user start {UNITE}", journal[-1])

    def test_a_stopped_unit_stays_stopped(self):
        self.unite("inactive")
        fini, journal = self.jouer()
        self.assertEqual(7, fini.returncode, fini.stderr)
        self.assertEqual(
            [f"systemctl --user is-active {UNITE}", "jeu"], journal
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

    def test_the_game_runs_under_the_deck_lock_as_game(self):
        fini, _journal = self.jouer(
            f"{sys.executable} -c '{VU_DU_JEU}' {DECK_DIR}",
        )
        self.assertEqual(0, fini.returncode, fini.stderr)
        self.assertEqual("game\n", fini.stdout)
        verrou = charger_verrou()
        self.assertIsNone(
            verrou.holder(verrou.lock_path({"XDG_RUNTIME_DIR": self.run_dir}))
        )

    def test_a_deck_held_elsewhere_runs_no_game(self):
        verrou = charger_verrou()
        tenu = verrou.acquire(
            "tiler", verrou.lock_path({"XDG_RUNTIME_DIR": self.run_dir})
        )
        self.addCleanup(tenu.close)
        fini, journal = self.jouer()
        self.assertEqual(2, fini.returncode, fini.stderr)
        self.assertIn("tiler", fini.stderr)
        self.assertNotIn("jeu", journal)

    def test_an_interrupted_game_still_gives_the_deck_back(self):
        """Le signal frappe tout le groupe de processus, comme un Ctrl-C au
        terminal : le jeu meurt du signal, le script relance le service puis
        sort avec le code du jeu, 128 + le numéro du signal."""
        for signal_, code in (("INT", 130), ("TERM", 143)):
            with self.subTest(signal=signal_):
                self.journal.write_text("", encoding="utf-8")
                self.unite("active")
                fini, journal = self.jouer(
                    f'echo jeu >>"$JOURNAL"; kill -{signal_} 0; sleep 5',
                    start_new_session=True,
                )
                self.assertEqual(code, fini.returncode, fini.stderr)
                self.assertEqual(
                    f"systemctl --user start {UNITE}", journal[-1]
                )

    def test_sigterm_to_the_script_alone_lets_the_game_finish(self):
        """bash attend la fin du jeu avant de traiter un signal qui ne vise
        que lui : le jeu finit, puis le deck revient au service."""
        self.unite("active")
        proc = subprocess.Popen(
            [
                str(PASSATION),
                "sh",
                "-c",
                'echo debut >>"$JOURNAL"; sleep 1; echo jeu >>"$JOURNAL";'
                " exit 7",
            ],
            env=self.environ(),
            stderr=subprocess.DEVNULL,
        )
        self.addCleanup(proc.kill)
        for _fois in range(100):
            if "debut" in self.journal.read_text(encoding="utf-8"):
                break
            time.sleep(0.05)
        proc.send_signal(signal.SIGTERM)
        self.assertEqual(7, proc.wait(20))
        journal = self.journal.read_text(encoding="utf-8").splitlines()
        self.assertIn("jeu", journal)
        self.assertEqual(f"systemctl --user start {UNITE}", journal[-1])

    def test_a_failed_stop_runs_the_game_and_restarts_nothing(self):
        self.unite("active")
        fini, journal = self.jouer(env={"ECHEC_STOP": "1"})
        self.assertEqual(7, fini.returncode)
        self.assertIn("could not stop", fini.stderr)
        self.assertIn("jeu", journal)
        self.assertNotIn(f"systemctl --user start {UNITE}", journal)

    def test_games_off_refuses_before_stopping_anything(self):
        self.unite("active")
        for valeur in ("off", "", "yes"):
            with self.subTest(valeur=valeur):
                self.journal.write_text("", encoding="utf-8")
                self.regler(f"GAMES={valeur}\n")
                fini, journal = self.jouer()
                self.assertEqual(4, fini.returncode)
                self.assertEqual([], journal)
                self.assertIn("Stream Deck games are disabled", fini.stderr)
                self.assertEqual(1, len(fini.stderr.strip().splitlines()))

    def test_games_on_or_missing_still_play(self):
        self.unite("inactive")
        for texte in ("GAMES=on\n", "DECK_PROGRAM=tiler\n"):
            with self.subTest(texte=texte):
                self.journal.write_text("", encoding="utf-8")
                self.regler(texte)
                fini, journal = self.jouer()
                self.assertEqual(7, fini.returncode, fini.stderr)
                self.assertIn("jeu", journal)

    def test_handover_reads_xdg_config_home(self):
        self.unite("inactive")
        autre = self.tmp / "autre"
        (autre / "erplibre-home").mkdir(parents=True)
        (autre / "erplibre-home/streamdeck.conf").write_text("GAMES=off\n")
        fini, _ = self.jouer(env={"XDG_CONFIG_HOME": str(autre)})
        self.assertEqual(4, fini.returncode)

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
