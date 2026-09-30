#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import ast
import builtins
import io
import json
import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, call, mock_open, patch

from script.todo import todo_i18n, ui
from script.todo.todo import (
    ANDROID_DIR,
    CONFIG_FILE,
    CONFIG_OVERRIDE_FILE,
    ENABLE_CRASH,
    ERROR_LOG_PATH,
    GRADLE_FILE,
    LOGO_ASCII_FILE,
    MOBILE_HOME_PATH,
    STRINGS_FILE,
    TODO,
    VENV_ERPLIBRE,
)
from script.todo.ui import port
from script.todo.version_manager import (
    INSTALLED_ODOO_VERSION_FILE,
    ODOO_VERSION_FILE,
    VERSION_DATA_FILE,
    get_odoo_version,
)


class TestTODOInit(unittest.TestCase):
    def test_initial_attributes(self):
        todo = TODO()
        self.assertIsNone(todo.dir_path)
        self.assertIsNone(todo.selected_file_path)
        self.assertIsNotNone(todo.config_file)
        self.assertIsNotNone(todo.execute)
        self.assertIsNotNone(todo.kdbx_manager)


class TestFillHelpInfo(unittest.TestCase):
    def setUp(self):
        self.todo = TODO()

    @patch("script.todo.todo.t")
    def test_basic_help_info(self, mock_t):
        mock_t.side_effect = lambda k: {
            "command": "Command:",
            "back": "Back",
        }.get(k, k)
        choices = [
            {"prompt_description": "Option A"},
            {"prompt_description": "Option B"},
        ]
        result = self.todo.fill_help_info(choices)
        self.assertIn("[1] Option A", result)
        self.assertIn("[2] Option B", result)
        self.assertIn("[0] Back", result)

    @patch("script.todo.todo.t")
    def test_with_prompt_description_key(self, mock_t):
        mock_t.side_effect = lambda k: {
            "command": "Command:",
            "back": "Back",
            "my_key": "Translated Description",
        }.get(k, k)
        choices = [
            {
                "prompt_description": "fallback",
                "prompt_description_key": "my_key",
            },
        ]
        result = self.todo.fill_help_info(choices)
        self.assertIn("[1] Translated Description", result)

    @patch("script.todo.todo.t")
    def test_empty_list(self, mock_t):
        mock_t.side_effect = lambda k: {
            "command": "Command:",
            "back": "Back",
        }.get(k, k)
        result = self.todo.fill_help_info([])
        self.assertIn("Command:", result)
        self.assertIn("[0] Back", result)
        self.assertNotIn("[1]", result)

    def test_the_header_writes_the_crumbs_of_the_navigator(self):
        # L'en-tête écrit le fil d'Ariane que tient le navigateur, puis la
        # ligne d'état, et fait du fil la clé de télémétrie du menu ; hors
        # de tout menu, il n'écrit ni fil ni clé.
        from script.todo.ui import navigator

        with patch("script.todo.todo_telemetry.record") as record:
            self.assertNotIn("📍", self.todo._menu_header())
            with navigator.crumbs_at(["TODO", "Forged"]):
                header = self.todo._menu_header("forged state")
        self.assertEqual(
            header.split("\n")[:2], ["📍 TODO › Forged", "forged state"]
        )
        record.assert_called_once_with("TODO › Forged")


