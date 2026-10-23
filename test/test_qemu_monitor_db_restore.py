#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Restauration d'une base depuis les actions VM du suivi d'installation.

Ce que ces tests gardent :

- le service erplibre est arrêté autour de la restauration, et relancé
  SEULEMENT s'il tournait, même quand la restauration échoue ;
- le code rendu est celui de la restauration ;
- l'image suit « .odoo-version », lue dans la VM ;
- le dossier ERPLibre vient de l'unité (production sous /opt), avec
  ~/git/erplibre en repli ; sans dossier, rien n'est arrêté ni restauré ;
- la mise à jour suit le même dossier ;
- le bouton passe les options cochées, et rien ne part sans confirmation.

Les commandes tournent pour de vrai sous bash, avec de faux systemctl,
sudo, git et db_restore.py qui notent leurs appels.
"""

import contextlib
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))
sys.path.insert(0, str(RACINE / "test"))

from async_case import AsyncCase  # noqa: E402

from script.todo import qemu_install_monitor as mon  # noqa: E402

FAUX_SYSTEMCTL = """#!/bin/sh
echo "systemctl $*" >> "$LOG"
case "$1" in
  list-unit-files) [ -n "$UNIT" ] && echo "erplibre.service enabled" ;;
  is-active) [ "$ACTIVE" = 1 ]; exit $? ;;
  show) echo "$WD" ;;
esac
exit 0
"""
FAUX_SUDO = """#!/bin/sh
exec "$@"
"""
FAUX_GIT = """#!/bin/sh
echo "git $* dans $(pwd)" >> "$LOG"
"""
# Les arguments séparés par « | » : un nom de base à espace doit rester UN
# argument.
FAUX_RESTORE = """#!/bin/sh
printf 'restore dans %s :' "$(pwd)" >> "$LOG"
for a in "$@"; do printf ' %s|' "$a" >> "$LOG"; done
echo >> "$LOG"
# TUE : la restauration est interrompue, comme par un ctrl+C ou une
# connexion coupée, qui atteignent le shell qui l'a lancée.
if [ -n "$TUE" ]; then kill -TERM $PPID; sleep 1; fi
exit ${RC:-0}
"""


def _ecrit(chemin, texte, executable=False):
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(texte)
    if executable:
        chemin.chmod(0o755)


class Bac(unittest.TestCase):
    """Une VM simulée : un HOME, un PATH de faux outils, un journal."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.home = self.base / "home"
        self.journal = self.base / "journal"
        for nom, texte in (
            ("systemctl", FAUX_SYSTEMCTL),
            ("git", FAUX_GIT),
        ):
            _ecrit(self.base / "bin" / nom, texte, executable=True)

    def erplibre(self, dossier, version="18.0\n"):
        _ecrit(dossier / ".odoo-version", version)
        _ecrit(
            dossier / "script" / "database" / "db_restore.py",
            FAUX_RESTORE,
            executable=True,
        )
        for script in ("install_git_repo.sh", "install_locally.sh"):
            _ecrit(
                dossier / "script" / "install" / script,
                f'#!/bin/sh\necho "{script} dans $(pwd)" >> "$LOG"\n',
                executable=True,
            )
        return dossier

    def lance(self, cmd, unit=True, actif=True, wd="", rc=0, tue=False):
        # Le PATH ci-dessous perd la doublure du lanceur : le faux sudo est
        # posé ici, pour que la commande n'atteigne jamais le vrai.
        _ecrit(self.base / "bin" / "sudo", FAUX_SUDO, executable=True)
        self.journal.write_text("")
        env = dict(
            os.environ,
            HOME=str(self.home),
            PATH=f"{self.base / 'bin'}:/usr/bin:/bin",
            LOG=str(self.journal),
            UNIT="1" if unit else "",
            ACTIVE="1" if actif else "0",
            WD=wd,
            RC=str(rc),
            TUE="1" if tue else "",
        )
        fin = subprocess.run(
            ["bash", "-c", cmd], env=env, capture_output=True, text=True
        )
        return fin.returncode, self.journal.read_text().splitlines()


