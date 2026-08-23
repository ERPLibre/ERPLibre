#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Suivre un déploiement qui n'installe PAS ERPLibre.

Symptôme rapporté : en décochant l'installation d'ERPLibre, le tableau de bord
ne s'ouvrait plus du tout. Deux causes, l'une derrière l'autre :

- la case « suivi » vivait DANS le groupe de l'installation ERPLibre, et
  `build_spec` ne la recopiait même pas dans la spec finale ;
- l'épilogue du déploiement était gardé par « if install or desktop » : sans
  rien à installer, il ne se passait rien.

Et si le suivi s'ouvrait quand même, il n'aurait rien montré : la commande
distante valait « true », donc un journal vide et un ✅ instantané. Elle
regarde maintenant la VM ARRIVER — cloud-init, puis un relevé système — ce qui
donne un début, une fin, et de quoi juger qu'elle est prête.
"""

import contextlib
import io
import os
import subprocess
import sys
import unittest

sys.argv = ["todo.py"]
from script.todo import qemu_install_monitor as mon  # noqa: E402
from script.todo.qemu_deploy_form import build_spec  # noqa: E402
from script.todo.todo import TODO  # noqa: E402


class TestLaCommandeDistante(unittest.TestCase):
    def setUp(self):
        self.todo = TODO.__new__(TODO)

    def _sans_rien(self):
        return self.todo._qemu_erplibre_remote_cmd(None)

    def test_it_is_no_longer_a_bare_true(self):
        """« true » rendait un journal vide et un ✅ instantané : le suivi
        s'ouvrait sur rien."""
        self.assertNotEqual("true", self._sans_rien().strip())

    def test_it_is_valid_shell(self):
        res = subprocess.run(
            ["bash", "-n"],
            input=self._sans_rien(),
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, res.returncode, res.stderr)

    def test_it_waits_for_cloud_init(self):
        """C'est le vrai « suivi » d'une VM neuve : tant que cloud-init tourne,
        la machine n'est pas prête."""
        self.assertIn("cloud-init status --wait", self._sans_rien())

    def test_it_frames_the_step_so_the_monitor_can_bound_it(self):
        """Le tableau lit ces marqueurs pour dire où en est la VM."""
        cmd = self._sans_rien()
        self.assertIn("===>", cmd)
        self.assertIn("<===", cmd)

    def test_it_reports_what_says_the_vm_is_up(self):
        cmd = self._sans_rien()
        for morceau in ("/etc/os-release", "uname -r", "hostname -I", "df -h"):
            self.assertIn(morceau, cmd, morceau)

    def test_it_runs_and_says_something(self):
        """Exécutée ici, hors VM : l'attente de cloud-init est neutralisée, le
        relevé doit sortir et rendre 0."""
        cmd = self._sans_rien().replace(
            "sudo timeout 900 cloud-init status --wait", "true"
        )
        res = subprocess.run(
            ["bash", "-c", cmd], capture_output=True, text=True, timeout=60
        )
        self.assertEqual(0, res.returncode, res.stderr[-300:])
        self.assertIn("===>", res.stdout)
        self.assertIn("<===", res.stdout)
        # Trois lignes de relevé au moins : sans elles, le journal est creux.
        self.assertGreaterEqual(len(res.stdout.strip().splitlines()), 5)

    def test_a_desktop_only_vm_still_installs_its_desktop(self):
        """Le chemin qui marchait déjà ne doit pas changer de sens."""
        self.todo._qemu_desktop_remote_cmd = lambda d, s: "INSTALLE_BUREAU; "
        self.todo._qemu_tools_remote_cmd = lambda *a, **k: ""
        self.todo._qemu_no_auto_upgrade = lambda *a, **k: ""
        cmd = self.todo._qemu_erplibre_remote_cmd(None, desktop="gnome")
        self.assertIn("INSTALLE_BUREAU", cmd)


class TestLaSpecDuFormulaire(unittest.TestCase):
    def _form(self, **extra):
        base = {
            "res_label": "x1",
            "ssh_key": "/k.pub",
            "install": None,
            "add_ssh_config": False,
            "parallelism": 1,
        }
        base.update(extra)
        return base

    def test_the_choice_reaches_the_spec(self):
        """Il ne la recopiait pas : le choix du formulaire n'atteignait jamais
        le déploiement."""
        spec = build_spec([], [], self._form(monitor=True))
        self.assertTrue(spec["monitor"])
        spec = build_spec([], [], self._form(monitor=False))
        self.assertFalse(spec["monitor"])

    def test_an_old_form_without_the_key_still_monitors(self):
        """Compatibilité : une spec enregistrée avant ce changement ne doit pas
        perdre son tableau de bord."""
        self.assertTrue(build_spec([], [], self._form())["monitor"])


