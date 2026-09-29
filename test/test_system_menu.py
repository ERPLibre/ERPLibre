#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le menu Système : le diagnostic et son rapport.

Les faits du poste sont fabriqués : un test ne dépend ni du matériel ni des
commandes installées là où il tourne.
"""

import os
import sys
import tempfile
import unittest
from unittest import mock

sys.argv = ["todo.py"]
from script.todo import system_diagnostic as sd  # noqa: E402
from script.todo import system_menu as sm  # noqa: E402
from script.todo import todo_i18n  # noqa: E402


def setUpModule():
    ancienne = todo_i18n._current_lang
    todo_i18n._current_lang = "fr"
    unittest.addModuleCleanup(setattr, todo_i18n, "_current_lang", ancienne)


class TestLesSourcesAbsentes(unittest.TestCase):
    def test_a_missing_command_gives_none(self):
        with mock.patch.object(sd.shutil, "which", return_value=None):
            self.assertIsNone(sd.commande(["hostnamectl"]))
            self.assertIsNone(sd.cartes_graphiques())

    def test_identity_falls_back_without_hostnamectl(self):
        with (
            mock.patch.object(sd, "commande", return_value=None),
            mock.patch.object(sd, "lire", return_value=None),
        ):
            ident = sd.identite()
        self.assertTrue(ident["kernel"])
        self.assertIsNone(ident["vendor"])

    def test_every_missing_fact_reads_unavailable(self):
        faits = {
            "identity": dict.fromkeys(
                (
                    "hostname",
                    "os",
                    "kernel",
                    "architecture",
                    "chassis",
                    "virtualization",
                    "vendor",
                    "model",
                )
            ),
            "cpu": {"model": None, "logical": None, "physical": None},
            "memory": dict.fromkeys(
                ("total", "available", "swap_total", "swap_free")
            ),
            "gpu": None,
            "partitions": [],
            "load": {"load": None, "uptime": None},
            "erplibre": {
                "erplibre": None,
                "odoo": None,
                "python": None,
                "active_venv": None,
                "venvs": [],
            },
        }
        texte = "\n".join(sm.lignes_diagnostic(faits))
        self.assertIn("indisponible", texte)
        self.assertIn("lspci non installé", texte)
        self.assertNotIn("None", texte)


class TestLesFichiersDuSysteme(unittest.TestCase):
    def fichier(self, contenu):
        with tempfile.NamedTemporaryFile(
            "w", delete=False, encoding="utf-8"
        ) as fh:
            fh.write(contenu)
        self.addCleanup(os.unlink, fh.name)
        return fh.name

    def test_meminfo_in_bytes(self):
        chemin = self.fichier(
            "MemTotal:       2048 kB\nMemAvailable:   1024 kB\n"
            "SwapTotal:         0 kB\nSwapFree:          0 kB\n"
        )
        mem = sd.memoire(chemin)
        self.assertEqual(mem["total"], 2048 * 1024)
        self.assertEqual(mem["available"], 1024 * 1024)

    def test_only_data_filesystems_and_the_repo_marked(self):
        racine = tempfile.mkdtemp()
        self.addCleanup(os.rmdir, racine)
        mounts = self.fichier(
            "proc /proc proc rw 0 0\n"
            "tmpfs /run tmpfs rw 0 0\n"
            "/dev/sda1 / ext4 rw 0 0\n"
        )
        parts = sd.partitions(racine, mounts)
        self.assertEqual([p["mountpoint"] for p in parts], ["/"])
        self.assertTrue(parts[0]["repo"])


class TestLeRapport(unittest.TestCase):
    def test_the_report_lands_in_private_diagnostic(self):
        from script.todo.todo import TODO

        todo = TODO.__new__(TODO)
        ancien = os.getcwd()
        with tempfile.TemporaryDirectory() as tmp:
            os.chdir(tmp)
            try:
                with (
                    mock.patch("builtins.input", return_value="o"),
                    mock.patch("builtins.print"),
                ):
                    todo._system_diagnostic()
                fichiers = os.listdir(
                    os.path.join(tmp, "private", "diagnostic")
                )
                with open(
                    os.path.join(tmp, "private", "diagnostic", fichiers[0]),
                    encoding="utf-8",
                ) as fh:
                    contenu = fh.read()
            finally:
                os.chdir(ancien)
        self.assertEqual(len(fichiers), 1)
        self.assertTrue(fichiers[0].endswith(".txt"))
        self.assertIn("Identité", contenu)

    def test_no_report_without_a_yes(self):
        from script.todo.todo import TODO

        todo = TODO.__new__(TODO)
        ancien = os.getcwd()
        with tempfile.TemporaryDirectory() as tmp:
            os.chdir(tmp)
            try:
                with (
                    mock.patch("builtins.input", return_value=""),
                    mock.patch("builtins.print"),
                ):
                    todo._system_diagnostic()
                existe = os.path.exists(os.path.join(tmp, "private"))
            finally:
                os.chdir(ancien)
        self.assertFalse(existe)


if __name__ == "__main__":
    unittest.main()
