#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Le menu Production : simulation d'abord, exécution réelle sur accord.

La mise à jour arrête un service ; la sauvegarde, la restauration et la
minuterie écrivent. Le menu doit donc toujours passer par la simulation,
ne rien lancer quand elle refuse, demander avant l'exécution réelle, et ne
lancer celle-ci que sous sudo, sans capture. L'état des sauvegardes se lit
sans sudo. Rien n'est réellement exécuté : `execute` est remplacé,
`subprocess.run` aussi.
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))
sys.argv = ["todo.py"]

from script.todo.todo import TODO  # noqa: E402


class FauxExecute:
    """Retient les commandes et rend le code demandé."""

    def __init__(self, code=0):
        self.code = code
        self.commandes = []
        self.options = []

    def exec_command_live(self, cmd, **kw):
        self.commandes.append(cmd)
        self.options.append(kw)
        return self.code


def lancer(reponses, code_simulation=0, confirme=True, seule=False):
    """Joue `_ops_update_modules` avec ces réponses ; rend (todo, run,
    confirm)."""
    todo = TODO.__new__(TODO)
    todo.execute = FauxExecute(code_simulation)
    with (
        mock.patch("builtins.input", side_effect=reponses),
        mock.patch(
            "script.todo.ops_menu.click.confirm", return_value=confirme
        ) as confirm,
        mock.patch(
            "script.todo.ops_menu.subprocess.run",
            return_value=mock.Mock(returncode=0),
        ) as run,
        mock.patch("builtins.print"),
    ):
        todo._ops_update_modules(simulation_seule=seule)
    return todo, run, confirm


class TestMiseAJourDepuisLeMenu(unittest.TestCase):
    def test_simulation_puis_execution_sous_sudo(self):
        todo, run, confirm = lancer(["my_module_a,my_module_b", "demo_db", ""])
        self.assertEqual(len(todo.execute.commandes), 1)
        simulation = todo.execute.commandes[0]
        self.assertIn("update_module.py", simulation)
        self.assertIn("--dry-run", simulation)
        self.assertIn("--db demo_db", simulation)
        self.assertNotIn("--no-backup", simulation)
        self.assertIs(todo.execute.options[0]["source_erplibre"], False)
        self.assertTrue(confirm.called)
        argv = run.call_args.args[0]
        self.assertEqual(argv[0], "sudo")
        self.assertNotIn("--dry-run", argv)
        self.assertIn("my_module_a,my_module_b", argv)
        # Sans capture : le terminal reste au programme.
        self.assertNotIn("capture_output", run.call_args.kwargs)
        self.assertNotIn("stdout", run.call_args.kwargs)

    def test_base_vide_et_sans_sauvegarde(self):
        todo, run, _ = lancer(["base", "", "n"])
        argv = run.call_args.args[0]
        self.assertNotIn("--db", argv)
        self.assertIn("--no-backup", argv)

    def test_refus_de_la_confirmation(self):
        todo, run, _ = lancer(["base", "", ""], confirme=False)
        self.assertEqual(len(todo.execute.commandes), 1)
        self.assertFalse(run.called)

    def test_simulation_qui_refuse_n_execute_rien(self):
        todo, run, confirm = lancer(["base", "", ""], code_simulation=2)
        self.assertFalse(confirm.called)
        self.assertFalse(run.called)

    def test_simulation_seule(self):
        todo, run, confirm = lancer(["base", "", ""], seule=True)
        self.assertEqual(len(todo.execute.commandes), 1)
        self.assertFalse(confirm.called)
        self.assertFalse(run.called)

    def test_sans_module_rien_n_est_lance(self):
        todo, run, _ = lancer([""])
        self.assertEqual(todo.execute.commandes, [])
        self.assertFalse(run.called)

    def test_valeurs_citees_pour_le_shell(self):
        todo, _, _ = lancer(["base; id", "", ""], confirme=False)
        self.assertIn("'base; id'", todo.execute.commandes[0])


def jouer(methode, reponses, code_simulation=0, confirme=True):
    """Joue une entrée de sauvegarde ; rend (todo, run, confirm)."""
    todo = TODO.__new__(TODO)
    todo.execute = FauxExecute(code_simulation)
    with (
        mock.patch("builtins.input", side_effect=reponses),
        mock.patch(
            "script.todo.ops_menu.click.confirm", return_value=confirme
        ) as confirm,
        mock.patch(
            "script.todo.ops_menu.subprocess.run",
            return_value=mock.Mock(returncode=0),
        ) as run,
        mock.patch("builtins.print"),
    ):
        getattr(todo, methode)()
    return todo, run, confirm


