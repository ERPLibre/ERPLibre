#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Le menu de l'audit de performance : la commande ssh construite, la durée
validée avant tout envoi, les messages des codes de sortie, et le lancement
local depuis le menu Production.

Aucune commande n'est lancée : le lanceur est injecté et retient ce qu'il
reçoit. Les préférences ne sont jamais lues (hôte placé en cache).
"""

import io
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))
sys.argv = ["todo.py"]

from script.todo import ops_menu, todo_i18n  # noqa: E402
from script.todo.todo import TODO  # noqa: E402

AUDIT = str(RACINE / "script" / "proxmox" / "host_perf_audit.py")
_LANGUE = []


def setUpModule():
    """Les messages sont vérifiés en anglais, quelle que soit la langue
    du poste."""
    _LANGUE.append(todo_i18n._current_lang)
    todo_i18n._current_lang = "en"


def tearDownModule():
    todo_i18n._current_lang = _LANGUE.pop()


class FauxLanceur:
    """Retient argv et options ; rend `code` ou lève `erreur`."""

    def __init__(self, code=0, erreur=None):
        self.code = code
        self.erreur = erreur
        self.appels = []

    def __call__(self, argv, stdin=None, timeout=None):
        self.appels.append(
            {
                "argv": list(argv),
                "stdin": getattr(stdin, "name", stdin),
                "ouvert": stdin is not None and not stdin.closed,
                "timeout": timeout,
            }
        )
        if self.erreur is not None:
            raise self.erreur
        return self.code


def todo_avec_hote(**hote):
    todo = TODO.__new__(TODO)
    base = {
        "target": "root@pve.example.org",
        "jump": "jump.example.org",
        "sudo": "",
    }
    base.update(hote)
    todo._pve_host_cache = base
    return todo


def jouer(todo, reponses, lanceur):
    """Joue l'entrée du menu Proxmox ; rend ce qui a été affiché."""
    sortie = io.StringIO()
    with (
        mock.patch("builtins.input", side_effect=reponses),
        mock.patch("sys.stdout", sortie),
    ):
        todo._pve_perf_audit(runner=lanceur)
    return sortie.getvalue()


class TestAuditDistant(unittest.TestCase):
    def test_commande_ssh_exacte(self):
        lanceur = FauxLanceur()
        affiche = jouer(todo_avec_hote(), ["10m", "1"], lanceur)
        self.assertEqual(len(lanceur.appels), 1)
        appel = lanceur.appels[0]
        self.assertEqual(
            appel["argv"],
            [
                "ssh",
                "-T",
                "-o",
                "ServerAliveInterval=30",
                "-o",
                "BatchMode=yes",
                "-o",
                "ConnectTimeout=10",
                "-J",
                "jump.example.org",
                "root@pve.example.org",
                "python3 -I - --duration 600",
            ],
        )
        self.assertEqual(appel["stdin"], AUDIT)
        self.assertTrue(appel["ouvert"])
        self.assertEqual(appel["timeout"], 600 + ops_menu.MARGE_AUDIT_S)
        self.assertIn("< script/proxmox/host_perf_audit.py", affiche)

    def test_independant_des_options_de_ssh_argv(self):
        """L'argv se construit quelles que soient les options que ssh_argv
        place avant la cible : aucune n'est cherchée par sa valeur."""
        from script.proxmox import proxmox_deploy

        for options in ([], ["-o", "ConnectTimeout=15"], ["-4"]):
            with self.subTest(options=options):
                faux = mock.Mock(
                    return_value=["ssh"]
                    + options
                    + ["root@pve.example.org", "r"]
                )
                with mock.patch.object(proxmox_deploy, "ssh_argv", faux):
                    argv = TODO._pve_perf_argv(
                        {"target": "root@pve.example.org"}, 60
                    )
                self.assertEqual(
                    argv,
                    ["ssh", "-T", "-o", "ServerAliveInterval=30"]
                    + options
                    + ["root@pve.example.org", "r"],
                )
                faux.assert_called_once_with(
                    {"target": "root@pve.example.org"},
                    "python3 -I - --duration 60",
                )

    def test_sudo_sans_mot_de_passe_et_port(self):
        lanceur = FauxLanceur()
        jouer(todo_avec_hote(sudo="sudo ", port="2222"), ["10m", "1"], lanceur)
        argv = lanceur.appels[0]["argv"]
        self.assertEqual(
            argv[-1], "sudo -n sh -c 'python3 -I - --duration 600'"
        )
        self.assertEqual(argv[argv.index("-p") + 1], "2222")
        self.assertEqual(argv[:2], ["ssh", "-T"])

    def test_duree_refusee_avant_tout_envoi(self):
        for saisie in ("10m; touch /tmp/p", "0", "8d", "soon"):
            with self.subTest(saisie=saisie):
                lanceur = FauxLanceur()
                affiche = jouer(todo_avec_hote(), [saisie, "1"], lanceur)
                self.assertEqual(lanceur.appels, [])
                self.assertIn("duration refused", affiche)

    def test_duree_par_defaut(self):
        lanceur = FauxLanceur()
        jouer(todo_avec_hote(), ["", "1"], lanceur)
        self.assertTrue(lanceur.appels[0]["argv"][-1].endswith(" 60"))

    def test_messages_des_codes(self):
        for code, attendu in (
            (127, "python3 is missing"),
            (255, "SSH connection failed"),
            (2, "could not run"),
            (1, "ended with code"),
        ):
            with self.subTest(code=code):
                affiche = jouer(
                    todo_avec_hote(), ["10m", "1"], FauxLanceur(code)
                )
                self.assertIn(attendu, affiche)

    def test_delai_et_ctrl_c(self):
        affiche = jouer(
            todo_avec_hote(),
            ["10m", "1"],
            FauxLanceur(erreur=subprocess.TimeoutExpired("ssh", 900)),
        )
        self.assertIn("did not finish in time", affiche)
        affiche = jouer(
            todo_avec_hote(),
            ["10m", "1"],
            FauxLanceur(erreur=KeyboardInterrupt()),
        )
        self.assertIn("without its report", affiche)

    def test_choix_inconnu(self):
        lanceur = FauxLanceur()
        affiche = jouer(todo_avec_hote(), ["10m", "9"], lanceur)
        self.assertEqual(lanceur.appels, [])
        self.assertIn("Cancel", affiche)


