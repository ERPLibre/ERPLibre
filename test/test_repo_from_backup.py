#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""La configuration tirée d'une sauvegarde s'arrête quand aucun dépôt n'est lu.

La chaîne est get_repo_from_module.py → get_repo_from_backup.py →
git_repo_update_group.py, puis generate_config.sh par le menu TODO. Chaque
maillon ne doit transmettre que des chemins de dépôt : une ligne de journal
qui passe pour un dépôt rend la liste non vide, et la garde qui arrête la
génération ne joue plus.
"""

import io
import json
import os
import shutil
import sys
import tempfile
import unittest
import zipfile
from contextlib import redirect_stdout
from unittest import mock

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
)

from script.database import (
    get_repo_from_backup,  # noqa: E402
    get_repo_from_module,  # noqa: E402
)
from script.git import git_repo_update_group  # noqa: E402

# La sortie d'une exécution non muette : en-tête, commande, pied.
BRUIT = [
    "🏠 ⬇ Execute command :",
    "",
    "source ./.venv.erplibre/bin/activate && ./script/x.py",
    "ERROR:__main__:Missing module 'module_inconnu'",
    "🏠 ⬆ Executed (0.12 sec.) :",
]


class TestReposFromLines(unittest.TestCase):
    def setUp(self):
        self.racine = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.racine)

    def module(self, depot, nom):
        chemin = os.path.join(self.racine, depot, nom)
        os.makedirs(chemin)
        return chemin

    def test_seuls_les_dossiers_de_module_donnent_un_depot(self):
        a = self.module("depot_a", "mod_1")
        b = self.module("depot_a", "mod_2")
        c = self.module("depot_b", "mod_3")
        depots = get_repo_from_module.repos_from_lines(BRUIT + [a, b, c])
        self.assertEqual(
            depots,
            [
                os.path.join(self.racine, "depot_a"),
                os.path.join(self.racine, "depot_b"),
            ],
        )

    def test_un_journal_seul_ne_donne_aucun_depot(self):
        self.assertEqual(get_repo_from_module.repos_from_lines(BRUIT), [])


class TestReposFromOutput(unittest.TestCase):
    RACINE = "/opt/essai_erplibre"

    def test_garde_les_chemins_sous_la_racine_relatifs(self):
        lignes = BRUIT + [
            f"{self.RACINE}/odoo18.0/addons/OCA_web",
            f"  {self.RACINE}/odoo18.0/addons/OCA_crm  ",
            "/ailleurs/odoo18.0/addons/OCA_hr",
        ]
        self.assertEqual(
            git_repo_update_group.repos_from_output(lignes, self.RACINE),
            ["odoo18.0/addons/OCA_web", "odoo18.0/addons/OCA_crm"],
        )

    def test_une_sortie_de_bruit_est_vide(self):
        self.assertEqual(
            git_repo_update_group.repos_from_output(
                BRUIT + [self.RACINE + "/"], self.RACINE
            ),
            [],
        )


class TestUpdateGroupDepuisSauvegarde(unittest.TestCase):
    def lancer(self, sortie, statut=0):
        execution = mock.Mock()
        execution.exec_command_live.return_value = (statut, sortie)
        outil_git = mock.Mock()
        with (
            mock.patch.object(
                git_repo_update_group.execute,
                "Execute",
                return_value=execution,
            ),
            mock.patch.object(
                git_repo_update_group, "GitTool", return_value=outil_git
            ),
            mock.patch.object(
                sys,
                "argv",
                ["git_repo_update_group.py", "--from_backup_name", "essai"],
            ),
            mock.patch("sys.stderr", new_callable=io.StringIO) as erreur,
        ):
            try:
                git_repo_update_group.main()
                code = 0
            except SystemExit as sortie_systeme:
                code = sortie_systeme.code
        return code, outil_git, erreur.getvalue()

    def test_une_sortie_de_bruit_arrete_la_generation(self):
        code, outil_git, erreur = self.lancer(BRUIT)
        self.assertEqual(code, 1)
        outil_git.generate_generate_config.assert_not_called()
        self.assertIn("config not generated", erreur)

    def test_des_depots_lus_generent_la_configuration(self):
        depot = os.path.join(os.getcwd(), "odoo18.0", "addons", "OCA_web")
        code, outil_git, _ = self.lancer(BRUIT + [depot])
        self.assertEqual(code, 0)
        _, kwargs = outil_git.generate_generate_config.call_args
        self.assertEqual(kwargs["whitelist"], ["odoo18.0/addons/OCA_web"])


class TestGetRepoFromBackup(unittest.TestCase):
    def setUp(self):
        self.dossier = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dossier)
        self.zip = os.path.join(self.dossier, "essai.zip")
        with zipfile.ZipFile(self.zip, "w") as z:
            z.writestr("manifest.json", json.dumps({"modules": {"web": "18"}}))

    def test_n_imprime_que_les_depots_et_rend_le_statut(self):
        execution = mock.Mock()
        execution.exec_command_live.return_value = (0, ["/r/depot_a"])
        with (
            mock.patch.object(
                get_repo_from_backup.execute,
                "Execute",
                return_value=execution,
            ),
            mock.patch.object(
                sys,
                "argv",
                ["get_repo_from_backup.py", "--backup_path", self.zip],
            ),
            redirect_stdout(io.StringIO()) as vu,
            self.assertRaises(SystemExit) as sortie,
        ):
            get_repo_from_backup.main()
        self.assertEqual(sortie.exception.code, 0)
        self.assertEqual(vu.getvalue(), "/r/depot_a\n")
        _, kwargs = execution.exec_command_live.call_args
        self.assertTrue(kwargs["quiet"])


class TestGenerateConfigTodo(unittest.TestCase):
    def setUp(self):
        from script.todo import todo as todo_module

        self.obj = todo_module.TODO.__new__(todo_module.TODO)
        self.commandes = []
        self.statut = 0

        def faux_exec(_self, cmd, **_kw):
            self.commandes.append(cmd)
            return self.statut

        self.obj.execute = type("E", (), {"exec_command_live": faux_exec})()

    def test_le_filtre_et_la_generation_sont_lies_par_et(self):
        self.obj.generate_config(add_arg="--from_backup_name essai")
        self.assertIn(
            "./script/git/git_repo_update_group.py --from_backup_name essai"
            " && ./script/generate_config.sh",
            self.commandes[0],
        )

    def test_un_filtre_en_echec_est_dit(self):
        self.statut = 1
        with redirect_stdout(io.StringIO()) as vu:
            statut = self.obj.generate_config(add_arg="--group base")
        self.assertEqual(statut, 1)
        self.assertIn("❌", vu.getvalue())

    def test_une_generation_sans_filtre_ne_dit_rien(self):
        with redirect_stdout(io.StringIO()) as vu:
            self.assertEqual(self.obj.generate_config(), 0)
        self.assertEqual(vu.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