class TestSauvegardeDepuisLeMenu(unittest.TestCase):
    """Les entrées de sauvegarde : simulation, accord, sudo sans capture."""

    CAS = (
        ("_ops_backup_now", ["demo_db"], "odoo_backup.py", []),
        (
            "_ops_test_restore",
            [""],
            "odoo_backup.py",
            ["--test-restore"],
        ),
        (
            "_ops_restore_new_database",
            ["/srv/sauvegardes/demo_db/x.zip", "copie_db"],
            "odoo_backup.py",
            [
                "--restore",
                "--file",
                "/srv/sauvegardes/demo_db/x.zip",
                "--into",
                "copie_db",
            ],
        ),
        ("_ops_backup_timer", ["", "demo_db"], "install_backup_timer.py", []),
        (
            "_ops_backup_timer",
            ["r", ""],
            "install_backup_timer.py",
            ["--uninstall"],
        ),
    )

    def test_simulation_accord_puis_sudo(self):
        for methode, reponses, script, attendus in self.CAS:
            with self.subTest(methode=methode, reponses=reponses):
                todo, run, confirm = jouer(methode, reponses)
                self.assertEqual(len(todo.execute.commandes), 1)
                simulation = todo.execute.commandes[0]
                self.assertIn(script, simulation)
                self.assertTrue(simulation.endswith("--dry-run"))
                self.assertIs(
                    todo.execute.options[0]["source_erplibre"], False
                )
                self.assertTrue(confirm.called)
                argv = run.call_args.args[0]
                self.assertEqual(argv[0], "sudo")
                self.assertTrue(argv[2].endswith(script))
                self.assertNotIn("--dry-run", argv)
                for valeur in attendus:
                    self.assertIn(valeur, argv)
                self.assertNotIn("capture_output", run.call_args.kwargs)
                self.assertNotIn("stdout", run.call_args.kwargs)

    def test_base_transmise_ou_detectee(self):
        _, run, _ = jouer("_ops_backup_now", ["demo_db"])
        self.assertEqual(run.call_args.args[0][-2:], ["--db", "demo_db"])
        _, run, _ = jouer("_ops_backup_now", [""])
        self.assertNotIn("--db", run.call_args.args[0])

    def test_refus_de_l_accord(self):
        for methode, reponses, _script, _attendus in self.CAS:
            with self.subTest(methode=methode):
                todo, run, _ = jouer(methode, reponses, confirme=False)
                self.assertEqual(len(todo.execute.commandes), 1)
                self.assertFalse(run.called)

    def test_simulation_qui_refuse_n_execute_rien(self):
        for methode, reponses, _script, _attendus in self.CAS:
            with self.subTest(methode=methode):
                _, run, confirm = jouer(methode, reponses, code_simulation=2)
                self.assertFalse(confirm.called)
                self.assertFalse(run.called)

    def test_restauration_sans_fichier_ni_base(self):
        for reponses in ([""], ["x.zip", ""]):
            with self.subTest(reponses=reponses):
                todo, run, _ = jouer("_ops_restore_new_database", reponses)
                self.assertEqual(todo.execute.commandes, [])
                self.assertFalse(run.called)

    def test_valeurs_citees_pour_le_shell(self):
        todo, _, _ = jouer(
            "_ops_restore_new_database", ["a b.zip", "x; id"], confirme=False
        )
        self.assertIn("'a b.zip'", todo.execute.commandes[0])
        self.assertIn("'x; id'", todo.execute.commandes[0])

    def test_etat_sans_sudo_ni_accord(self):
        for code in (0, 1, 2):
            with self.subTest(code=code):
                todo, run, confirm = jouer(
                    "_ops_backup_status", [], code_simulation=code
                )
                self.assertEqual(len(todo.execute.commandes), 1)
                self.assertIn("--status", todo.execute.commandes[0])
                self.assertNotIn("sudo", todo.execute.commandes[0])
                self.assertFalse(confirm.called)
                self.assertFalse(run.called)


class TestLeMenuEstBranche(unittest.TestCase):
    def test_retour_rend_false(self):
        todo = TODO.__new__(TODO)
        with (
            mock.patch("script.todo.ops_menu.click.prompt", return_value="0"),
            mock.patch.object(TODO, "fill_help_info", return_value=""),
            mock.patch("builtins.print"),
        ):
            self.assertIs(todo.prompt_execute_production(), False)

    def choisir(self, choix, reponses=("base", "", "")):
        """Joue le menu au clavier : `choix`, puis 0 ; rend (todo, run)."""
        todo = TODO.__new__(TODO)
        todo.execute = FauxExecute(0)
        with (
            mock.patch(
                "script.todo.ops_menu.click.prompt",
                side_effect=[choix, "0"],
            ),
            mock.patch.object(TODO, "fill_help_info", return_value=""),
            mock.patch("builtins.input", side_effect=list(reponses)),
            mock.patch(
                "script.todo.ops_menu.click.confirm", return_value=True
            ),
            mock.patch(
                "script.todo.ops_menu.subprocess.run",
                return_value=mock.Mock(returncode=0),
            ) as run,
            mock.patch("builtins.print"),
        ):
            self.assertIs(todo.prompt_execute_production(), False)
        return todo, run

    def test_choix_2_simule_seulement(self):
        todo, run = self.choisir("2")
        self.assertEqual(len(todo.execute.commandes), 1)
        self.assertIn("--dry-run", todo.execute.commandes[0])
        self.assertFalse(run.called)

    def test_choix_1_execute_sous_sudo(self):
        todo, run = self.choisir("1")
        self.assertIn("--dry-run", todo.execute.commandes[0])
        self.assertEqual(run.call_args.args[0][0], "sudo")

    def test_choix_3_a_7(self):
        for choix, reponses, script in (
            ("3", [""], "odoo_backup.py"),
            ("5", [""], "odoo_backup.py"),
            ("6", ["x.zip", "copie_db"], "odoo_backup.py"),
            ("7", ["", ""], "install_backup_timer.py"),
        ):
            with self.subTest(choix=choix):
                todo, run = self.choisir(choix, reponses)
                self.assertIn(script, todo.execute.commandes[0])
                self.assertIn("--dry-run", todo.execute.commandes[0])
                self.assertEqual(run.call_args.args[0][0], "sudo")
        todo, run = self.choisir("4", [])
        self.assertIn("--status", todo.execute.commandes[0])
        self.assertFalse(run.called)

    def test_entree_17_du_menu_execute(self):
        source = (RACINE / "script" / "todo" / "todo.py").read_text()
        self.assertIn(
            '[17] {t("Production - Update, back up and restore a systemd'
            ' instance")}',
            source,
        )
        self.assertIn("status = self.prompt_execute_production()", source)
        self.assertEqual(
            TODO._MENU_LABELS["prompt_execute_production"], "Production"
        )


if __name__ == "__main__":
    unittest.main()