class TestAuditLocal(unittest.TestCase):
    def test_depuis_le_menu_proxmox(self):
        lanceur = FauxLanceur()
        jouer(todo_avec_hote(), ["", "2"], lanceur)
        appel = lanceur.appels[0]
        self.assertEqual(
            appel["argv"], [sys.executable, AUDIT, "--duration", "60"]
        )
        self.assertIsNone(appel["stdin"])
        self.assertNotIn("ssh", appel["argv"])
        self.assertNotIn("sudo", appel["argv"])
        self.assertEqual(appel["timeout"], 60 + ops_menu.MARGE_AUDIT_S)

    def test_depuis_le_menu_production(self):
        lanceur = FauxLanceur()
        todo = TODO.__new__(TODO)
        sortie = io.StringIO()
        with (
            mock.patch("builtins.input", side_effect=["2h"]),
            mock.patch("sys.stdout", sortie),
            mock.patch.object(ops_menu, "lancer_en_direct", lanceur),
        ):
            todo._ops_perf_audit()
        self.assertEqual(
            lanceur.appels[0]["argv"],
            [sys.executable, AUDIT, "--duration", "7200"],
        )
        self.assertIn("sudo", sortie.getvalue())

    def test_ctrl_c_local(self):
        affiche = jouer(
            todo_avec_hote(),
            ["", "2"],
            FauxLanceur(erreur=KeyboardInterrupt()),
        )
        self.assertIn("covers the samples", affiche)

    def test_le_fichier_existe(self):
        self.assertTrue(os.path.isfile(ops_menu.HOST_PERF_AUDIT))


class FauxProcessus:
    def __init__(self, attentes):
        self.attentes = list(attentes)
        self.termine = False
        self.tue = False
        self.delais = []

    def wait(self, timeout=None):
        self.delais.append(timeout)
        effet = self.attentes.pop(0) if self.attentes else 0
        if isinstance(effet, BaseException):
            raise effet
        return effet

    def terminate(self):
        self.termine = True

    def kill(self):
        self.tue = True


class TestLancerEnDirect(unittest.TestCase):
    def lancer(self, attentes):
        proc = FauxProcessus(attentes)
        with mock.patch.object(
            ops_menu.subprocess, "Popen", return_value=proc
        ):
            try:
                return ops_menu.lancer_en_direct(["x"], timeout=5), proc
            except BaseException as err:  # noqa: B036
                return err, proc

    def test_code_rendu(self):
        code, proc = self.lancer([3])
        self.assertEqual(code, 3)
        self.assertFalse(proc.termine)
        self.assertEqual(proc.delais, [5])

    def test_ctrl_c_attend_le_rapport(self):
        err, proc = self.lancer([KeyboardInterrupt(), 0])
        self.assertIsInstance(err, KeyboardInterrupt)
        self.assertFalse(proc.termine)
        self.assertEqual(proc.delais, [5, ops_menu.ATTENTE_RAPPORT_S])

    def test_second_ctrl_c_arrete(self):
        err, proc = self.lancer([KeyboardInterrupt(), KeyboardInterrupt(), 0])
        self.assertIsInstance(err, KeyboardInterrupt)
        self.assertTrue(proc.termine)
        self.assertEqual(proc.delais, [5, ops_menu.ATTENTE_RAPPORT_S, 10])

    def test_delai(self):
        err, proc = self.lancer([subprocess.TimeoutExpired("x", 5), 0])
        self.assertIsInstance(err, subprocess.TimeoutExpired)
        self.assertTrue(proc.termine)
        self.assertEqual(proc.delais, [5, 10])


if __name__ == "__main__":
    unittest.main()
