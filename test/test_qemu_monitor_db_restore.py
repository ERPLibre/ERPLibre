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
- le bouton passe les options cochées, et rien ne part sans confirmation ;
- rien ne part vers une VM dont l'identité n'est plus prouvée : ligne
  effacée, domaine dont l'UUID a changé, adresse que libvirt ne confirme
  pas, VMID qu'une VM Proxmox ne porte plus — avant la question comme
  après le oui.

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
        self.sortie = fin.stdout
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


class TestLesDeuxLangues(unittest.TestCase):
    """L'écran des actions VM et ses confirmations suivent la langue choisie,
    au moment où ils s'affichent."""

    def langue(self, code):
        from script.todo import todo_i18n

        self.addCleanup(
            setattr, todo_i18n, "_current_lang", todo_i18n._current_lang
        )
        todo_i18n._current_lang = code

    def test_the_confirmations_follow_the_language(self):
        self.langue("en")
        en = " ".join(
            mon.db_restore_lines(["neutralize"])
            + mon.delete_lines({"name": "vm-a"})
        )
        self.langue("fr")
        fr = " ".join(
            mon.db_restore_lines(["neutralize"])
            + mon.delete_lines({"name": "vm-a"})
        )
        self.assertIn("DROPPED", en)
        self.assertIn("ERASED", en)
        self.assertIn("SUPPRIMÉE", fr)
        self.assertIn("EFFACÉ", fr)
        for texte in (en, fr):
            self.assertIn(mon.DB_RESTORE_NAME, texte)
            self.assertIn("/var/lib/libvirt/images/vm-a.qcow2", texte)

    def test_every_tick_box_label_is_translated(self):
        from script.todo.todo_i18n import TRANSLATIONS

        for _cle, libelle in mon.UPDATE_PARTS + mon.DB_RESTORE_PARTS:
            with self.subTest(libelle=libelle):
                self.assertIn(libelle, TRANSLATIONS)


