#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch

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

            with patch(
                "script.todo.version_manager.VERSION_DATA_FILE", version_file
            ), patch(
                "script.todo.version_manager.INSTALLED_ODOO_VERSION_FILE",
                os.path.join(tmpdir, "nonexistent.txt"),
            ), patch(
                "script.todo.version_manager.ODOO_VERSION_FILE",
                odoo_version_file,
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

            with patch(
                "script.todo.version_manager.VERSION_DATA_FILE", version_file
            ), patch(
                "script.todo.version_manager.INSTALLED_ODOO_VERSION_FILE",
                installed_file,
            ), patch(
                "script.todo.version_manager.ODOO_VERSION_FILE",
                os.path.join(tmpdir, "nonexistent"),
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

    def test_with_callback(self):
        todo = TODO()
        todo.execute = MagicMock()
        callback = MagicMock()
        dct = {"callback": callback}
        todo.execute_from_configuration(dct)
        callback.assert_called_once_with(dct)

    def test_makefile_error_stops_execution(self):
        todo = TODO()
        todo.execute = MagicMock()
        todo.execute.exec_command_live.return_value = 1
        callback = MagicMock()
        dct = {"makefile_cmd": "broken", "callback": callback}
        todo.execute_from_configuration(dct)
        callback.assert_not_called()


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
        """Signalé à l'usage : « pas clair si les tests ont passé ».

        unittest écrit son verdict sur stderr et les tests impriment sur
        stdout ; capturés ensemble, le stdout tamponné se déversait après
        le « OK ». Le lecteur voyait donc du bruit en dernier, pas le
        résultat.
        """
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
        with patch.object(
            todo, "execute_unit_tests"
        ) as mock_run, patch.object(todo, "execute_test_module"), patch(
            "click.prompt", side_effect=[entry, "0"]
        ), patch(
            "builtins.print"
        ):
            todo.prompt_execute_test()
        return mock_run

    def test_entry_4_runs_the_mail_tests(self):
        self.assertEqual(self._choose("4").call_args[0], ("test_mail*.py",))

    def test_entry_5_runs_the_analyse_tests(self):
        self.assertEqual(self._choose("5").call_args[0], ("test_analyse*.py",))

    def test_entry_3_still_runs_everything(self):
        self.assertEqual(self._choose("3").call_args[0], ())


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
        with patch("os.path.exists", return_value=True), patch(
            "builtins.input", return_value="n"
        ), patch("builtins.open") as mock_open, patch(
            "os.makedirs"
        ) as mock_makedirs, patch(
            "builtins.print"
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
        with patch("os.path.exists", return_value=True), patch(
            "builtins.input", return_value="y"
        ), patch("builtins.open", mock_open(read_data="gabarit")), patch(
            "os.makedirs"
        ) as mock_makedirs, patch(
            "builtins.print"
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
    def _deployed_templates():
        """Les gabarits nommés dans les appels à `_setup_claude_command`."""
        import ast

        source = Path("script/todo/todo.py").read_text(encoding="utf-8")
        found = []
        for node in ast.walk(ast.parse(source)):
            if not isinstance(node, ast.Call):
                continue
            attr = getattr(node.func, "attr", None)
            if attr != "_setup_claude_command":
                continue
            # (nom_de_commande, nom_de_gabarit) : les deux sont des littéraux,
            # sans quoi le test ne peut rien affirmer.
            args = [
                a.value
                for a in node.args
                if isinstance(a, ast.Constant) and isinstance(a.value, str)
            ]
            if len(args) >= 2:
                found.append(args[1])
        return found

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
        source = Path("script/todo/todo.py").read_text(encoding="utf-8")
        import ast

        pairs = []
        for node in ast.walk(ast.parse(source)):
            if not isinstance(node, ast.Call):
                continue
            if getattr(node.func, "attr", None) != "_setup_claude_command":
                continue
            args = [
                a.value
                for a in node.args
                if isinstance(a, ast.Constant) and isinstance(a.value, str)
            ]
            if len(args) >= 2:
                pairs.append((args[0], args[1]))
        self.assertTrue(pairs)
        for command, template in pairs:
            with self.subTest(command=command):
                text = Path("conf", template).read_text(encoding="utf-8")
                self.assertIn(f"name: {command}\n", text)


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
        with patch("script.todo.todo.shutil.which", return_value=None), patch(
            "builtins.print"
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
        with patch("builtins.input", return_value="n"), patch.object(
            todo, "_claude_plugin_exec"
        ) as mock_exec, patch("builtins.print"):
            todo._claude_install_preferred_plugins()
        mock_exec.assert_not_called()

    def test_accepting_installs_only_what_is_missing(self):
        todo = TODO()
        with patch("builtins.input", return_value="y"), patch.object(
            todo, "_claude_plugin_exec"
        ) as mock_exec, patch.object(
            todo,
            "_claude_plugin_is_installed",
            side_effect=lambda name: name == "pyright-lsp",
        ), patch(
            "builtins.print"
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
                ("good", '{"plugins":[{"name":"a",' '"description":"d"}]}'),
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
        with patch.object(
            todo, "_claude_marketplace_catalog", return_value=catalog
        ), patch("builtins.input", return_value="python"), patch(
            "builtins.print"
        ) as mock_print:
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
    @patch("builtins.input")
    def test_restore_by_filename(self, mock_input):
        todo = TODO()
        todo.db_manager._execute = MagicMock()
        todo.db_manager._execute.exec_command_live.return_value = (
            0,
            [],
        )
        # status="1" (by filename), db name default, no neutralize
        mock_input.side_effect = ["1", "", "n", "n"]
        todo.db_manager.restore_from_database()
        cmd = todo.db_manager._execute.exec_command_live.call_args_list[0][0][
            0
        ]
        self.assertIn("db_restore.py", cmd)

    @patch("builtins.input")
    def test_restore_with_neutralize(self, mock_input):
        todo = TODO()
        todo.db_manager._execute = MagicMock()
        todo.db_manager._execute.exec_command_live.return_value = (
            0,
            [],
        )
        mock_input.side_effect = ["1", "mydb", "y", "n"]
        todo.db_manager.restore_from_database()
        cmd = todo.db_manager._execute.exec_command_live.call_args_list[0][0][
            0
        ]
        self.assertIn("--neutralize", cmd)
        self.assertIn("mydb_neutralize", cmd)


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


class TestModuleLevelAbortExit(unittest.TestCase):
    """`click.exceptions.Abort` (raised by `click.prompt` on both Ctrl+C and
    Ctrl+D/EOF - see click's own `termui.prompt_func`) is NOT a
    `KeyboardInterrupt` subclass. Only the top-level menu's `click.prompt`
    call is wrapped locally, inside `run()` (todo.py around line 149) -
    every submenu (`prompt_assistant`, etc.) lets `Abort` propagate
    uncaught. These tests drive the real script end to end (not a mock of
    the dispatch chain) to prove the module-level guard around
    `todo.run()` (todo.py around line 7159) now catches it too.
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
        # raises Abort from a click.prompt() call that run() does not wrap.
        result = self._run_todo("3\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertNotIn("click.exceptions.Abort", result.stderr)

    def test_ctrl_d_on_the_top_menu_still_exits_cleanly(self):
        # Regression guard: the pre-existing local handler in run() must
        # keep working once the module-level guard is added alongside it.
        result = self._run_todo("")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
