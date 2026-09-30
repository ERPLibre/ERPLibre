#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le menu Système : le diagnostic et son rapport, le choix de l'espace à
récupérer, au formulaire comme en ligne.

Les faits du poste sont fabriqués : un test ne dépend ni du matériel ni des
commandes installées là où il tourne.
"""

import asyncio
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.argv = ["todo.py"]
from script.todo import system_cleanup as sc  # noqa: E402
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


class TestLeChoixEnLigne(unittest.TestCase):
    def candidats(self):
        return [
            sc.Candidat("cache", ".cache/pip", ["/a"], 3000, coche=True),
            sc.Candidat("filestore", "orpheline", ["/b"], 2000),
            sc.Candidat(
                "venv", ".venv.odoo16", ["/c"], 1000, mise_en_garde="reinstall"
            ),
        ]

    def choisir(self, reponse):
        with (
            mock.patch("builtins.input", return_value=reponse),
            mock.patch("builtins.print"),
        ):
            return sm.choisir_en_ligne(self.candidats())

    def test_enter_takes_the_checked_ones(self):
        self.assertEqual(self.choisir(""), [0])

    def test_numbers_pick_those_ones(self):
        self.assertEqual(self.choisir("2, 3"), [1, 2])

    def test_out_of_range_numbers_are_ignored(self):
        self.assertEqual(self.choisir("0,4,2"), [1])

    def test_c_cancels(self):
        self.assertIsNone(self.choisir("c"))

    def test_the_label_says_size_category_and_warning(self):
        ligne = sm.libelle(self.candidats()[2])
        self.assertIn("1000 o", ligne)
        self.assertIn("Venv d'une autre version d'Odoo", ligne)
        self.assertIn("réinstaller", ligne)


class TestLeFormulaire(unittest.TestCase):
    def test_the_checked_boxes_are_returned(self):
        candidats = [
            sc.Candidat("cache", ".cache/pip", ["/a"], 3000, coche=True),
            sc.Candidat("filestore", "orpheline", ["/b"], 2000),
        ]
        app = sm.formulaire(candidats)
        if app is None:
            self.skipTest("Textual absent")
        vu = {}

        async def scenario():
            from textual.widgets import SelectionList

            async with app.run_test(size=(120, 20)) as pilote:
                await pilote.pause()
                liste = app.query_one(SelectionList)
                vu["avant"] = list(liste.selected)
                liste.select(1)
                await pilote.click("#effacer")
                await pilote.pause()
            vu["rendu"] = app.return_value

        asyncio.run(scenario())
        self.assertEqual(vu["avant"], [0])
        self.assertEqual(sorted(vu["rendu"]), [0, 1])

    def test_cancel_returns_none(self):
        app = sm.formulaire(
            [sc.Candidat("cache", ".cache/pip", ["/a"], 3000, coche=True)]
        )
        if app is None:
            self.skipTest("Textual absent")

        async def scenario():
            async with app.run_test(size=(120, 20)) as pilote:
                await pilote.pause()
                await pilote.click("#annuler")
                await pilote.pause()

        asyncio.run(scenario())
        self.assertIsNone(app.return_value)


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


class TestLesLibelles(unittest.TestCase):
    def test_every_category_warning_and_reason_is_translated(self):
        for cle in (
            list(sm.LIBELLES_CATEGORIE.values())
            + list(sm.MISES_EN_GARDE.values())
            + list(sm.RAISONS.values())
        ):
            self.assertIn(cle, todo_i18n.TRANSLATIONS, cle)


if __name__ == "__main__":
    unittest.main()
