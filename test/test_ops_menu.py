#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Le menu Production : simulation d'abord, exécution réelle sur accord.

La mise à jour arrête un service ; la sauvegarde, la restauration et la
minuterie écrivent. Le menu doit donc toujours passer par la simulation,
ne rien lancer quand elle refuse, demander avant l'exécution réelle, et ne
lancer celle-ci que sous sudo, sans capture. L'état des sauvegardes, le
journal d'Odoo, la liste des courriels en échec, la santé locale et le
préchauffage se lisent sans sudo ; le renvoi des courriels passe par sudo
après accord ; la santé d'une URL publique ne propose jamais sudo. Rien n'est réellement exécuté : `execute` est remplacé,
`subprocess.run` aussi.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))
sys.argv = ["todo.py"]

from script.todo import ops_menu  # noqa: E402
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


class TestJournalEtCourrielsDepuisLeMenu(unittest.TestCase):
    """Le journal et la liste des courriels se lisent sans sudo ; un refus
    de lecture (code 2) propose la même commande sous sudo. Le renvoi des
    courriels passe par sudo, sans capture, après accord."""

    def jouer(self, methode, reponses=(), code=0, confirme=True, ecrit=True):
        todo = TODO.__new__(TODO)
        todo.execute = FauxExecute(code)
        with (
            mock.patch("builtins.input", side_effect=list(reponses)),
            mock.patch(
                "script.todo.ops_menu.click.confirm", return_value=confirme
            ) as confirm,
            mock.patch(
                "script.todo.ops_menu.subprocess.run",
                return_value=mock.Mock(returncode=0),
            ) as run,
            mock.patch(
                "script.todo.ops_menu._inscriptible", return_value=ecrit
            ),
            mock.patch("builtins.print"),
        ):
            getattr(todo, methode)()
        return todo, run, confirm

    def test_lectures_sans_sudo(self):
        for methode, reponses, attendus in (
            ("_ops_log_since_last", [], ["log_check.py", "--since-last"]),
            ("_ops_log_last_hours", [""], ["log_check.py", "--last 24"]),
            ("_ops_log_last_hours", ["6"], ["--last 6"]),
            ("_ops_log_hourly", [""], ["--by-hour --days 7"]),
            ("_ops_log_hourly", ["3"], ["--by-hour --days 3"]),
            ("_ops_mail_list", [""], ["mail_retry.py", "--list"]),
            ("_ops_mail_list", ["base_essai"], ["--list --db base_essai"]),
        ):
            with self.subTest(methode=methode, reponses=reponses):
                todo, run, confirm = self.jouer(methode, reponses)
                (commande,) = todo.execute.commandes
                for attendu in attendus:
                    self.assertIn(attendu, commande)
                self.assertNotIn("sudo", commande)
                self.assertIs(
                    todo.execute.options[0]["source_erplibre"], False
                )
                self.assertFalse(confirm.called)
                self.assertFalse(run.called)

    def test_refus_de_lecture_propose_sudo(self):
        for methode, reponses in (
            ("_ops_log_last_hours", [""]),
            ("_ops_mail_list", [""]),
        ):
            with self.subTest(methode=methode):
                _todo, run, confirm = self.jouer(methode, reponses, code=2)
                self.assertTrue(confirm.called)
                argv = run.call_args.args[0]
                self.assertEqual(argv[0], "sudo")
                self.assertNotIn("capture_output", run.call_args.kwargs)
                _todo, run, _ = self.jouer(
                    methode, reponses, code=2, confirme=False
                )
                self.assertFalse(run.called)

    def test_nombre_invalide_ne_lance_rien(self):
        todo, run, _ = self.jouer("_ops_log_last_hours", ["x"])
        self.assertEqual(todo.execute.commandes, [])
        self.assertFalse(run.called)

    def test_position_dans_un_dossier_de_root(self):
        if os.geteuid() == 0:
            self.skipTest("root écrit partout")
        todo, run, confirm = self.jouer("_ops_log_since_last", ecrit=False)
        self.assertTrue(confirm.called)
        self.assertEqual(todo.execute.commandes, [])
        argv = run.call_args.args[0]
        self.assertEqual(argv[0], "sudo")
        self.assertIn("--since-last", argv)
        todo, run, _ = self.jouer(
            "_ops_log_since_last", ecrit=False, confirme=False
        )
        self.assertFalse(run.called)
        self.assertEqual(len(todo.execute.commandes), 1)

    def test_renvoi_sous_sudo_apres_accord(self):
        _todo, run, confirm = self.jouer("_ops_mail_retry", ["base_essai"])
        self.assertTrue(confirm.called)
        argv = run.call_args.args[0]
        self.assertEqual(argv[0], "sudo")
        self.assertTrue(argv[2].endswith("mail_retry.py"))
        self.assertEqual(argv[-2:], ["--db", "base_essai"])
        self.assertNotIn("--yes", argv)
        self.assertNotIn("capture_output", run.call_args.kwargs)
        self.assertNotIn("stdout", run.call_args.kwargs)
        todo, run, _ = self.jouer("_ops_mail_retry", [""], confirme=False)
        self.assertFalse(run.called)
        self.assertEqual(todo.execute.commandes, [])