class TestGetOdooVersion(unittest.TestCase):
    def test_reads_version_data(self):
        version_data = {
            "odoo18.0_python3.12.10": {
                "odoo_version": "18.0",
                "python_version": "3.12.10",
                "default": True,
                "is_deprecated": False,
            },
            "odoo16.0_python3.10.18": {
                "odoo_version": "16.0",
                "python_version": "3.10.18",
                "default": False,
                "is_deprecated": False,
            },
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            version_file = os.path.join(tmpdir, "version.json")
            with open(version_file, "w") as f:
                json.dump(version_data, f)

            odoo_version_file = os.path.join(tmpdir, ".odoo-version")
            with open(odoo_version_file, "w") as f:
                f.write("18.0")

            with (
                patch(
                    "script.todo.version_manager.VERSION_DATA_FILE",
                    version_file,
                ),
                patch(
                    "script.todo.version_manager.INSTALLED_ODOO_VERSION_FILE",
                    os.path.join(tmpdir, "nonexistent.txt"),
                ),
                patch(
                    "script.todo.version_manager.ODOO_VERSION_FILE",
                    odoo_version_file,
                ),
            ):
                versions, installed, odoo_current = get_odoo_version()

            self.assertEqual(len(versions), 2)
            self.assertEqual(odoo_current, "odoo18.0")
            # Check erplibre_version was added
            names = [v["erplibre_version"] for v in versions]
            self.assertIn("odoo18.0_python3.12.10", names)
            self.assertIn("odoo16.0_python3.10.18", names)

    def test_installed_versions_read(self):
        version_data = {
            "odoo18.0_python3.12.10": {
                "odoo_version": "18.0",
                "python_version": "3.12.10",
                "default": True,
                "is_deprecated": False,
            },
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            version_file = os.path.join(tmpdir, "version.json")
            with open(version_file, "w") as f:
                json.dump(version_data, f)

            installed_file = os.path.join(tmpdir, "installed.txt")
            with open(installed_file, "w") as f:
                f.write("odoo18.0\nodoo16.0\n")

            with (
                patch(
                    "script.todo.version_manager.VERSION_DATA_FILE",
                    version_file,
                ),
                patch(
                    "script.todo.version_manager.INSTALLED_ODOO_VERSION_FILE",
                    installed_file,
                ),
                patch(
                    "script.todo.version_manager.ODOO_VERSION_FILE",
                    os.path.join(tmpdir, "nonexistent"),
                ),
            ):
                versions, installed, odoo_current = get_odoo_version()

            self.assertEqual(installed, ["odoo16.0", "odoo18.0"])
            self.assertIsNone(odoo_current)

    def test_no_version_data_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            version_file = os.path.join(tmpdir, "empty.json")
            with open(version_file, "w") as f:
                json.dump({}, f)

            with patch(
                "script.todo.version_manager.VERSION_DATA_FILE", version_file
            ):
                with self.assertRaises(Exception):
                    get_odoo_version()


class TestOnDirSelected(unittest.TestCase):
    @patch("script.todo.todo.todo_file_browser", create=True)
    def test_sets_dir_path(self, mock_browser):
        todo = TODO()
        todo.on_dir_selected("/some/path")
        self.assertEqual(todo.dir_path, "/some/path")


class TestRestartScript(unittest.TestCase):
    """La relance de TODO, dans un répertoire temporaire qui porte un venv
    vide : os.execve et os.execv sont des doubles, rien ne remplace le
    processus du test."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(tmp.name)
        os.makedirs(os.path.join(VENV_ERPLIBRE, "bin"))

    def restart(self, argv):
        """`restart_script` sous `argv` ; rend les doubles d'os.execve et
        d'os.execv. `self.flushed` dit, à chaque appel d'os.execve, si la
        sortie standard avait été vidée depuis sa dernière écriture."""
        todo = TODO.__new__(TODO)  # sans __init__, qui lit le checkout
        env = {"PATH": "/usr/bin", "PYTHONHOME": "/forged"}
        out, self.flushed = MagicMock(), []
        out.write.side_effect = lambda text: out.flush.reset_mock()
        with (
            patch.object(sys, "argv", argv),
            patch.dict(os.environ, env),
            patch.object(os, "execve") as execve,
            patch.object(os, "execv") as execv,
            redirect_stdout(out),
        ):
            execve.side_effect = lambda *a: self.flushed.append(
                out.flush.called
            )
            todo.restart_script("forged error")
        return execve, execv

    def test_the_argv_list_is_passed_as_is_without_a_shell(self):
        argv = ["script/todo/todo.py", "--name", "a b; touch forged", "$HOME"]
        execve, execv = self.restart(argv)
        execv.assert_not_called()
        venv = os.path.abspath(VENV_ERPLIBRE)
        python = os.path.join(venv, "bin", "python")
        [(path, args, env)] = [call.args for call in execve.call_args_list]
        self.assertEqual((path, args), (python, [python, *argv]))
        self.assertEqual(env["VIRTUAL_ENV"], venv)
        self.assertEqual(env["PATH"], f"{venv}/bin{os.pathsep}/usr/bin")
        self.assertNotIn("PYTHONHOME", env)
        # Ce qui a été imprimé part avant que le processus ne soit remplacé.
        self.assertEqual(self.flushed, [True])
        with open(ERROR_LOG_PATH, encoding="utf-8") as error:
            self.assertEqual(error.read(), "forged error")

    def test_an_error_already_logged_restarts_nothing(self):
        # Une erreur qui revient à chaque démarrage ne boucle pas.
        with open(ERROR_LOG_PATH, "w", encoding="utf-8") as error:
            error.write("first error")
        execve, execv = self.restart(["script/todo/todo.py"])
        execve.assert_not_called()
        execv.assert_not_called()


class TestExecuteFromConfiguration(unittest.TestCase):
    def test_with_command(self):
        todo = TODO()
        todo.execute = MagicMock()
        dct = {"command": "./run.sh"}
        todo.execute_from_configuration(dct)
        todo.execute.exec_command_live.assert_called()

    def test_every_command_entry_of_the_real_config_is_reachable(self):
        """Le dict synthétique du test précédent ne suffisait pas.

        `4fc15c3` a renommé la clé cherchée par le code en « Command: »,
        le libellé affiché. Plus aucune entrée de todo.json ne
        correspondait, et « Open ERPLibre with TODO 🤖 » ne faisait plus
        rien — sans erreur, le `if` étant simplement faux. Seule la VRAIE
        configuration relie les deux côtés.
        """
        with open(CONFIG_FILE) as fh:
            config = json.load(fh)

        entrees = []

        def parcourir(noeud):
            if isinstance(noeud, dict):
                if "command" in noeud:
                    entrees.append(noeud)
                for valeur in noeud.values():
                    parcourir(valeur)
            elif isinstance(noeud, list):
                for element in noeud:
                    parcourir(element)

        parcourir(config)
        self.assertTrue(entrees, "todo.json n'a plus d'entrée `command`")

        for entree in entrees:
            todo = TODO()
            todo.execute = MagicMock()
            todo.execute_from_configuration(entree)
            self.assertTrue(
                todo.execute.exec_command_live.called,
                f"entrée ignorée en silence : {entree.get('command')}",
            )

    def test_with_makefile_cmd(self):
        todo = TODO()
        todo.execute = MagicMock()
        todo.execute.exec_command_live.return_value = 0
        dct = {"makefile_cmd": "run_test"}
        todo.execute_from_configuration(dct)
        call_args = todo.execute.exec_command_live.call_args
        self.assertIn("make run_test", call_args[0][0])

    def test_makefile_cmd_ignored_when_flag(self):
        todo = TODO()
        todo.execute = MagicMock()
        dct = {"makefile_cmd": "run_test"}
        todo.execute_from_configuration(dct, ignore_makefile=True)
        todo.execute.exec_command_live.assert_not_called()

    def test_makefile_error_stops_execution(self):
        # La cible make échoue : la commande bash de l'instance ne part pas.
        todo = TODO()
        todo.execute = MagicMock()
        todo.execute.exec_command_live.return_value = 1
        dct = {"makefile_cmd": "broken", "bash_command": "forged_command"}
        todo.execute_from_configuration(dct)
        self.assertEqual(todo.execute.exec_command_live.call_count, 1)

    def test_run_db_opens_only_a_database_the_instance_names(self):
        # Sans « database », run.sh recevrait « -d None » : l'instance ne
        # lance que ses commandes, et le dit.
        todo = TODO()
        todo.execute = MagicMock()
        todo.prompt_execute_selenium_and_run_db = MagicMock()
        with redirect_stdout(io.StringIO()) as out:
            todo.execute_from_configuration(
                {"bash_command": "forged_one"}, exec_run_db=True
            )
            todo.execute_from_configuration(
                {"database": "forged"}, exec_run_db=True
            )
        opened = todo.prompt_execute_selenium_and_run_db.call_args_list
        self.assertEqual([c.args[0] for c in opened], ["forged"])
        todo.execute.exec_command_live.assert_called_once_with(
            "forged_one", source_erplibre=False
        )
        self.assertIn(
            todo_i18n.t(
                "This instance names no database: Odoo is not started."
            ),
            out.getvalue(),
        )


class TestConstants(unittest.TestCase):
    def test_config_file_path(self):
        self.assertEqual(CONFIG_FILE, "./script/todo/todo.json")

    def test_config_override_path(self):
        self.assertEqual(CONFIG_OVERRIDE_FILE, "./private/todo/todo.json")

    def test_logo_path(self):
        self.assertEqual(LOGO_ASCII_FILE, "./script/todo/logo_ascii.txt")

    def test_venv_erplibre(self):
        self.assertEqual(VENV_ERPLIBRE, ".venv.erplibre")

    def test_file_error_path(self):
        self.assertEqual(ERROR_LOG_PATH, ".erplibre.error.txt")

    def test_version_data_file(self):
        self.assertEqual(
            VERSION_DATA_FILE,
            os.path.join("conf", "supported_version_erplibre.json"),
        )

    def test_mobile_paths(self):
        self.assertEqual(ANDROID_DIR, "android")
        self.assertIn("mobile", MOBILE_HOME_PATH)


class TestDeployGitServer(unittest.TestCase):
    def test_local_mode(self):
        todo = TODO()
        todo.execute = MagicMock()
        todo._deploy_git_server(production_ready=False, action="init")
        cmd = todo.execute.exec_command_live.call_args[0][0]
        self.assertIn("--action init", cmd)
        self.assertNotIn("--production-ready", cmd)

    def test_production_mode(self):
        todo = TODO()
        todo.execute = MagicMock()
        todo._deploy_git_server(production_ready=True, action="all")
        cmd = todo.execute.exec_command_live.call_args[0][0]
        self.assertIn("--production-ready", cmd)
        self.assertIn("--action all", cmd)


class TestProcessKillGitDaemon(unittest.TestCase):
    def test_calls_pkill(self):
        todo = TODO()
        todo.execute = MagicMock()
        todo.process_kill_git_daemon()
        cmd = todo.execute.exec_command_live.call_args[0][0]
        self.assertIn("pkill", cmd)
        self.assertIn("git daemon", cmd)


class TestExecuteUnitTests(unittest.TestCase):
    def test_success_path(self):
        todo = TODO()
        todo.execute = MagicMock()
        todo.execute.exec_command_live.return_value = (0, ["OK"])
        with patch("builtins.print") as mock_print:
            todo.execute_unit_tests()
        cmd = todo.execute.exec_command_live.call_args[0][0]
        self.assertIn("unittest discover", cmd)

    def test_failure_path(self):
        todo = TODO()
        todo.execute = MagicMock()
        todo.execute.exec_command_live.return_value = (1, ["FAIL"])
        with patch("builtins.print") as mock_print:
            todo.execute_unit_tests()
        # Verify it was called - error handling path

    def test_stdout_is_unbuffered_so_the_verdict_lands_last(self):
        """Le verdict s'affiche en dernier : unittest l'écrit sur stderr et
        les tests impriment sur stdout, qui, tamponné et capturé avec
        stderr, se déverserait après le « OK ». `python -u` ne tamponne
        pas stdout."""
        todo = TODO()
        todo.execute = MagicMock()
        todo.execute.exec_command_live.return_value = (0, ["OK"])
        with patch("builtins.print"):
            todo.execute_unit_tests()
        cmd = todo.execute.exec_command_live.call_args[0][0]
        self.assertIn("python -u -m unittest", cmd)

    def test_the_pattern_reaches_the_command(self):
        todo = TODO()
        todo.execute = MagicMock()
        todo.execute.exec_command_live.return_value = (0, ["OK"])
        with patch("builtins.print"):
            todo.execute_unit_tests("test_mail*.py")
        cmd = todo.execute.exec_command_live.call_args[0][0]
        self.assertIn("-p 'test_mail*.py'", cmd)

    def test_the_default_pattern_is_still_the_whole_suite(self):
        """La signature a gagné un paramètre : l'entrée [3] ne doit pas
        s'être mise à ne lancer qu'un sous-ensemble en silence."""
        todo = TODO()
        todo.execute = MagicMock()
        todo.execute.exec_command_live.return_value = (0, ["OK"])
        with patch("builtins.print"):
            todo.execute_unit_tests()
        cmd = todo.execute.exec_command_live.call_args[0][0]
        self.assertIn("-p 'test_*.py'", cmd)


class TestTestMenuDispatch(unittest.TestCase):
    """Le câblage des entrées, pas leur contenu.

    Un `elif` qui pointe le mauvais motif lancerait une suite verte sans
    rien tester de ce que l'utilisateur a demandé — panne silencieuse que
    seul ce test attrape.
    """

    def _choose(self, entry):
        todo = TODO()
        with (
            patch.object(todo, "execute_unit_tests") as mock_run,
            patch.object(todo, "execute_test_module"),
            patch("click.prompt", side_effect=[entry, "0"]),
            patch("builtins.print"),
        ):
            todo.prompt_execute_test()
        return mock_run

    # Le motif est nommé, comme dans l'arbre de télémétrie, que [4] › [1]
    # rejoue par ses kwargs.
    def test_entry_4_runs_the_mail_tests(self):
        self.assertEqual(
            self._choose("4").call_args, call(pattern="test_mail*.py")
        )

    def test_entry_5_runs_the_analyse_tests(self):
        self.assertEqual(
            self._choose("5").call_args, call(pattern="test_analyse*.py")
        )

    def test_entry_3_still_runs_everything(self):
        self.assertEqual(self._choose("3").call_args, call())


class TestKdbxGetExtraCommandUser(unittest.TestCase):
    """La fonction rend (fragments, variables d'environnement).

    Le mot de passe ne doit JAMAIS revenir dans les fragments : ils
    deviennent une ligne de commande, que tout utilisateur de la machine
    peut lire dans /proc/<pid>/cmdline. Seul le NOM d'une variable y a sa
    place, et c'est ce que le dernier test verrouille.
    """

    def test_empty_kdbx_key(self):
        todo = TODO()
        result = todo.kdbx_manager.get_extra_command_user("")
        self.assertEqual(result, ("", {}))

    def test_none_kdbx_key(self):
        todo = TODO()
        result = todo.kdbx_manager.get_extra_command_user(None)
        self.assertEqual(result, ("", {}))

    def test_kdbx_not_available(self):
        todo = TODO()
        todo.kdbx_manager.get_kdbx = MagicMock(return_value=None)
        result = todo.kdbx_manager.get_extra_command_user("some_key")
        self.assertEqual(result, ("", {}))

    def test_password_never_reaches_the_command_line(self):
        todo = TODO()
        entry = MagicMock(username="odoo", password="s3cr3t")
        kp = MagicMock()
        kp.find_entries_by_title = MagicMock(return_value=entry)
        todo.kdbx_manager.get_kdbx = MagicMock(return_value=kp)
        fragment, env = todo.kdbx_manager.get_extra_command_user("une_cle")
        self.assertNotIn("s3cr3t", fragment)
        self.assertIn(
            "--default_password_auth_env EL_WEB_LOGIN_PWD_0", fragment
        )
        self.assertEqual(env, {"EL_WEB_LOGIN_PWD_0": "s3cr3t"})


class TestSetupClaudeCommit(unittest.TestCase):
    """Le déploiement d'une commande `/…` dans ~/.claude/commands.

    La méthode a été généralisée depuis : elle prend le nom de la commande
    et son gabarit, et quand la cible existe elle DEMANDE confirmation au
    lieu de passer son tour. Le test ne détournait pas `input` — il aurait
    bloqué si l'appel n'avait pas échoué avant.
    """

    def test_existing_file_and_refusal_writes_nothing(self):
        todo = TODO()
        with (
            patch("os.path.exists", return_value=True),
            patch("builtins.input", return_value="n"),
            patch("builtins.open") as mock_open,
            patch("os.makedirs") as mock_makedirs,
            patch("builtins.print"),
        ):
            todo._setup_claude_command(
                "commit", "template_claude_commands_commit.md"
            )
        # Un refus doit sortir AVANT toute écriture : ni lecture du gabarit,
        # ni création du dossier. Sans ces deux assertions, le test passait
        # aussi bien si la méthode écrasait le fichier.
        mock_open.assert_not_called()
        mock_makedirs.assert_not_called()

    def test_existing_file_and_acceptance_writes(self):
        """Le pendant : sans lui, la méthode pourrait ne JAMAIS écrire et
        le test ci-dessus resterait vert."""
        todo = TODO()
        with (
            patch("os.path.exists", return_value=True),
            patch("builtins.input", return_value="y"),
            patch("builtins.open", mock_open(read_data="gabarit")),
            patch("os.makedirs") as mock_makedirs,
            patch("builtins.print"),
        ):
            todo._setup_claude_command(
                "commit", "template_claude_commands_commit.md"
            )
        mock_makedirs.assert_called_once()


class TestClaudeCommandTemplates(unittest.TestCase):
    """Chaque commande proposée par le menu doit avoir son gabarit.

    Un nom de gabarit fautif ne se voit qu'à l'exécution, au moment où le
    déploiement échoue devant l'utilisateur : rien ne relie le littéral passé
    à `_setup_claude_command` au fichier de `conf/`.
    """

    @staticmethod
    def _deployed_pairs():
        """(commande, gabarit) de chaque déploiement de Claude configs :
        les `kwargs` des entrées déclarées qui mènent à
        `_setup_claude_command`, puis les appels de todo.py à cette
        méthode, leurs deux premiers arguments écrits en position ou
        nommés `command_name` et `template_filename`."""
        import ast

        from script.todo.menus import git as menus_git

        pairs = [
            (e.kwargs["command_name"], e.kwargs["template_filename"])
            for e in menus_git.CLAUDE_CONFIGS.entries
            if e.action == "_setup_claude_command"
        ]
        source = Path("script/todo/todo.py").read_text(encoding="utf-8")
        for node in ast.walk(ast.parse(source)):
            if not isinstance(node, ast.Call):
                continue
            attr = getattr(node.func, "attr", None)
            if attr != "_setup_claude_command":
                continue
            named = {k.arg: k.value for k in node.keywords}
            args = [
                node.args[i] if i < len(node.args) else named.get(name)
                for i, name in enumerate(("command_name", "template_filename"))
            ]
            # Les deux sont des littéraux, sans quoi le test ne peut rien
            # affirmer.
            values = [
                a.value
                for a in args
                if isinstance(a, ast.Constant) and isinstance(a.value, str)
            ]
            if len(values) == 2:
                pairs.append(tuple(values))
        return pairs

    @staticmethod
    def _deployed_templates():
        """Les gabarits que nomment les déploiements de Claude configs."""
        pairs = TestClaudeCommandTemplates._deployed_pairs()
        return [template for _, template in pairs]

    def test_every_menu_template_exists(self):
        templates = self._deployed_templates()
        self.assertGreaterEqual(len(templates), 4, templates)
        for name in templates:
            with self.subTest(template=name):
                self.assertTrue(
                    os.path.isfile(os.path.join("conf", name)),
                    f"conf/{name} est nommé par le menu et n'existe pas",
                )

    def test_every_template_declares_its_own_name(self):
        """Le `name:` du frontmatter donne le nom de la commande `/…` ; un
        gabarit qui en déclare un autre déploie un fichier dont le contenu
        parle d'une commande différente."""
        pairs = self._deployed_pairs()
        self.assertTrue(pairs)
        for command, template in pairs:
            with self.subTest(command=command):
                text = Path("conf", template).read_text(encoding="utf-8")
                self.assertIn(f"name: {command}\n", text)


class TestListeCommandesClaude(unittest.TestCase):
    """La liste des commandes `/…` compare chaque gabarit à sa copie.

    Elle montre les commandes non installées, les copies périmées avec leur
    compte de lignes, et celles qui ne viennent pas d'ERPLibre ; elle propose
    le diff puis le redéploiement, qui garde l'identité git de la copie.
    """

    IDENTITE = 'user.name="Nom Inventé" -c user.email="nom@exemple.invalid"'

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dossier = self._tmp.name
        self.todo = TODO()
        self.todo._CLAUDE_COMMANDS_DIR = self.dossier
        gabarit = Path(
            "conf", TODO._CLAUDE_COMMAND_TEMPLATES["commit"]
        ).read_text(encoding="utf-8")
        self.gabarit_commit = gabarit
        personnalise = gabarit.replace(
            'user.name="Your Name" -c user.email="your@email.com"',
            self.IDENTITE,
        )
        # /commit à jour hors identité ; /todo_plan_max périmée d'une ligne ;
        # /perso hors ERPLibre ; les autres absentes.
        self._ecrire("commit", personnalise)
        plan = Path(
            "conf", TODO._CLAUDE_COMMAND_TEMPLATES["todo_plan_max"]
        ).read_text(encoding="utf-8")
        self._ecrire("todo_plan_max", plan + "ligne ajoutée à la main\n")
        self._ecrire("perso", "une commande à soi\n")

    def tearDown(self):
        self._tmp.cleanup()

    def _ecrire(self, nom, texte):
        Path(self.dossier, f"{nom}.md").write_text(texte, encoding="utf-8")

    def _lister(self, *reponses):
        sortie = io.StringIO()
        with (
            patch("builtins.input", side_effect=list(reponses)),
            patch("sys.stdout", sortie),
        ):
            self.todo._list_claude_commands()
        return sortie.getvalue()

    def _ligne(self, sortie, nom):
        return next(x for x in sortie.splitlines() if f"/{nom} " in x)

    def test_etat_de_chaque_commande(self):
        sortie = self._lister("n", "n")
        self.assertIn(todo_i18n.t("up to date"), self._ligne(sortie, "commit"))
        self.assertIn("(+0 -1)", self._ligne(sortie, "todo_plan_max"))
        self.assertIn(
            todo_i18n.t("command not installed"),
            self._ligne(sortie, "git_prepare_merge"),
        )
        self.assertIn(
            todo_i18n.t("not from ERPLibre"), self._ligne(sortie, "perso")
        )

    def test_le_diff_montre_ce_que_le_redeploiement_retire(self):
        sortie = self._lister("o", "n")
        self.assertIn("-ligne ajoutée à la main", sortie)

    def test_un_refus_n_ecrit_rien(self):
        avant = Path(self.dossier, "todo_plan_max.md").read_text()
        self._lister("n", "n")
        apres = Path(self.dossier, "todo_plan_max.md").read_text()
        self.assertEqual(avant, apres)

    def test_le_redeploiement_remet_le_gabarit(self):
        self._lister("n", "o")
        attendu = Path(
            "conf", TODO._CLAUDE_COMMAND_TEMPLATES["todo_plan_max"]
        ).read_text(encoding="utf-8")
        self.assertEqual(
            attendu, Path(self.dossier, "todo_plan_max.md").read_text()
        )

    def test_le_redeploiement_garde_l_identite_git(self):
        self._ecrire(
            "commit",
            self.gabarit_commit.replace(
                'user.name="Your Name" -c user.email="your@email.com"',
                self.IDENTITE,
            )
            + "vieille ligne\n",
        )
        self._lister("n", "o")
        texte = Path(self.dossier, "commit.md").read_text(encoding="utf-8")
        self.assertIn(self.IDENTITE, texte)
        self.assertNotIn("vieille ligne", texte)
        self.assertNotIn("Your Name", texte)

    def test_tout_a_jour_ne_pose_aucune_question(self):
        for nom in ("todo_plan_max", "perso"):
            os.remove(Path(self.dossier, f"{nom}.md"))
        with patch("builtins.input") as question:
            with patch("sys.stdout", io.StringIO()):
                self.todo._list_claude_commands()
        question.assert_not_called()

    def test_la_table_couvre_les_gabarits_du_menu(self):
        """Une commande ajoutée au menu sans entrée dans la table resterait
        invisible à la liste et à l'écran de contexte."""
        nommes = set(TestClaudeCommandTemplates._deployed_templates())
        self.assertEqual(nommes, set(TODO._CLAUDE_COMMAND_TEMPLATES.values()))


class TestClaudeAddAutomation(unittest.TestCase):
    """GPT code › Add an automation : la commande s'écrit dans une liste
    `<section>_from_makefile` de todo.json qu'un menu lit, et nulle part
    ailleurs. todo.json est une copie temporaire."""

    def setUp(self):
        # L'ajout écrit le todo.json voisin de todo.py, que `add` détourne
        # vers une copie : le vrai, suivi par git, reste tel quel.
        import script.todo.todo as module

        real = Path(module.__file__).with_name("todo.json")
        before = real.read_bytes()
        self.addCleanup(
            lambda: self.assertTrue(real.read_bytes() == before, real)
        )

    def add(self, *answers):
        """(todo.json après l'ajout, texte affiché) quand l'ajout reçoit
        `answers`, sur un todo.json qui n'a que `git_from_makefile`."""
        import script.todo.todo as module

        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "todo.json"
            config.write_text('{"git_from_makefile": []}\n')
            with (
                patch.object(module, "__file__", str(Path(tmp) / "todo.py")),
                patch("builtins.input", side_effect=answers),
                redirect_stdout(io.StringIO()) as out,
            ):
                TODO()._claude_add_automation()
            return json.loads(config.read_text()), out.getvalue()

    def test_only_a_section_a_menu_reads_is_written(self):
        # Sans réponse, la section est git ; config, network et process
        # n'ont aucun menu.
        config, _ = self.add("Forged", "forged_command", "")
        added = {
            "prompt_description": "Forged",
            "bash_command": "forged_command",
        }
        self.assertEqual(config, {"git_from_makefile": [added]})
        refused = todo_i18n.t("No menu reads this section: ")
        for section in ("config", "network", "process", "forged"):
            with self.subTest(section=section):
                config, out = self.add("Forged", "forged_command", section)
                self.assertEqual(config, {"git_from_makefile": []})
                self.assertIn(refused + section, out)

    def test_each_offered_section_is_read_by_a_menu(self):
        # Un menu écrit à la main (get_config) ou déclaré (FromConfig)
        # nomme sa liste en littéral, premier argument de l'appel, sous
        # script/todo ; le même texte dans un commentaire ou ailleurs ne
        # compte pas.
        root = Path(__file__).resolve().parent.parent / "script" / "todo"
        read = set()
        for path in root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Call) and node.args):
                    continue
                name = getattr(node.func, "id", None) or getattr(
                    node.func, "attr", None
                )
                first = node.args[0]
                if name in ("get_config", "FromConfig") and isinstance(
                    first, ast.Constant
                ):
                    read.add(first.value)
        for section in TODO._AUTOMATION_SECTIONS:
            with self.subTest(section=section):
                self.assertIn(f"{section}_from_makefile", read)

    def test_the_question_names_each_offered_section(self):
        # Dans chaque langue, la question de la section nomme chaque
        # section de _AUTOMATION_SECTIONS ; « forged » est refusée avant
        # toute lecture de todo.json.
        import script.todo.todo as module

        with (
            patch.object(module, "t", side_effect=lambda key: key),
            patch(
                "builtins.input",
                side_effect=["Forged", "forged_command", "forged"],
            ) as question,
            redirect_stdout(io.StringIO()),
        ):
            TODO()._claude_add_automation()
        key = question.call_args_list[2].args[0]
        for lang in todo_i18n.LANGUAGES:
            text = todo_i18n.TRANSLATIONS[key][lang]
            for section in TODO._AUTOMATION_SECTIONS:
                with self.subTest(lang=lang, section=section):
                    self.assertRegex(text, rf"\b{section}\b")


class TestGitAddRemote(unittest.TestCase):
    """Git › Add a remote : le nom et l'adresse tapés arrivent à git tels
    quels, chacun en un argument ; la commande est un double."""

    def answer(self, answers, status=0):
        """(commande lancée, texte affiché) quand l'ajout reçoit
        `answers` et que la commande rend `status`."""
        todo = TODO()
        todo.execute = MagicMock()
        todo.execute.exec_command_live.return_value = status
        with (
            patch("builtins.input", side_effect=answers),
            redirect_stdout(io.StringIO()) as out,
        ):
            todo._git_add_remote()
        command = todo.execute.exec_command_live.call_args.args[0]
        return command, out.getvalue()

    def test_the_name_and_the_address_reach_git_as_typed(self):
        # Un blanc ne coupe pas une réponse, un « ; » ne lance rien après
        # git, et un nom qui commence par « - » suit « -- », qui termine
        # les options de git ; sans nom, le remote s'appelle localhost.
        name, address = "forged name", "/forged dir/repo.git; forged"
        for answers, arguments in (
            ([name, address], [name, address]),
            (["", "forged-address"], ["localhost", "forged-address"]),
            (["-x", "forged-address"], ["-x", "forged-address"]),
        ):
            with self.subTest(answers=answers):
                command, _ = self.answer(answers)
                self.assertEqual(
                    shlex.split(command),
                    ["git", "remote", "add", "--", *arguments],
                )

    def test_a_failure_of_git_is_reported(self):
        # La commande rend son code sans lever : un remote qui existe déjà
        # fait sortir git en 3, et rien n'a été ajouté.
        _, out = self.answer(["forged", "forged-address"], status=3)
        self.assertNotIn(todo_i18n.t("Remote added successfully!"), out)
        self.assertIn(f"{todo_i18n.t('Error adding remote: ')}3", out)
        _, out = self.answer(["forged", "forged-address"])
        self.assertIn(todo_i18n.t("Remote added successfully!"), out)


class TestClaudePlugins(unittest.TestCase):
    """Le menu des plugins Claude Code.

    Ce qui est vérifié ici ne se voit pas à la lecture : la frontière de mot
    qui distingue deux noms dont l'un contient l'autre, le refus qui n'installe
    rien, et l'absence de l'exécutable, qui doit se dire au lieu de passer pour
    un échec de la commande.
    """

    def test_absent_binary_reports_without_executing(self):
        todo = TODO()
        todo.execute = MagicMock()
        with (
            patch("script.todo.todo.shutil.which", return_value=None),
            patch("builtins.print"),
        ):
            self.assertEqual(todo._claude_plugin_exec("list"), 1)
            self.assertEqual(
                todo._claude_plugin_exec("list", capture=True), (1, [])
            )
        # La forme du retour suit l'appelant : un appelant qui déballe un
        # couple ne doit pas recevoir un entier nu.
        todo.execute.exec_command_live.assert_not_called()

    def test_installed_name_matches_on_word_boundary(self):
        todo = TODO()
        # Chaque cas négatif CONTIENT le nom cherché comme sous-chaîne : une
        # recherche naïve les déclarerait tous posés.
        cases = [
            (["code-review-toolkit@market  v1.0"], "code-review", False),
            (["my-superpowers@market  v1.0"], "superpowers", False),
            (["superpowers2@market  v1.0"], "superpowers", False),
            (["code-review@market  v1.0"], "code-review", True),
            (["No plugins installed."], "superpowers", False),
            (["superpowers@market (enabled)"], "superpowers", True),
        ]
        for lines, name, expected in cases:
            with self.subTest(name=name, lines=lines):
                with patch.object(
                    todo, "_claude_plugin_exec", return_value=(0, lines)
                ):
                    self.assertIs(
                        todo._claude_plugin_is_installed(name), expected
                    )

    def test_unreadable_list_reports_not_installed(self):
        """Un code de sortie non nul ne vaut pas « absent » par hasard : la
        réinstallation qui suit est idempotente, l'inverse effacerait."""
        todo = TODO()
        with patch.object(
            todo, "_claude_plugin_exec", return_value=(2, ["boom"])
        ):
            self.assertFalse(todo._claude_plugin_is_installed("superpowers"))

    def test_refusing_the_preferred_list_installs_nothing(self):
        todo = TODO()
        with (
            patch("builtins.input", return_value="n"),
            patch.object(todo, "_claude_plugin_exec") as mock_exec,
            patch("builtins.print"),
        ):
            todo._claude_install_preferred_plugins()
        mock_exec.assert_not_called()

    def test_accepting_installs_only_what_is_missing(self):
        todo = TODO()
        with (
            patch("builtins.input", return_value="y"),
            patch.object(todo, "_claude_plugin_exec") as mock_exec,
            patch.object(
                todo,
                "_claude_plugin_is_installed",
                side_effect=lambda name: name == "pyright-lsp",
            ),
            patch("builtins.print"),
        ):
            todo._claude_install_preferred_plugins()
        called = [call.args[0] for call in mock_exec.call_args_list]
        # « -y » est obligatoire : la sortie de TODO est un tuyau, et la CLI
        # refuse sans lui toute installation qui exécute une commande.
        self.assertEqual(
            called,
            [
                "install superpowers -y",
                "install claude-security -y",
                "install skill-creator -y",
            ],
        )

    def test_catalog_skips_an_unreadable_manifest(self):
        todo = TODO()
        with tempfile.TemporaryDirectory() as tmp:
            for name, body in (
                ("good", '{"plugins":[{"name":"a","description":"d"}]}'),
                ("broken", "{not json"),
            ):
                folder = os.path.join(tmp, name, ".claude-plugin")
                os.makedirs(folder)
                with open(
                    os.path.join(folder, "marketplace.json"), "w"
                ) as handle:
                    handle.write(body)
            with patch.object(TODO, "_CLAUDE_MARKETPLACES_DIR", tmp):
                catalog = todo._claude_marketplace_catalog()
        self.assertEqual(catalog, [("a", "good", "d")])

    def test_catalog_is_empty_without_any_marketplace(self):
        todo = TODO()
        with patch.object(
            TODO, "_CLAUDE_MARKETPLACES_DIR", "/nonexistent-marketplaces"
        ):
            self.assertEqual(todo._claude_marketplace_catalog(), [])

    def test_search_matches_name_and_description(self):
        todo = TODO()
        catalog = [
            ("pyright-lsp", "official", "Python language server"),
            ("mongodb", "official", "Document database"),
        ]
        with (
            patch.object(
                todo, "_claude_marketplace_catalog", return_value=catalog
            ),
            patch("builtins.input", return_value="python"),
            patch("builtins.print") as mock_print,
        ):
            todo._claude_plugin_search()
        printed = " ".join(
            str(call.args[0]) for call in mock_print.call_args_list
        )
        self.assertIn("pyright-lsp", printed)
        self.assertNotIn("mongodb", printed)


class TestSelectDatabase(unittest.TestCase):
    @patch("script.todo.database_manager.click")
    def test_select_database_returns_name(self, mock_click):
        todo = TODO()
        todo.db_manager._execute = MagicMock()
        todo.db_manager._execute.exec_command_live.return_value = (
            0,
            ["db_test", "db_prod"],
        )
        mock_click.prompt.return_value = "1"
        result = todo.db_manager.select_database()
        self.assertEqual(result, "db_test")

    @patch("script.todo.database_manager.click")
    def test_select_database_returns_false_on_zero(self, mock_click):
        todo = TODO()
        todo.db_manager._execute = MagicMock()
        todo.db_manager._execute.exec_command_live.return_value = (
            0,
            ["db_test"],
        )
        mock_click.prompt.return_value = "0"
        result = todo.db_manager.select_database()
        self.assertFalse(result)


class TestRestoreFromDatabase(unittest.TestCase):
    """Database › Restore from backup : [1] demande le nom du fichier sous
    image_db par `ui.ask`, auquel répond un ScriptedPort ; les autres
    questions passent par `input`. Les commandes sont doublées."""

    def restore(self, answers, file_name):
        """(commandes lancées, port qui a répondu, double d'`input`) quand
        `input` reçoit `answers` et la question du nom `file_name`."""
        todo = TODO()
        todo.db_manager._execute = MagicMock()
        todo.db_manager._execute.exec_command_live.return_value = (0, [])
        scripted = port.ScriptedPort([file_name])
        with (
            ui.bind(scripted),
            patch("builtins.input", side_effect=answers) as asked,
            redirect_stdout(io.StringIO()),
        ):
            todo.db_manager.restore_from_database()
        live = todo.db_manager._execute.exec_command_live
        return [c.args[0] for c in live.call_args_list], scripted, asked

    def test_restore_by_filename(self):
        # [1], puis le nom : l'image et le nom de base par défaut en
        # viennent, et non de la réponse « 1 ».
        commands, scripted, _ = self.restore(
            ["1", "", "n", "n"], "forged_image.zip"
        )
        self.assertIn("db_restore.py -d forged_image ", commands[0])
        self.assertIn("--image forged_image.zip", commands[0])
        [question] = scripted.events
        self.assertEqual(
            question["text"],
            "\U0001f4ac "
            + todo_i18n.t("File name in image_db (empty to go back): "),
        )

    def test_restore_with_neutralize(self):
        commands, _, _ = self.restore(
            ["1", "mydb", "y", "n"], "forged_image.zip"
        )
        self.assertIn("--neutralize", commands[0])
        self.assertIn("mydb_neutralize", commands[0])

    def test_a_blank_file_name_goes_back(self):
        # Ni commande ni autre question : rien n'est restauré.
        for blank in ("", "  "):
            commands, _, asked = self.restore(["1", "", "n", "n"], blank)
            self.assertEqual(commands, [], repr(blank))
            self.assertEqual(asked.call_count, 1, repr(blank))


class TestCreateBackupFromDatabase(unittest.TestCase):
    @patch("script.todo.database_manager.click")
    @patch("builtins.input")
    def test_creates_backup_command(self, mock_input, mock_click):
        todo = TODO()
        todo.db_manager._execute = MagicMock()
        todo.db_manager._execute.exec_command_live.return_value = (
            0,
            ["test_db"],
        )
        mock_click.prompt.return_value = "1"
        # backup name input
        mock_input.return_value = "backup.zip"
        todo.db_manager.create_backup_from_database()
        cmd = todo.db_manager._execute.exec_command_live.call_args_list[-1][0][
            0
        ]
        self.assertIn("--backup", cmd)
        self.assertIn("test_db", cmd)

    @patch("builtins.input")
    def test_no_database_chosen_makes_no_backup(self, mock_input):
        # select_database rend False sur [0], sans base, ou quand
        # PostgreSQL ne répond pas : ni nom de sauvegarde demandé, ni
        # commande lancée, que le nom soit vide ou non.
        todo = TODO()
        todo.db_manager._execute = MagicMock()
        todo.db_manager.select_database = MagicMock(return_value=False)
        for name in ("", "forged.zip"):
            mock_input.return_value = name
            todo.db_manager.create_backup_from_database()
        mock_input.assert_not_called()
        todo.db_manager._execute.exec_command_live.assert_not_called()


class TestDownloadDatabaseBackup(unittest.TestCase):
    """Database › Download database : les réponses sont tapées par des
    doubles, les commandes et l'archive aussi ; rien ne part."""

    def download(self, answers, listed, status=0, typed=()):
        """(ce que rend le dialogue, les chemins que lit `zipfile.ZipFile`)
        quand `input` reçoit `answers`, le nom demandé à la main `typed`, et
        que la liste des bases distantes rend `status` et les lignes
        `listed`. Garde les commandes lancées et la sortie imprimée."""
        todo = TODO()
        execute = todo.db_manager._execute = MagicMock()
        execute.exec_command_live.side_effect = [
            (status, listed),
            (0, "forged"),
        ]
        out = io.StringIO()
        with (
            ui.bind(port.ScriptedPort(typed)),
            patch("builtins.input", side_effect=answers),
            patch("getpass.getpass", return_value="forged"),
            patch("zipfile.ZipFile") as archive,
            redirect_stdout(out),
        ):
            done = todo.db_manager.download_database_backup_cli()
        self.commands = [
            c.args[0] for c in execute.exec_command_live.call_args_list
        ]
        self.printed = out.getvalue()
        return done, [c.args[0] for c in archive.call_args_list]

    def test_it_checks_the_archive_at_the_path_typed(self):
        done, read = self.download(["forged", "forged.zip"], ["forged_one"])
        self.assertEqual(done, (0, "forged.zip", "forged_one"))
        self.assertEqual(read, ["forged.zip"])

    def test_a_shown_number_picks_its_database(self):
        # « 2 » est le numéro affiché de forged_two ; « 02 » n'en est pas
        # un, et reste, comme tout autre texte, le nom tapé.
        listed = ["forged_one", "forged_two"]
        for typed, name in (
            ("2", "forged_two"),
            ("02", "02"),
            ("forged_other", "forged_other"),
        ):
            done, _ = self.download(["forged", typed, ""], listed)
            self.assertEqual(done[2], name, typed)

    def test_a_list_that_fails_asks_the_name_by_hand(self):
        # list_remote.py rend 1, et son erreur arrive dans la sortie
        # fusionnée : elle n'est pas un nom de base.
        done, _ = self.download(
            ["https://forged.invalid", ""],
            ["Connection Error: forged refusal"],
            status=1,
            typed=["forged_typed"],
        )
        self.assertEqual((done[0], done[2]), (0, "forged_typed"))
        self.assertNotIn("Connection Error", done[1])
        self.assertIn(
            todo_i18n.t("Cannot read the list of remote databases."),
            self.printed,
        )

    def test_a_blank_name_cancels(self):
        # Liste en échec, ou vide : ni chemin, ni mot de passe, ni
        # download_remote.sh ; la liste est la seule commande lancée.
        for listed, status in (
            (["Connection Error: forged refusal"], 1),
            ([], 0),
        ):
            done, read = self.download(
                ["https://forged.invalid", "", ""], listed, status, [""]
            )
            self.assertEqual(done, (1, "", ""), listed)
            self.assertEqual(read, [], listed)
            self.assertEqual(len(self.commands), 1, self.commands)
            self.assertIn("list_remote.py", self.commands[0])


class TestADownloadCancelledStopsItsCaller(unittest.TestCase):
    """Les appelants de `download_database_backup_cli` qui agissent sur ce
    qu'il rend : Analyse › Monitoring et Transform data › Anonymise
    restaurent l'archive, la migration de base la retient et la lit. La
    liste distante échoue et le nom tapé est vide : le dialogue rend
    (1, "", ""), et rien n'est téléchargé, restauré ni retenu."""

    def setUp(self):
        self.todo = TODO()
        self.execute = self.todo.db_manager._execute = MagicMock()
        self.execute.exec_command_live.side_effect = [
            (1, ["Connection Error: forged refusal"]),
            (0, "forged"),
        ]
        self.enterContext(ui.bind(port.ScriptedPort([""])))
        self.enterContext(
            patch(
                "builtins.input",
                side_effect=["https://forged.invalid", "", ""],
            )
        )
        self.enterContext(patch("getpass.getpass", return_value="forged"))
        self.enterContext(patch("zipfile.ZipFile"))
        self.enterContext(redirect_stdout(io.StringIO()))
        self.enterContext(patch("click.prompt", return_value="3"))

    def assert_only_the_list_ran(self):
        commands = [
            c.args[0] for c in self.execute.exec_command_live.call_args_list
        ]
        self.assertEqual(len(commands), 1, commands)
        self.assertIn("list_remote.py", commands[0])

    def test_monitoring_restores_nothing(self):
        with patch.object(self.todo, "_monitoring_restore") as restore:
            self.assertIsNone(self.todo._monitoring_select_source())
        restore.assert_not_called()
        self.assert_only_the_list_ran()

    def test_anonymise_restores_nothing(self):
        with patch.object(self.todo, "_monitoring_restore") as restore:
            self.assertIsNone(self.todo._transform_anonymise_source())
        restore.assert_not_called()
        self.assert_only_the_list_ran()

    def test_the_database_upgrade_keeps_no_file(self):
        from script.todo import todo_upgrade

        upgrade = todo_upgrade.TodoUpgrade(self.todo)
        home = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(
            patch.object(
                todo_upgrade,
                "UPGRADE_DATABASE_CONFIG_LOG",
                os.path.join(home, "absent.json"),
            )
        )
        with (
            patch.object(upgrade, "prompt_auto_execute"),
            patch.object(upgrade, "ask_ui", return_value="cli"),
            patch.object(upgrade, "ask", return_value="remote"),
            patch.object(upgrade, "write_config") as write_config,
            self.assertLogs(todo_upgrade._logger, "ERROR"),
        ):
            self.assertIsNone(upgrade.execute_odoo_upgrade())
        write_config.assert_not_called()
        self.assertNotIn("migration_file", upgrade.dct_progression)
        self.assert_only_the_list_ran()


class TestModuleLevelAbortExit(unittest.TestCase):
    """`click.exceptions.Abort` (raised by `click.prompt` on both Ctrl+C and
    Ctrl+D/EOF - see click's own `termui.prompt_func`) is NOT a
    `KeyboardInterrupt` subclass. At the question of the main menu, which
    declares `quits`, the navigator turns it into `SystemExit(0)`; every
    submenu (`prompt_assistant`, etc.) lets `Abort` go up out of `run()`.
    These tests drive the real script end to end (not a mock of the
    dispatch chain): the module-level guard around `todo.run()` catches
    the Abort of a submenu, and the main menu ends TODO cleanly.
    """

    def _run_todo(self, stdin_text):
        repo_root = Path(__file__).resolve().parent.parent
        python_bin = repo_root / ".venv.erplibre" / "bin" / "python3"
        env = os.environ.copy()
        with tempfile.TemporaryDirectory() as home_dir:
            env["HOME"] = home_dir
            return subprocess.run(
                [str(python_bin), "script/todo/todo.py"],
                cwd=repo_root,
                input=stdin_text,
                capture_output=True,
                text=True,
                env=env,
                timeout=30,
            )

    def test_ctrl_d_in_a_submenu_exits_cleanly(self):
        # "3" enters the Assistant submenu; the immediate EOF that follows
        # raises Abort at its question, which lets it go up out of run().
        result = self._run_todo("3\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertNotIn("click.exceptions.Abort", result.stderr)

    def test_ctrl_d_on_the_top_menu_still_exits_cleanly(self):
        # EOF at the question of the main menu ends TODO with code 0.
        result = self._run_todo("")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("Traceback", result.stderr)


class TestOptionsDeLAnonymiseur(unittest.TestCase):
    """Le mode, les listes, et les deux options qui suivent.

    La garde de la liste blanche appartient à la question des MODÈLES :
    c'est le `elif` de son `if`. Une question insérée entre les deux la
    rattache à la dernière posée, si bien qu'elle refuse selon une
    réponse qui n'est pas la sienne et laisse passer une liste blanche
    vide — laquelle n'anonymise rien, en l'annonçant comme un succès.

    Les cinq chemins du mode sont couverts ici, plus le fichier de mots
    introuvable.
    """

    def setUp(self):
        from script.todo.todo import TODO

        self.todo = TODO.__new__(TODO)
        self.vrai_input = builtins.input
        self.addCleanup(setattr, builtins, "input", self.vrai_input)
        self.sortie = io.StringIO()
        vrai = sys.stdout
        sys.stdout = self.sortie
        self.addCleanup(setattr, sys, "stdout", vrai)

    def _repondre(self, mode, *reponses):
        import script.todo.todo as module

        suite = iter(reponses)
        builtins.input = lambda invite="": next(suite)
        vrai = module.click.prompt
        module.click.prompt = lambda *a, **k: mode
        self.addCleanup(setattr, module.click, "prompt", vrai)
        return self.todo._monitoring_anonymize_options()

    def test_une_liste_blanche_sans_modele_est_REFUSEE(self):
        """Elle ne ferait rien : le dire vaut mieux que la lancer."""
        self.assertIsNone(self._repondre("2", "", "n", "n", ""))

    def test_une_liste_blanche_avec_un_modele_passe(self):
        self.assertEqual(
            self._repondre("2", "res.partner", "n", "n", ""),
            ["--mode", "whitelist", "--models", "res.partner"],
        )

    def test_l_hybride_sans_modele_passe(self):
        """Ses défauts SONT sa liste : rien à nommer."""
        self.assertEqual(
            self._repondre("1", "", "n", "n", ""), ["--mode", "hybrid"]
        )

    def test_les_deux_options_suivent_le_mode(self):
        self.assertEqual(
            self._repondre("1", "", "o", "o", ""),
            ["--mode", "hybrid", "--include-logins", "--keep-digits"],
        )

    def test_la_liste_noire_exclut(self):
        self.assertEqual(
            self._repondre("3", "res.users", "n", "n", ""),
            ["--mode", "blacklist", "--exclude", "res.users"],
        )

    def test_un_mode_inconnu_renonce(self):
        self.assertIsNone(self._repondre("9"))

    def test_un_fichier_de_mots_introuvable_est_REFUSE(self):
        """Le lancer produirait une trace au lieu d'un message."""
        self.assertIsNone(
            self._repondre("1", "", "n", "n", "/nexistepas/mots.py")
        )


class TestParseIndexSelection(unittest.TestCase):
    """Une liste de rangs, « 1 3 » ou « 1,3 » : Assistant › LLM › Known
    servers › Delete a server, et les choix de VM des familles QEMU et
    Proxmox, y prennent une option par son numéro tel qu'une liste
    l'écrit, ou par son nom."""

    def test_a_rank_is_a_number_as_the_list_writes_it(self):
        # « 01 », « +1 » ou un chiffre d'une autre écriture désigneraient
        # la première option ; « 0 », « -1 » ou « 4 », sur trois, aucune.
        parse = TODO._parse_index_selection
        options = ["forged_a", "forged_b", "forged_c"]
        self.assertEqual(parse("1 3", options), ["forged_a", "forged_c"])
        self.assertEqual(
            parse("2,forged_a,2", options), ["forged_b", "forged_a"]
        )
        # Une option nommée comme un numéro se prend par son nom.
        self.assertEqual(parse("01", ["forged_x", "01"]), ["01"])
        for raw in ("01", "+1", "١", "0", "-1", "4"):
            with self.subTest(raw=raw):
                self.assertEqual(parse(raw, options), [])

    def test_is_index_agrees_with_the_parser(self):
        # `_is_index` sert de garde à un appelant qui doit dire un numéro
        # hors liste plutôt que l'escamoter ; elle doit reconnaître les
        # mêmes numéros que `_parse_index_selection`, ni plus ni moins.
        is_index = TODO._is_index
        options = ["forged_a", "forged_b", "forged_c"]
        for raw in ("1", "2", "3"):
            with self.subTest(raw=raw):
                self.assertTrue(is_index(raw, options))
        for raw in ("01", "+1", "١", "0", "-1", "4"):
            with self.subTest(raw=raw):
                self.assertFalse(is_index(raw, options))


class TestAttributsDeTODO(unittest.TestCase):
    """Tout `self.X` que `TODO` LIT est-il posé par TODO ou un mixin ?

    Un attribut mal orthographié ne lève qu'à l'exécution de l'entrée qui
    le touche : `self._execute` là où `TODO` pose `self.execute` traverse
    tout contrôle statique et attend l'opérateur.

    Le nom se cherche dans les classes dont TODO HÉRITE, et nulle part
    ailleurs : `DatabaseManager` pose bien `_execute`, si bien que le
    chercher dans tout `script/todo/` le trouve et ne voit rien. Un
    bouchon de test qui fournit l'attribut masque la faute de la même
    façon.
    """

    RACINE = Path(__file__).resolve().parents[1] / "script" / "todo"

    @staticmethod
    def _noms_de_classe(classe):
        """Méthodes et attributs que cette classe POSE."""
        noms = set()
        for noeud in ast.walk(classe):
            if isinstance(noeud, (ast.FunctionDef, ast.AsyncFunctionDef)):
                noms.add(noeud.name)
            if (
                isinstance(noeud, ast.Attribute)
                and isinstance(noeud.value, ast.Name)
                and noeud.value.id == "self"
                and isinstance(noeud.ctx, ast.Store)
            ):
                noms.add(noeud.attr)
        for corps in classe.body:
            if isinstance(corps, ast.Assign):
                for cible in corps.targets:
                    if isinstance(cible, ast.Name):
                        noms.add(cible.id)
        return noms

    def _classe_todo(self):
        source = (self.RACINE / "todo.py").read_text(encoding="utf-8")
        arbre = ast.parse(source)
        return next(
            n
            for n in ast.walk(arbre)
            if isinstance(n, ast.ClassDef) and n.name == "TODO"
        )

    def test_aucun_attribut_lu_sans_etre_pose(self):
        todo = self._classe_todo()
        bases = {b.id for b in todo.bases if isinstance(b, ast.Name)}
        self.assertGreater(len(bases), 5, "TODO est composé de mixins")
        poses = self._noms_de_classe(todo)
        trouvees = set()
        for chemin in sorted(self.RACINE.rglob("*.py")):
            try:
                arbre = ast.parse(chemin.read_text(encoding="utf-8"))
            except SyntaxError:  # pragma: no cover - fichier en travaux
                continue
            for noeud in ast.walk(arbre):
                if isinstance(noeud, ast.ClassDef) and noeud.name in bases:
                    poses |= self._noms_de_classe(noeud)
                    trouvees.add(noeud.name)
        # Une base introuvable rendrait le contrôle muet : ses noms
        # manqueraient, et tout ce qu'elle pose passerait pour orphelin.
        self.assertEqual(bases - trouvees, set(), "base introuvable")
        lus = {
            noeud.attr
            for noeud in ast.walk(todo)
            if isinstance(noeud, ast.Attribute)
            and isinstance(noeud.value, ast.Name)
            and noeud.value.id == "self"
            and isinstance(noeud.ctx, ast.Load)
        }
        self.assertEqual(sorted(lus - poses), [])


class TestLeFluxQuiEcrit(unittest.TestCase):
    """`_monitoring_write_flow` : les codes de sortie sont un CONTRAT.

    La marche à blanc rend 2 pour un refus, 1 quand il y a du travail, et
    0 quand il n'y a RIEN à anonymiser. Ne distinguer que le 2 fait
    confirmer puis « appliquer » un plan vide : l'appelant tire alors une
    sauvegarde de la base INTACTE et l'annonce anonymisée.
    """

    def setUp(self):
        from script.analyse import monitoring

        self.todo = TODO.__new__(TODO)
        self.todo._monitoring_anonymize_options = lambda: ["--mode", "hybrid"]
        self.monitoring = monitoring
        self.addCleanup(
            setattr, monitoring, "run_analysis", monitoring.run_analysis
        )
        self.addCleanup(setattr, builtins, "input", builtins.input)
        self.sortie = io.StringIO()
        vrai = sys.stdout
        sys.stdout = self.sortie
        self.addCleanup(setattr, sys, "stdout", vrai)
        self.appels = []

    def _codes(self, *codes):
        """Les codes que la marche à blanc puis l'écriture rendront."""
        suite = iter(codes)

        def faux(analyse, database, **kw):
            self.appels.append(list(kw.get("extra") or []))
            return next(suite)

        self.monitoring.run_analysis = faux

    def _taper(self, *reponses):
        suite = iter(reponses)
        builtins.input = lambda invite="": next(suite)

    def _dit(self, cle):
        return todo_i18n.t(cle) in self.sortie.getvalue()

    def test_un_plan_vide_ne_se_fait_pas_confirmer(self):
        """Retaper le nom d'une base qu'on ne touchera pas obtient un
        consentement sans objet."""
        self._codes(0)
        self._taper()  # aucune invite ne doit être posée
        self.assertIs(False, self.todo._monitoring_write_flow({}, "base"))
        self.assertEqual(1, len(self.appels))

    def test_un_plan_vide_le_DIT(self):
        self._codes(0)
        self.todo._monitoring_write_flow({}, "base")
        self.assertTrue(self._dit("Nothing to anonymise: nothing to confirm."))

    def test_un_refus_de_la_marche_a_blanc_arrete(self):
        self._codes(2)
        self.assertIs(False, self.todo._monitoring_write_flow({}, "base"))
        self.assertEqual(1, len(self.appels))

    def test_du_travail_annonce_demande_le_nom_puis_ecrit(self):
        self._codes(3, 0)
        self._taper("base")
        self.assertIs(True, self.todo._monitoring_write_flow({}, "base"))
        self.assertEqual(2, len(self.appels))
        self.assertIn("--apply", self.appels[1])
        self.assertIn("--confirm", self.appels[1])

    def test_un_nom_mal_retape_n_ecrit_rien(self):
        self._codes(3)
        self._taper("bas")
        self.assertIs(False, self.todo._monitoring_write_flow({}, "base"))
        self.assertEqual(1, len(self.appels))

    def test_une_ecriture_en_erreur_rend_FAUX(self):
        """L'appelant ne doit pas tirer de sauvegarde derrière."""
        self._codes(3, 2)
        self._taper("base")
        self.assertIs(False, self.todo._monitoring_write_flow({}, "base"))

    def test_renoncer_aux_options_n_appelle_rien(self):
        self.todo._monitoring_anonymize_options = lambda: None
        self._codes()
        self.assertIs(False, self.todo._monitoring_write_flow({}, "base"))
        self.assertEqual([], self.appels)

    def test_seul_le_code_du_TRAVAIL_ouvre_la_confirmation(self):
        """Une trace Python sort en 1. Lire « ni 0 ni 2 » comme du travail
        faisait demander la confirmation destructrice après un plantage,
        puis « appliquer » un plan jamais calculé."""
        for code in (0, 1, 2, 4, 5, 127):
            with self.subTest(code=code):
                self._codes(code)
                self.appels = []
                self._taper()  # aucune invite ne doit être posée
                self.assertIs(
                    False, self.todo._monitoring_write_flow({}, "base")
                )
                self.assertEqual(1, len(self.appels))

    def test_un_code_inattendu_le_DIT(self):
        """Le refus, lui, a déjà parlé : ne pas le redoubler."""
        self._codes(1)
        self.todo._monitoring_write_flow({}, "base")
        self.assertTrue(self._dit("The dry run ended on an unexpected code:"))
        self.sortie.truncate(0)
        self.sortie.seek(0)
        self._codes(2)
        self.appels = []
        self.todo._monitoring_write_flow({}, "base")
        self.assertFalse(self._dit("The dry run ended on an unexpected code:"))

    def test_une_ecriture_SANS_EFFET_ne_vaut_pas_une_ecriture(self):
        """Un plan devenu vide entre les deux passes rendait 0, psql
        acceptant un script vide : l'appelant tirait alors une sauvegarde
        de la base intacte en l'annonçant anonymisée."""
        from script.analyse import anonymize

        self._codes(3, anonymize.SORTIE_SANS_EFFET)
        self._taper("base")
        self.assertIs(False, self.todo._monitoring_write_flow({}, "base"))

    def test_les_codes_sont_ceux_que_le_moteur_declare(self):
        """Le contrat vit dans `anonymize`, pas en double ici."""
        from script.analyse import anonymize

        self.assertEqual(0, anonymize.SORTIE_RIEN)
        self.assertEqual(2, anonymize.SORTIE_REFUS)
        self.assertEqual(3, anonymize.SORTIE_A_FAIRE)
        self.assertEqual(4, anonymize.SORTIE_SANS_EFFET)
        self.assertNotIn(
            1,
            (
                anonymize.SORTIE_RIEN,
                anonymize.SORTIE_REFUS,
                anonymize.SORTIE_A_FAIRE,
                anonymize.SORTIE_SANS_EFFET,
            ),
        )


if __name__ == "__main__":
    unittest.main()