class TestLaRestauration(Bac):
    def setUp(self):
        super().setUp()
        self.dev = self.erplibre(self.home / "git" / "erplibre")

    def restore(self, journal):
        return next(x for x in journal if x.startswith("restore"))

    def test_a_running_service_is_stopped_then_started(self):
        rc, journal = self.lance(mon.db_restore_cmd(["neutralize"]))
        self.assertEqual(0, rc)
        arret = journal.index("systemctl stop erplibre.service")
        self.assertLess(arret, journal.index(self.restore(journal)))
        self.assertEqual("systemctl start erplibre.service", journal[-1])

    def test_a_stopped_service_stays_stopped(self):
        _rc, journal = self.lance(mon.db_restore_cmd([]), actif=False)
        self.assertIn("systemctl stop erplibre.service", journal)
        self.assertNotIn("systemctl start erplibre.service", journal)

    def test_without_a_unit_nothing_is_stopped(self):
        rc, journal = self.lance(mon.db_restore_cmd([]), unit=False)
        self.assertEqual(0, rc)
        self.assertFalse([x for x in journal if " stop " in f" {x} "])
        self.assertTrue(self.restore(journal))

    def test_a_failed_restore_still_restarts_and_returns_its_code(self):
        rc, journal = self.lance(mon.db_restore_cmd([]), rc=3)
        self.assertEqual(3, rc)
        self.assertEqual("systemctl start erplibre.service", journal[-1])

    def test_an_interrupted_restore_still_restarts_the_service(self):
        rc, journal = self.lance(mon.db_restore_cmd([]), tue=True)
        self.assertNotEqual(0, rc)
        self.assertEqual(
            1, journal.count("systemctl start erplibre.service"), journal
        )

    def test_an_interrupted_restore_leaves_a_stopped_service_stopped(self):
        _rc, journal = self.lance(
            mon.db_restore_cmd([]), actif=False, tue=True
        )
        self.assertNotIn("systemctl start erplibre.service", journal)

    def test_a_finished_restore_restarts_the_service_once(self):
        _rc, journal = self.lance(mon.db_restore_cmd([]))
        self.assertEqual(1, journal.count("systemctl start erplibre.service"))

    def test_the_image_follows_the_checkout_version(self):
        self.erplibre(self.dev, version="17.0 \n")
        _rc, journal = self.lance(mon.db_restore_cmd([]))
        self.assertIn(" odoo17.0_base|", self.restore(journal))

    def test_only_the_ticked_options_are_passed(self):
        _rc, journal = self.lance(mon.db_restore_cmd(["ignore_cache", "x"]))
        ligne = self.restore(journal)
        self.assertIn(" --ignore_cache|", ligne)
        self.assertNotIn("--neutralize", ligne)
        self.assertNotIn(" x|", ligne)

    def test_the_database_name_stays_one_argument(self):
        _rc, journal = self.lance(mon.db_restore_cmd([], database="a b"))
        self.assertIn(" --database| a b|", self.restore(journal))

    def test_a_production_install_restores_under_its_unit_directory(self):
        prod = self.erplibre(self.base / "opt" / "erplibre")
        _rc, journal = self.lance(mon.db_restore_cmd([]), wd=str(prod))
        self.assertIn(f"restore dans {prod} :", self.restore(journal))

    def test_a_unit_directory_that_is_gone_falls_back_to_home(self):
        _rc, journal = self.lance(
            mon.db_restore_cmd([]), wd=str(self.base / "absent")
        )
        self.assertIn(f"restore dans {self.dev} :", self.restore(journal))

    def test_without_any_directory_nothing_is_stopped_or_restored(self):
        # Le dossier de développement retiré : ni unité utile, ni repli.
        for chemin in sorted(self.dev.rglob("*"), reverse=True):
            chemin.unlink() if chemin.is_file() else chemin.rmdir()
        self.dev.rmdir()
        rc, journal = self.lance(mon.db_restore_cmd([]))
        self.assertEqual(1, rc)
        self.assertNotIn("systemctl stop erplibre.service", journal)
        self.assertFalse([x for x in journal if x.startswith("restore")])

    def test_the_confirmation_names_what_is_lost(self):
        lignes = "\n".join(mon.db_restore_lines(["neutralize"]))
        self.assertIn(mon.DB_RESTORE_NAME, lignes)
        self.assertIn("crons", lignes)
        self.assertNotIn("crons", "\n".join(mon.db_restore_lines([])))


