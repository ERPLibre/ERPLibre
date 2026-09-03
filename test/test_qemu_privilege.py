#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le privilège se sonde, il ne se suppose pas.

Appartenir au groupe libvirt suffit à joindre qemu:///system. Préfixer alors
chaque commande de « sudo » ne donne aucun droit de plus et réclame un mot de
passe à chaque entrée de menu.

Ce que ces tests gardent :

- la question se tranche en ESSAYANT ; /etc/group ne dit que ce qui est
  DÉCLARÉ, et les groupes d'un processus sont figés à l'ouverture de session ;
- root ne demande jamais sudo, et une machine sans virsh non plus — une invite
  de mot de passe pour une commande introuvable ne mène nulle part ;
- l'avertissement d'avant-installation se tait quand l'accès est déjà là.
"""

import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.argv = ["todo.py"]
from script.todo import qemu_privilege as qp  # noqa: E402
from script.todo.todo import TODO  # noqa: E402


class Sondage(unittest.TestCase):
    def setUp(self):
        qp.reset_cache()

    def tearDown(self):
        qp.reset_cache()

    def _sonde(self, rc):
        class Res:
            returncode = rc
            stdout = ""
            stderr = ""

        return mock.patch.object(qp.subprocess, "run", return_value=Res())

    def test_reachable_means_no_sudo(self):
        with mock.patch.object(
            qp.shutil, "which", return_value="/usr/bin/virsh"
        ), mock.patch.object(qp.os, "geteuid", return_value=1000), self._sonde(
            0
        ):
            self.assertFalse(qp.needs_sudo())
            self.assertEqual(qp.sudo_prefix(), "")

    def test_unreachable_means_sudo(self):
        with mock.patch.object(
            qp.shutil, "which", return_value="/usr/bin/virsh"
        ), mock.patch.object(qp.os, "geteuid", return_value=1000), self._sonde(
            1
        ):
            self.assertTrue(qp.needs_sudo())
            self.assertEqual(qp.sudo_prefix(), "sudo ")

    def test_root_never_needs_sudo(self):
        with mock.patch.object(
            qp.shutil, "which", return_value="/usr/bin/virsh"
        ), mock.patch.object(qp.os, "geteuid", return_value=0), self._sonde(1):
            self.assertFalse(qp.needs_sudo())

    def test_without_virsh_no_password_prompt(self):
        """Demander un mot de passe pour lancer une commande introuvable ne
        mène nulle part : l'échec doit être « command not found »."""
        with mock.patch.object(
            qp.shutil, "which", return_value=None
        ), mock.patch.object(qp.os, "geteuid", return_value=1000):
            self.assertFalse(qp.needs_sudo())

    def test_the_probe_runs_once(self):
        """Chaque entrée de menu la demande : un virsh par commande se
        verrait."""
        with mock.patch.object(
            qp.shutil, "which", return_value="/usr/bin/virsh"
        ), mock.patch.object(qp.os, "geteuid", return_value=1000):
            with self._sonde(0) as run:
                for _ in range(5):
                    qp.needs_sudo()
                self.assertEqual(run.call_count, 1)

    def test_a_dead_probe_falls_back_on_sudo(self):
        """Un virsh qui n'arrive pas au bout ne prouve pas l'accès : mieux
        vaut une invite de mot de passe qu'une commande refusée."""
        with mock.patch.object(
            qp.shutil, "which", return_value="/usr/bin/virsh"
        ), mock.patch.object(
            qp.os, "geteuid", return_value=1000
        ), mock.patch.object(
            qp.subprocess, "run", side_effect=OSError("boom")
        ):
            self.assertTrue(qp.needs_sudo())


class AvertissementAvantInstallation(unittest.TestCase):
    def setUp(self):
        qp.reset_cache()
        self.todo = TODO.__new__(TODO)

    def tearDown(self):
        qp.reset_cache()

    def _rendu(self, joignable, declare, actif):
        with mock.patch.object(
            qp, "libvirt_reachable", return_value=joignable
        ), mock.patch.object(qp, "group_state", return_value=(declare, actif)):
            buf = io.StringIO()
            with redirect_stdout(buf):
                self.todo._qemu_warn_libvirt_access()
        return buf.getvalue()

    def test_it_stays_quiet_when_access_is_there(self):
        self.assertEqual("", self._rendu(True, True, True))

    def test_it_names_usermod_when_the_group_is_missing(self):
        rendu = self._rendu(False, False, False)
        self.assertIn("usermod -aG libvirt", rendu)

    def test_a_declared_but_inactive_group_asks_for_a_new_session(self):
        """Refaire un usermod déjà fait ne changerait rien : ce qui manque est
        une session, pas une ligne dans /etc/group."""
        rendu = self._rendu(False, True, False)
        self.assertIn("newgrp libvirt", rendu)
        self.assertNotIn("usermod", rendu)

    def test_an_active_group_says_nothing_even_if_virsh_fails(self):
        """Le groupe est porté par le processus : la cause est ailleurs
        (démon arrêté, socket absente) et l'accuser tromperait."""
        self.assertEqual("", self._rendu(False, True, True))


class LUriEstToujoursExplicite(unittest.TestCase):
    """Sans « --connect », un virsh non root vise qemu:///session.

    Cet hyperviseur-là est SÉPARÉ : aucune VM du système n'y existe, et
    « list --all » y rend une liste vide, sans erreur ni avertissement. Tant
    que les commandes passaient par sudo, l'URI de root masquait l'omission ;
    la retirer l'a mise au jour.
    """

    def test_the_builder_always_names_the_uri(self):
        for besoin in (True, False):
            with mock.patch.object(qp, "needs_sudo", return_value=besoin):
                argv = qp.virsh_argv("list", "--all")
                self.assertIn("--connect", argv)
                self.assertEqual(
                    qp.LIBVIRT_URI, argv[argv.index("--connect") + 1]
                )
                self.assertIn(f"--connect {qp.LIBVIRT_URI}", qp.virsh_cmd("x"))

    def test_sudo_only_when_the_probe_asks_for_it(self):
        with mock.patch.object(qp, "needs_sudo", return_value=False):
            self.assertNotIn("sudo", qp.virsh_argv("list"))
        with mock.patch.object(qp, "needs_sudo", return_value=True):
            self.assertEqual("sudo", qp.virsh_argv("list")[0])

    def test_no_menu_call_builds_virsh_by_hand(self):
        """Un virsh écrit à la main échapperait au constructeur, donc à
        l'URI : c'est exactement ce qui vidait la liste des VM."""
        for chemin in (
            "script/todo/qemu_manage.py",
            "script/todo/qemu_install_monitor.py",
        ):
            source = Path(chemin).read_text(encoding="utf-8")
            for num, ligne in enumerate(source.splitlines(), 1):
                if '"virsh"' not in ligne and "}virsh " not in ligne:
                    continue
                voisin = "\n".join(
                    source.splitlines()[max(0, num - 4) : num + 4]
                )
                self.assertIn(
                    "--connect",
                    voisin,
                    f"{chemin}:{num} appelle virsh sans URI",
                )


if __name__ == "__main__":
    unittest.main()
