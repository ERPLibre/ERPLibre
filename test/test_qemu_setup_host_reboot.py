#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le redémarrage de l'hôte se demande, il ne se déduit pas.

« --setup-host » installe des paquets, et sur une distribution à noyau
roulant il peut avoir besoin d'un redémarrage pour que libvirt monte virbr0.
Ces deux actes n'ont pas le même prix : le premier s'annule, le second emporte
tout ce qui tourne sur la machine.

Ce que ces tests gardent :

- « --assume-yes » couvre le gestionnaire de paquets, JAMAIS le redémarrage.
- « --reboot-if-needed » PROPOSE ; un refus laisse la machine debout et sort
  en erreur, sans jamais programmer le redémarrage.
- « --assume-yes-reboot » est le seul consentement qui se passe de question,
  et il est réservé à la provision d'une VM que personne ne regarde.
- La commande du menu hôte ne le porte pas ; celle du profil invité le porte.
"""

import importlib.util
import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.argv = ["todo.py"]

RACINE = Path(__file__).resolve().parents[1]


def _deploy_qemu():
    """deploy_qemu.py chargé comme module, comme le fait todo.py."""
    path = RACINE / "script/qemu/deploy_qemu.py"
    spec = importlib.util.spec_from_file_location("deploy_qemu", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


DQ = _deploy_qemu()

# L'état exact qui déclenche la question : le noyau a été remplacé depuis le
# démarrage, donc le réseau « default » ne peut pas monter.
NOYAU_PERIME = "Le noyau en cours n'a plus ses modules."


class SetupHostReboot(unittest.TestCase):
    def _lancer(self, reponse=False, **kwargs):
        """setup_host sur un hôte au noyau périmé et au réseau inactif.

        Rend le triplet (redémarrages, questions, SystemExit ou None). Tout
        ce qui touche au système est neutralisé : seul l'enchaînement des
        décisions est sous test. « reponse » est ce que l'utilisateur répond
        si la question lui est posée.
        """
        runner = mock.MagicMock()
        runner.dry_run = False
        runner.use_sudo = False
        reboots = []
        questions = []

        def question(texte, default=True):
            questions.append(texte)
            return reponse

        with mock.patch.object(DQ, "ensure_tools"), mock.patch.object(
            DQ, "ensure_libvirt_service"
        ), mock.patch.object(
            DQ, "ensure_libvirt_group", return_value=True
        ), mock.patch.object(
            DQ, "ensure_ssh_key"
        ), mock.patch.object(
            DQ, "ensure_network"
        ), mock.patch.object(
            DQ, "kernel_modules_stale", return_value=NOYAU_PERIME
        ), mock.patch.object(
            DQ, "libvirt_ready", return_value=True
        ), mock.patch.object(
            DQ, "network_state", return_value=(False, True)
        ), mock.patch.object(
            DQ, "schedule_reboot", side_effect=lambda r: reboots.append(r)
        ), mock.patch.object(
            DQ, "prompt_yes_no", side_effect=question
        ):
            with redirect_stdout(io.StringIO()):
                try:
                    DQ.setup_host(runner, **kwargs)
                    sortie = None
                except SystemExit as exc:
                    sortie = exc
        return reboots, questions, sortie

    def test_assume_yes_alone_never_reboots(self):
        """La régression même : accepter l'installation des paquets ne
        redémarrait pas la machine, mais l'appelant, lui, ajoutait le drapeau
        qui le faisait. Sans le drapeau, rien ne redémarre et rien n'est
        demandé."""
        reboots, questions, sortie = self._lancer(
            assume_yes=True, no_install=False, reboot_if_needed=False
        )
        self.assertEqual(reboots, [])
        self.assertEqual(questions, [])
        self.assertIsInstance(sortie, SystemExit)

    def test_reboot_if_needed_asks_and_a_refusal_stops(self):
        reboots, questions, sortie = self._lancer(
            assume_yes=True,
            no_install=False,
            reboot_if_needed=True,
            reponse=False,
        )
        self.assertEqual(len(questions), 1, questions)
        self.assertEqual(reboots, [])
        self.assertIsInstance(sortie, SystemExit)
        # Le refus doit se lire dans le message : un « pas prêt » sec laisse
        # croire à une panne alors que la machine a obéi.
        self.assertIn("refusé", str(sortie))

    def test_reboot_if_needed_reboots_when_accepted(self):
        reboots, questions, sortie = self._lancer(
            assume_yes=True,
            no_install=False,
            reboot_if_needed=True,
            reponse=True,
        )
        self.assertEqual(len(questions), 1)
        self.assertEqual(len(reboots), 1)
        self.assertIsNone(sortie)

    def test_assume_yes_reboot_skips_the_question(self):
        """La provision d'une VM neuve n'a personne pour répondre : sans ce
        drapeau, la question tomberait sur un EOF et la VM resterait sur un
        noyau sans modules."""
        reboots, questions, sortie = self._lancer(
            assume_yes=True,
            no_install=False,
            reboot_if_needed=True,
            assume_yes_reboot=True,
        )
        self.assertEqual(questions, [])
        self.assertEqual(len(reboots), 1)
        self.assertIsNone(sortie)


class ConsentInTheCallers(unittest.TestCase):
    """Le drapeau se lit dans les commandes que TODO fabrique."""

    @staticmethod
    def _commande_hote():
        """La chaîne assignée à « cmd » dans _qemu_ensure_tools.

        Lue par l'arbre syntaxique et non par le texte : un commentaire qui
        NOMME le drapeau pour expliquer son absence est légitime, et une
        recherche textuelle le prendrait pour la commande.
        """
        import ast

        source = (RACINE / "script/todo/qemu_menu.py").read_text(
            encoding="utf-8"
        )
        for node in ast.walk(ast.parse(source)):
            if (
                isinstance(node, ast.FunctionDef)
                and node.name == "_qemu_ensure_tools"
            ):
                for stmt in ast.walk(node):
                    if (
                        isinstance(stmt, ast.Assign)
                        and getattr(stmt.targets[0], "id", "") == "cmd"
                    ):
                        return ast.literal_eval(stmt.value)
        raise AssertionError("cmd introuvable dans _qemu_ensure_tools")

    def test_the_host_menu_never_assumes_the_reboot(self):
        cmd = self._commande_hote()
        self.assertIn("--setup-host", cmd)
        self.assertIn("--reboot-if-needed", cmd)
        self.assertNotIn("--assume-yes-reboot", cmd)

    def test_the_guest_profile_carries_the_explicit_consent(self):
        source = (RACINE / "script/todo/qemu_install.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("--assume-yes-reboot", source)

    def test_the_flag_exists_in_the_parser(self):
        parser = DQ.build_parser()
        rendu = parser.format_help()
        self.assertIn("--assume-yes-reboot", rendu)


if __name__ == "__main__":
    unittest.main()