class TestLesMessagesDansLaVM(Bac):
    """Ce que les commandes affichent dans la VM suit la langue choisie, et
    une traduction ne peut rien développer dans le shell."""

    def setUp(self):
        super().setUp()
        self.erplibre(self.home / "git" / "erplibre")

    def test_the_restore_speaks_english_with_its_variables(self):
        from script.todo import todo_i18n

        self.addCleanup(
            setattr, todo_i18n, "_current_lang", todo_i18n._current_lang
        )
        todo_i18n._current_lang = "en"
        self.lance(mon.db_restore_cmd([]), rc=3)
        self.assertIn("== Restoring test from odoo18.0_base ==", self.sortie)
        self.assertIn("== Restore finished (code 3) ==", self.sortie)

    def test_a_translation_expands_nothing(self):
        texte = 'a "b" $HOME `id` \\c'
        fin = subprocess.run(
            ["bash", "-c", f'echo "{mon._dq(texte)}"'],
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertEqual(texte, fin.stdout.rstrip("\n"))


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


class Suivi(AsyncCase):
    """Le suivi ouvert sur une VM, libvirt remplacé."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        # Ce que libvirt répond : l'adresse du domaine, son UUID.
        self.adresse = "127.0.0.9"
        self.uuid = "uuid-ancien"
        for cible, valeur in (
            ("read_domstats", lambda: ""),
            ("arm_balloon", lambda names: None),
            ("virsh_domstates", lambda: {}),
            ("virsh_ip", lambda nom: self.adresse),
            ("local_uuid", lambda nom: self.uuid),
            ("_port_open", lambda ip, port=8069, timeout=0.5: False),
        ):
            patch = mock.patch.object(mon, cible, valeur)
            patch.start()
            self.addCleanup(patch.stop)
        self.app = self.ouvre()

    def ouvre(self, **extra):
        """Le suivi d'une session à une VM ; `extra` complète son entrée."""
        log = self.base / "vm-a.log"
        log.write_text(f"x\n{mon.EXIT_MARKER} 0\n")
        entree = {
            "name": "vm-a",
            "ip": "127.0.0.9",
            "log": str(log),
            "ssh": "ssh erplibre@127.0.0.9",
        }
        entree.update(extra)
        manifeste = self.base / "session.json"
        manifeste.write_text(
            json.dumps(
                {
                    "branch": "develop",
                    "started": time.time(),
                    "vms": [entree],
                }
            )
        )
        return mon.run_monitor(str(manifeste), run_app=False)

    async def demande(self, pilote):
        """Ouvre les actions de la VM et appuie sur la restauration."""
        from textual.widgets import Checkbox

        app = self.app
        await pilote.pause()
        await pilote.press("a")
        await pilote.pause()
        app.screen.query_one("#d_neutralize", Checkbox).value = False
        app.screen.query_one("#a_dbrestore").press()
        await pilote.pause()
        await pilote.pause()

    async def bouton(self, pilote, oui, pendant=None):
        """`pendant` : ce qui change pendant que la question est ouverte."""
        app = self.app
        await self.demande(pilote)
        self.assertEqual("ConfirmScreen", type(app.screen).__name__)
        if pendant:
            pendant()
        app.screen.query_one("#c_yes" if oui else "#c_no").press()
        await pilote.pause()
        await pilote.pause()


class TestLeBouton(Suivi):
    async def test_the_ticked_options_reach_the_command_after_yes(self):
        with mock.patch.object(type(self.app), "_run_in_vm") as lance:
            async with self.app.run_test(size=(150, 40)) as pilote:
                await self.bouton(pilote, oui=True)
        lance.assert_called_once()
        # Un mock posé sur la classe ne reçoit pas « self ».
        vm, cmd, _titre = lance.call_args[0]
        self.assertEqual("vm-a", vm["name"])
        self.assertEqual(mon.db_restore_cmd(["ignore_cache"]), cmd)
        self.assertEqual("", lance.call_args[1]["guard"])

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


class TestLIdentiteDeLaVm(Suivi):
    """L'adresse en mémoire peut désigner une autre machine : la ligne, le
    domaine et son adresse sont vérifiés avant la question et juste avant
    de partir."""

    async def refusee_avant_la_question(self, preparer=None):
        with mock.patch.object(
            type(self.app), "_run_in_vm"
        ) as lance, mock.patch.object(type(self.app), "notify") as notify:
            async with self.app.run_test(size=(150, 40)) as pilote:
                if preparer:
                    await pilote.pause()
                    preparer()
                await self.demande(pilote)
                self.assertNotEqual(
                    "ConfirmScreen", type(self.app.screen).__name__
                )
        lance.assert_not_called()
        return notify.call_args[0][0]

    async def refusee_apres_oui(self, pendant=None):
        with mock.patch.object(
            type(self.app), "_run_in_vm"
        ) as lance, mock.patch.object(type(self.app), "notify") as notify:
            async with self.app.run_test(size=(150, 40)) as pilote:
                await self.bouton(pilote, oui=True, pendant=pendant)
        lance.assert_not_called()
        return notify.call_args[0][0]

    async def test_a_deleted_row_is_refused_before_the_question(self):
        msg = await self.refusee_avant_la_question(
            lambda: self.app._domstate.__setitem__("vm-a", "gone")
        )
        self.assertEqual(
            mon.t("{name} was deleted: restore refused.").format(name="vm-a"),
            msg,
        )

    async def test_a_reused_name_is_refused_before_the_question(self):
        self.app = self.ouvre(uuid="uuid-ancien")
        self.uuid = "uuid-autre"
        msg = await self.refusee_avant_la_question()
        self.assertEqual(
            mon.t(
                "The domain {name} is no longer the deployed VM"
                " (deleted, or its name reused): restore refused."
            ).format(name="vm-a"),
            msg,
        )

    async def test_an_unreadable_virsh_refuses_a_known_uuid(self):
        self.app = self.ouvre(uuid="uuid-ancien")
        self.uuid = ""
        await self.refusee_avant_la_question()

    async def test_a_deletion_during_the_question_is_refused_after_yes(self):
        await self.refusee_apres_oui(
            lambda: self.app._domstate.__setitem__("vm-a", "gone")
        )

    async def test_a_domain_replaced_during_the_question_is_refused(self):
        self.app = self.ouvre(uuid="uuid-ancien")

        def remplace():
            self.uuid = "uuid-autre"

        await self.refusee_apres_oui(remplace)

    async def test_an_address_libvirt_does_not_confirm_is_refused(self):
        self.adresse = ""
        msg = await self.refusee_apres_oui()
        self.assertEqual(
            mon.t(
                "libvirt knows no address for {name} (VM stopped?):"
                " restore refused."
            ).format(name="vm-a"),
            msg,
        )

    async def test_the_address_is_read_again_before_running(self):
        self.app = self.ouvre(uuid="uuid-ancien")
        self.adresse = "127.0.0.42"
        with mock.patch.object(type(self.app), "_run_in_vm") as lance:
            async with self.app.run_test(size=(150, 40)) as pilote:
                await self.bouton(pilote, oui=True)
        vm = lance.call_args[0][0]
        self.assertEqual("127.0.0.42", vm["ip"])

    async def test_a_proxmox_vm_has_its_vmid_checked_by_its_host(self):
        info = {"vmid": 101, "target": "root@hote.invalid", "addr": "10.9.9.9"}
        self.app = self.ouvre(pve=info)
        self.adresse = ""
        with mock.patch.object(type(self.app), "_run_in_vm") as lance:
            async with self.app.run_test(size=(150, 40)) as pilote:
                await self.bouton(pilote, oui=True)
        garde = lance.call_args[1]["guard"]
        self.assertEqual(
            mon.pve_host_cmd(info, mon.pve_identity_guard(101, "vm-a")),
            garde,
        )


class TestLaGardePasseAvantLeSsh(unittest.TestCase):
    """_run_in_vm : une garde en échec empêche la connexion."""

    def lance(self, garde):
        app = None
        with tempfile.TemporaryDirectory() as coin:
            log = Path(coin, "vm-a.log")
            log.write_text(f"x\n{mon.EXIT_MARKER} 0\n")
            manifeste = Path(coin, "session.json")
            manifeste.write_text(
                json.dumps(
                    {
                        "branch": "d",
                        "vms": [
                            {
                                "name": "vm-a",
                                "ip": "127.0.0.9",
                                "log": str(log),
                            }
                        ],
                    }
                )
            )
            app = mon.run_monitor(str(manifeste), run_app=False)
        vu = []
        with mock.patch.object(
            app, "suspend", mock.MagicMock()
        ), mock.patch.object(mon.os, "system", vu.append), mock.patch(
            "builtins.input", lambda *a: ""
        ), mock.patch(
            "builtins.print"
        ):
            app._run_in_vm(app._vm_by_name("vm-a"), "echo x", "t", guard=garde)
        return vu[0]

    def test_the_guard_is_chained_before_ssh(self):
        cmd = self.lance("false")
        self.assertTrue(cmd.startswith("false && ssh "), cmd)

    def test_a_failing_guard_never_reaches_ssh(self):
        cmd = self.lance("false").replace("ssh ", "echo SSH ", 1)
        res = subprocess.run(
            ["bash", "-c", cmd], capture_output=True, text=True
        )
        self.assertNotIn("SSH", res.stdout)

    def test_without_a_guard_ssh_comes_first(self):
        self.assertTrue(self.lance("").startswith("ssh "))


if __name__ == "__main__":
    unittest.main()