class TestLaDecisionDuDeploiement(unittest.TestCase):
    """L'épilogue : qui est appelé, et avec quoi."""

    def _joue(self, spec):
        todo = TODO.__new__(TODO)
        appels = []
        todo._qemu_install_erplibre_monitored = lambda *a, **k: appels.append(
            "suivi"
        )
        todo._qemu_install_erplibre_vm = lambda *a, **k: appels.append("muet")
        todo._qemu_resolve_ips = lambda names, labels=None: {}
        base = {
            "vms": [],
            "existing": ["vm-a"],
            "install": None,
            "add_ssh_config": False,
            "parallelism": 1,
        }
        base.update(spec)
        with contextlib.redirect_stdout(io.StringIO()):
            todo._qemu_run_spec(base)
        return appels

    def test_without_erplibre_the_monitor_still_opens(self):
        """Le cœur du problème rapporté."""
        self.assertEqual(["suivi"], self._joue({"monitor": True}))

    def test_a_spec_without_the_key_monitors_too(self):
        self.assertEqual(["suivi"], self._joue({}))

    def test_refusing_the_monitor_does_nothing_at_all(self):
        """Et surtout : ne pas partir installer un profil qui n'existe pas.
        L'ancien repli faisait « install['cmd'] » sur un None."""
        self.assertEqual([], self._joue({"monitor": False}))

    def test_an_install_without_the_monitor_takes_the_quiet_path(self):
        appels = self._joue(
            {
                "monitor": False,
                "install": {
                    "branch": "develop",
                    "prod": False,
                    "cmd": "make x",
                    "monitor": False,
                },
            }
        )
        self.assertEqual(["muet"], appels)

    def test_the_install_keeps_the_last_word_on_its_own_monitoring(self):
        appels = self._joue(
            {
                "monitor": False,
                "install": {
                    "branch": "develop",
                    "prod": False,
                    "cmd": "make x",
                    "monitor": True,
                },
            }
        )
        self.assertEqual(["suivi"], appels)


class TestLeJournal(unittest.TestCase):
    """L'en-tête et le prologue ne doivent pas annoncer ce qui n'a pas lieu."""

    def _vm(self):
        return {
            "name": "vm-a",
            "ip": "10.0.0.9",
            "distro": "debian",
            "version": "13",
            "arch": "amd64",
        }

    def test_an_install_is_titled_an_install(self):
        head = mon._log_header(self._vm(), "develop", "2026-01-01 00:00:00")
        self.assertIn(mon.t("installation"), head)
        self.assertIn("develop", head)

    def test_without_a_branch_it_is_not_called_an_install(self):
        """« ERPLibre — installation » puis « Branche : » vide, sur un
        déploiement qui n'installe rien : le journal se contredisait."""
        head = mon._log_header(self._vm(), "", "2026-01-01 00:00:00")
        self.assertIn(mon.t("VM start-up"), head)
        self.assertNotIn("Branche", head)

    def test_the_prologue_says_what_actually_follows(self):
        """« installation ERPLibre en cours » alors que rien ne s'installe."""
        import tempfile
        from pathlib import Path

        vus = []
        vrai_launch, vrai_dir = mon._launch_one, mon.session_dir
        mon._launch_one = (
            lambda ip, cmd, log, name="", installs=True: vus.append(installs)
        )
        # session_dir détournée : sans cela le test écrivait de VRAIES sessions
        # dans ~/.erplibre/qemu-install, qui polluaient l'historique que
        # « Rouvrir le suivi » propose à l'utilisateur.
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        mon.session_dir = lambda: Path(tmp.name)
        try:
            mon.launch_installs([self._vm()], "", "true")
            mon.launch_installs([self._vm()], "develop", "true")
        finally:
            mon._launch_one, mon.session_dir = vrai_launch, vrai_dir
        self.assertEqual([False, True], vus)

    def test_the_host_key_notice_is_not_a_warning(self):
        """ssh l'écrit à CHAQUE première connexion : comptée, la colonne ⚠
        s'allumait sur toute installation, dès sa première ligne."""
        import tempfile

        with tempfile.NamedTemporaryFile(
            "w", suffix=".log", delete=False, encoding="utf-8"
        ) as fh:
            fh.write(
                "Warning: Permanently added '10.0.0.9' (ED25519) to the"
                " list of known hosts.\n__ERPLIBRE_EXIT__ 0\n"
            )
            chemin = fh.name
        self.addCleanup(os.unlink, chemin)
        self.assertEqual((0, 0), mon.scan_log_errors(chemin))


if __name__ == "__main__":
    unittest.main(verbosity=1)