class TestLaMiseAJourSuitLeMemeDossier(Bac):
    def test_git_and_python_run_in_the_production_directory(self):
        self.erplibre(self.home / "git" / "erplibre")
        prod = self.erplibre(self.base / "opt" / "erplibre")
        _rc, journal = self.lance(
            mon.update_remote_cmd(["git", "python"]), wd=str(prod)
        )
        self.assertIn(f"git pull --ff-only dans {prod}", journal)
        self.assertIn(f"install_git_repo.sh dans {prod}", journal)
        self.assertIn(f"install_locally.sh dans {prod}", journal)


class TestLeBouton(AsyncCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        for cible, valeur in (
            ("read_domstats", lambda: ""),
            ("arm_balloon", lambda names: None),
            ("virsh_domstates", lambda: {}),
            ("virsh_ip", lambda nom: ""),
            ("_port_open", lambda ip, port=8069, timeout=0.5: False),
        ):
            patch = mock.patch.object(mon, cible, valeur)
            patch.start()
            self.addCleanup(patch.stop)
        log = base / "vm-a.log"
        log.write_text(f"x\n{mon.EXIT_MARKER} 0\n")
        manifeste = base / "session.json"
        manifeste.write_text(
            json.dumps(
                {
                    "branch": "develop",
                    "started": time.time(),
                    "vms": [
                        {
                            "name": "vm-a",
                            "ip": "127.0.0.9",
                            "log": str(log),
                            "ssh": "ssh erplibre@127.0.0.9",
                        }
                    ],
                }
            )
        )
        self.app = mon.run_monitor(str(manifeste), run_app=False)

    async def bouton(self, pilote, oui):
        from textual.widgets import Checkbox

        app = self.app
        await pilote.pause()
        await pilote.press("a")
        await pilote.pause()
        app.screen.query_one("#d_neutralize", Checkbox).value = False
        app.screen.query_one("#a_dbrestore").press()
        await pilote.pause()
        await pilote.pause()
        self.assertEqual("ConfirmScreen", type(app.screen).__name__)
        app.screen.query_one("#c_yes" if oui else "#c_no").press()
        await pilote.pause()
        await pilote.pause()

    async def test_the_ticked_options_reach_the_command_after_yes(self):
        with mock.patch.object(type(self.app), "_run_in_vm") as lance:
            async with self.app.run_test(size=(150, 40)) as pilote:
                await self.bouton(pilote, oui=True)
        lance.assert_called_once()
        # Un mock posé sur la classe ne reçoit pas « self ».
        vm, cmd, _titre = lance.call_args[0]
        self.assertEqual("vm-a", vm["name"])
        self.assertEqual(mon.db_restore_cmd(["ignore_cache"]), cmd)

    async def test_vm_actions_run_with_a_terminal(self):
        """Sans « ssh -t », sudo n'aurait pas où demander son mot de passe,
        et db_restore.py afficherait le mot de passe maître en clair."""
        lances = []
        async with self.app.run_test(size=(150, 40)) as pilote:
            await pilote.pause()
            vm = self.app._vm_by_name("vm-a")
            with mock.patch.object(
                self.app, "suspend", lambda: contextlib.nullcontext()
            ), mock.patch.object(
                mon.os, "system", lambda c: lances.append(c) or 0
            ), mock.patch(
                "builtins.input", lambda *a: ""
            ):
                self.app._run_in_vm(vm, "echo x", "essai")
        self.assertEqual(1, len(lances))
        self.assertTrue(lances[0].startswith("ssh -t "), lances[0])
        self.assertNotIn("-t", mon.vm_ssh_prefix(vm).split()[:2])

    async def test_nothing_runs_without_yes(self):
        with mock.patch.object(type(self.app), "_run_in_vm") as lance:
            async with self.app.run_test(size=(150, 40)) as pilote:
                await self.bouton(pilote, oui=False)
        lance.assert_not_called()


if __name__ == "__main__":
    unittest.main()