class TestSanteDepuisLeMenu(unittest.TestCase):
    """Santé locale et préchauffage : lancés sans sudo, sudo proposé sur
    un code 2. Santé d'une URL : l'URL validée avant tout lancement, le
    domaine de courriel facultatif, jamais de sudo."""

    def jouer(self, methode, reponses=(), code=0, confirme=True):
        todo = TODO.__new__(TODO)
        todo.execute = FauxExecute(code)
        with (
            mock.patch("builtins.input", side_effect=list(reponses)),
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

    def test_sante_locale_et_prechauffage(self):
        for methode, attendu in (
            ("_ops_health_local", "health_check.py --local"),
            ("_ops_warmup_deep", "warmup_http.py --deep --local"),
        ):
            with self.subTest(methode=methode):
                todo, run, confirm = self.jouer(methode)
                (commande,) = todo.execute.commandes
                self.assertTrue(commande.endswith(attendu), commande)
                self.assertNotIn("sudo", commande)
                self.assertFalse(confirm.called)
                self.assertFalse(run.called)
                _todo, run, confirm = self.jouer(methode, code=2)
                self.assertTrue(confirm.called)
                argv = run.call_args.args[0]
                self.assertEqual(argv[0], "sudo")
                self.assertEqual(argv[-1], attendu.split()[-1])

    def test_sante_d_une_url(self):
        for reponses, attendu in (
            (["example.org", ""], "--url https://example.org"),
            (
                ["https://www.example.org/web", "example.org"],
                "--url https://www.example.org --mail-domain example.org",
            ),
        ):
            with self.subTest(reponses=reponses):
                todo, run, confirm = self.jouer("_ops_health_url", reponses)
                (commande,) = todo.execute.commandes
                self.assertIn("health_check.py", commande)
                self.assertTrue(commande.endswith(attendu), commande)
                self.assertFalse(run.called)
        todo, run, confirm = self.jouer(
            "_ops_health_url", ["example.org", ""], code=2
        )
        self.assertFalse(confirm.called)
        self.assertFalse(run.called)

    def test_url_ou_domaine_invalide_ne_lance_rien(self):
        for reponses in (
            ["ftp://example.org"],
            ["https://u:p@example.org"],
            [""],
            ["example.org", "-f/etc/passwd"],
            ["example.org", "a;b"],
        ):
            with self.subTest(reponses=reponses):
                todo, run, _ = self.jouer("_ops_health_url", reponses)
                self.assertEqual(todo.execute.commandes, [])
                self.assertFalse(run.called)


class TestDossierInscriptible(unittest.TestCase):
    """`_inscriptible` sur de vrais dossiers : celui qui existe, sinon son
    parent existant le plus proche."""

    def test_dossiers(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        racine = d.name
        self.assertTrue(ops_menu._inscriptible(racine))
        self.assertTrue(ops_menu._inscriptible(os.path.join(racine, "a", "b")))
        if os.geteuid() == 0:
            self.skipTest("root écrit partout")
        fermee = os.path.join(racine, "fermee")
        os.makedirs(fermee)
        os.chmod(fermee, 0o555)
        self.addCleanup(os.chmod, fermee, 0o755)
        self.assertFalse(ops_menu._inscriptible(fermee))
        self.assertFalse(ops_menu._inscriptible(os.path.join(fermee, "etat")))


class TestCodeDeSortieSousSudo(unittest.TestCase):
    """Un code autre que 0 ou 1 sous sudo est affiché : rien n'est
    capturé, c'est la seule trace d'un refus."""

    def test_code_affiche(self):
        todo = TODO.__new__(TODO)
        todo.execute = FauxExecute(0)
        for code, montre in ((0, False), (1, False), (2, True)):
            with self.subTest(code=code):
                with (
                    mock.patch("builtins.input", side_effect=[""]),
                    mock.patch(
                        "script.todo.ops_menu.click.confirm",
                        return_value=True,
                    ),
                    mock.patch(
                        "script.todo.ops_menu.subprocess.run",
                        return_value=mock.Mock(returncode=code),
                    ),
                    mock.patch("builtins.print") as affiche,
                ):
                    todo._ops_mail_retry()
                textes = [str(a.args[0]) for a in affiche.call_args_list]
                attendu = f"{ops_menu.t('The command ended with code')} {code}"
                self.assertEqual(
                    any(attendu in texte for texte in textes), montre
                )


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

    def test_choix_8_a_12(self):
        with mock.patch(
            "script.todo.ops_menu._inscriptible", return_value=True
        ):
            for choix, reponses, attendu in (
                ("8", [], "log_check.py --since-last"),
                ("9", [""], "log_check.py --last 24"),
                ("10", [""], "log_check.py --by-hour --days 7"),
                ("11", [""], "mail_retry.py --list"),
            ):
                with self.subTest(choix=choix):
                    todo, run = self.choisir(choix, reponses)
                    self.assertIn(attendu, todo.execute.commandes[0])
                    self.assertFalse(run.called)
        todo, run = self.choisir("12", [""])
        self.assertEqual(todo.execute.commandes, [])
        self.assertEqual(run.call_args.args[0][0], "sudo")
        self.assertTrue(run.call_args.args[0][2].endswith("mail_retry.py"))

    def test_choix_13_a_15(self):
        for choix, reponses, attendu in (
            ("13", [], "health_check.py --local"),
            ("14", ["example.org", ""], "--url https://example.org"),
            ("15", [], "warmup_http.py --deep --local"),
        ):
            with self.subTest(choix=choix):
                todo, run = self.choisir(choix, reponses)
                self.assertIn(attendu, todo.execute.commandes[0])
                self.assertFalse(run.called)

    def test_entree_17_du_menu_execute(self):
        source = (RACINE / "script" / "todo" / "todo.py").read_text()
        self.assertIn(
            '[17] {t("Production - Update, back up, restore and watch a'
            ' systemd instance")}',
            source,
        )
        self.assertIn("status = self.prompt_execute_production()", source)
        self.assertEqual(
            TODO._MENU_LABELS["prompt_execute_production"], "Production"
        )


if __name__ == "__main__":
    unittest.main()
