#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le sous-menu Exécution › Dolibarr : installer, lancer, arrêter, suivre.

Le menu choisit l'instance et lance script/dolibarr/run.py avec elle. Ce qui
se garde :
- chaque entrée affichée a sa branche, au bon numéro (MenuCoherence) ;
- une seule instance de développement est prise d'office, plusieurs se
  choisissent, aucune se dit ;
- l'état se demande pour toutes les instances, sans choix préalable.
"""

import builtins
import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))
sys.path.insert(0, str(RACINE / "test"))

import test_todo_menu as menus  # noqa: E402

from script.todo import dolibarr_menu  # noqa: E402
from script.todo.todo import TODO  # noqa: E402

RUN = "./.venv.erplibre/bin/python -u script/dolibarr/run.py"


class TestDolibarrMenuNumbering(menus.MenuCoherence, unittest.TestCase):
    SOURCE = RACINE / "script" / "todo" / "dolibarr_menu.py"
    ENTRY = "def prompt_execute_dolibarr(self):"
    END = "def _dolibarr_run(self, action):"
    MINIMUM = 5
    EXPECTED = {
        "Dolibarr - Install an instance": "prompt_install_dolibarr",
        "Dolibarr - Start an instance": "_dolibarr_run",
        "Dolibarr - Stop an instance": "_dolibarr_run",
        "Dolibarr - Instance status": "_dolibarr_run",
        "Dolibarr - Instance logs": "_dolibarr_run",
        "Dolibarr - Update the pinned commit": "_dolibarr_pin",
        "Dolibarr - Upgrade an instance": "_dolibarr_upgrade",
        "Dolibarr - Health, security and integrity": "_dolibarr_doctor",
        "Dolibarr - Back up an instance": "_dolibarr_backup",
        "Dolibarr - Restore a backup": "_dolibarr_restore",
        "Dolibarr - List the instances": "_dolibarr_fleet_list",
        "Dolibarr - Remove an instance": "_dolibarr_remove",
        "Dolibarr - Find installations (local or SSH)": "_dolibarr_detect",
        "Dolibarr - Debug profile": "_dolibarr_debug",
        "Dolibarr - Modules: create, link, enable": "_dolibarr_module",
        "Dolibarr - Package a module (DoliStore)": "_dolibarr_package",
        "Dolibarr - Code quality of a module (phpcs, PHPStan)": (
            "_dolibarr_quality"
        ),
        "Dolibarr - Hooks and triggers between versions": "_dolibarr_hooks",
        "Dolibarr - Core changes: branch, check, patches": "_dolibarr_core",
        "Dolibarr - REST API: technical user and key": "_dolibarr_api",
    }


class Banc(unittest.TestCase):
    def setUp(self):
        self.registre = {}
        p = mock.patch.object(
            dolibarr_menu.lib_dolibarr,
            "load_registry",
            lambda root: self.registre,
        )
        p.start()
        self.addCleanup(p.stop)

    def lancer(self, action, reponses=()):
        todo = TODO.__new__(TODO)
        lances = []

        class Execute:
            def exec_command_live(inner, cmd, **kwargs):
                lances.append(cmd)
                return 0

        todo.execute = Execute()
        suite = iter(reponses)

        def repondre(prompt=""):
            try:
                return next(suite)
            except StopIteration:
                raise AssertionError(
                    f"question imprévue : {prompt!r}"
                ) from None

        sortie = io.StringIO()
        with (
            mock.patch.object(builtins, "input", repondre),
            contextlib.redirect_stdout(sortie),
        ):
            todo._dolibarr_run(action)
        return lances, sortie.getvalue()


DEV = {"mode": "dev", "runtime": "native", "url": "http://127.0.0.1:8080"}


class TestChoixDeLInstance(Banc):
    def test_a_single_instance_is_taken_without_asking(self):
        self.registre = {"erp": dict(DEV)}
        lances, _s = self.lancer("start")
        self.assertEqual(lances, [f"{RUN} start --instance erp"])

    def test_several_instances_are_chosen_by_number(self):
        self.registre = {"aaa": dict(DEV), "zzz": dict(DEV)}
        lances, _s = self.lancer("stop", reponses=["2"])
        self.assertEqual(lances, [f"{RUN} stop --instance zzz"])

    def test_back_at_the_choice_runs_nothing(self):
        self.registre = {"aaa": dict(DEV), "zzz": dict(DEV)}
        lances, _s = self.lancer("logs", reponses=["0"])
        self.assertEqual(lances, [])

    def test_no_instance_says_so(self):
        lances, sortie = self.lancer("start")
        self.assertEqual(lances, [])
        self.assertIn(
            dolibarr_menu.t("No development Dolibarr instance."), sortie
        )

    def test_production_instances_are_not_offered_here(self):
        self.registre = {"erp": dict(DEV, mode="prod")}
        lances, _s = self.lancer("start")
        self.assertEqual(lances, [])

    def test_a_development_container_instance_is_offered_too(self):
        # run.py la pilote par son moteur.
        self.registre = {"ctr": dict(DEV, runtime="container")}
        lances, _s = self.lancer("start")
        self.assertEqual(lances, [f"{RUN} start --instance ctr"])

    def test_status_covers_every_instance_without_asking(self):
        self.registre = {"aaa": dict(DEV), "zzz": dict(DEV)}
        lances, _s = self.lancer("status")
        self.assertEqual(lances, [f"{RUN} status"])


DETECT = "./.venv.erplibre/bin/python -u script/dolibarr/detect.py"
DOCTOR = "./.venv.erplibre/bin/python -u script/dolibarr/doctor.py"


BACKUP = "./.venv.erplibre/bin/python -u script/dolibarr/backup.py"


class TestSauvegarde(Banc):
    def lancer_sauvegarde(self, reponses=()):
        todo = TODO.__new__(TODO)
        lances = []

        class Execute:
            def exec_command_live(inner, cmd, **kwargs):
                lances.append(cmd)
                return 0

        todo.execute = Execute()
        suite = iter(reponses)
        with (
            mock.patch.object(builtins, "input", lambda p="": next(suite)),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            todo._dolibarr_backup()
        return lances

    def test_every_instance_can_be_saved_production_included(self):
        self.registre = {"aaa": dict(DEV), "zzz": dict(DEV, mode="prod")}
        lances = self.lancer_sauvegarde(["2"])
        self.assertEqual(lances, [f"{BACKUP} create --instance zzz"])

    def test_a_single_instance_is_taken_without_asking(self):
        self.registre = {"erp": dict(DEV, runtime="container")}
        self.assertEqual(
            self.lancer_sauvegarde(), [f"{BACKUP} create --instance erp"]
        )

    def test_no_instance_saves_nothing(self):
        self.assertEqual(self.lancer_sauvegarde(), [])


class TestRestauration(Banc):
    def setUp(self):
        super().setUp()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.racine = Path(tmp.name)
        dossier = self.racine / "private" / "dolibarr" / "backups" / "erp"
        dossier.mkdir(parents=True)
        for nom in (
            "erp-20260901-000000.tar.gz",
            "erp-20260927-081500.tar.gz",
        ):
            (dossier / nom).write_bytes(b"x")
        p = mock.patch.object(dolibarr_menu, "ROOT", str(self.racine))
        p.start()
        self.addCleanup(p.stop)
        self.registre = {"erp": dict(DEV, mode="prod")}

    def lancer_restauration(self, reponses):
        todo = TODO.__new__(TODO)
        lances = []

        class Execute:
            def exec_command_live(inner, cmd, **kwargs):
                lances.append(cmd)
                return 0

        todo.execute = Execute()
        suite = iter(reponses)
        sortie = io.StringIO()
        with (
            mock.patch.object(builtins, "input", lambda p="": next(suite)),
            contextlib.redirect_stdout(sortie),
        ):
            todo._dolibarr_restore()
        return lances, sortie.getvalue()

    def test_the_newest_archive_comes_first_and_the_name_is_retyped(self):
        lances, sortie = self.lancer_restauration(["1", "erp"])
        archive = "private/dolibarr/backups/erp/erp-20260927-081500.tar.gz"
        self.assertEqual(
            lances,
            [
                f"{BACKUP} restore --instance erp --archive {archive}"
                " --confirm erp"
            ],
        )
        self.assertIn(
            dolibarr_menu.t(
                "This overwrites the database, documents and modules of %s;"
                " a safety backup comes first."
            )
            % "erp",
            sortie,
        )

    def test_a_wrong_name_runs_nothing(self):
        lances, _s = self.lancer_restauration(["1", "er"])
        self.assertEqual(lances, [])

    def test_no_archive_says_so(self):
        self.registre = {"autre": dict(DEV)}
        lances, _s = self.lancer_restauration([])
        self.assertEqual(lances, [])


FLEET = "./.venv.erplibre/bin/python -u script/dolibarr/fleet.py"


class TestParc(Banc):
    def lancer_parc(self, methode, reponses=(), codes=None):
        todo = TODO.__new__(TODO)
        lances = []
        codes = list(codes or [])

        class Execute:
            def exec_command_live(inner, cmd, **kwargs):
                lances.append(cmd)
                return codes.pop(0) if codes else 0

        todo.execute = Execute()
        suite = iter(reponses)
        with (
            mock.patch.object(builtins, "input", lambda p="": next(suite)),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            getattr(todo, methode)()
        return lances

    def test_list_runs_fleet_list(self):
        self.assertEqual(
            self.lancer_parc("_dolibarr_fleet_list"), [f"{FLEET} list"]
        )

    def test_remove_shows_the_plan_backs_up_then_asks_the_name(self):
        self.registre = {"erp": dict(DEV)}
        lances = self.lancer_parc("_dolibarr_remove", ["y", "erp"])
        self.assertEqual(
            lances,
            [
                f"{FLEET} remove --instance erp --dry-run",
                f"{BACKUP} create --instance erp",
                f"{FLEET} remove --instance erp --confirm erp",
            ],
        )

    def test_a_failed_backup_stops_the_removal(self):
        self.registre = {"erp": dict(DEV)}
        lances = self.lancer_parc("_dolibarr_remove", ["y"], codes=[0, 1])
        self.assertEqual(len(lances), 2)

    def test_no_backup_asked_and_a_wrong_name_removes_nothing(self):
        self.registre = {"erp": dict(DEV)}
        lances = self.lancer_parc("_dolibarr_remove", ["n", "er"])
        self.assertEqual(lances, [f"{FLEET} remove --instance erp --dry-run"])


UPGRADE = "./.venv.erplibre/bin/python -u script/dolibarr/upgrade.py"


class TestMontee(Banc):
    def lancer_montee(self, reponses):
        todo = TODO.__new__(TODO)
        lances = []

        class Execute:
            def exec_command_live(inner, cmd, **kwargs):
                lances.append(cmd)
                return 0

        todo.execute = Execute()
        suite = iter(reponses)
        with (
            mock.patch.object(builtins, "input", lambda p="": next(suite)),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            todo._dolibarr_upgrade()
        return lances

    def test_the_chosen_instance_is_upgraded_after_a_yes(self):
        self.registre = {"aaa": dict(DEV), "zzz": dict(DEV, mode="prod")}
        self.assertEqual(
            self.lancer_montee(["2", "y"]),
            [f"{UPGRADE} --instance zzz"],
        )

    def test_no_runs_nothing(self):
        self.registre = {"erp": dict(DEV)}
        self.assertEqual(self.lancer_montee(["n"]), [])


DEBUG = "./.venv.erplibre/bin/python -u script/dolibarr/debug.py"


class TestDeverminage(Banc):
    def lancer_debug(self, reponses):
        todo = TODO.__new__(TODO)
        lances = []

        class Execute:
            def exec_command_live(inner, cmd, **kwargs):
                lances.append(cmd)
                return 0

        todo.execute = Execute()
        suite = iter(reponses)
        with (
            mock.patch.object(builtins, "input", lambda p="": next(suite)),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            todo._dolibarr_debug()
        return lances

    def test_on_for_a_development_instance(self):
        self.registre = {"erp": dict(DEV)}
        self.assertEqual(
            self.lancer_debug(["1"]), [f"{DEBUG} on --instance erp"]
        )

    def test_tail_asks_for_a_filter(self):
        self.registre = {"erp": dict(DEV)}
        self.assertEqual(
            self.lancer_debug(["4", "sql="]),
            [f"{DEBUG} tail --instance erp --filter sql="],
        )

    def test_a_production_needs_its_name_retyped(self):
        self.registre = {"erp": dict(DEV, mode="prod")}
        self.assertEqual(
            self.lancer_debug(["1", "erp"]),
            [f"{DEBUG} on --instance erp --confirm erp"],
        )
        self.assertEqual(self.lancer_debug(["1", "er"]), [])


MODULE = "./.venv.erplibre/bin/python -u script/dolibarr/module.py"
CONTENEUR = {"mode": "dev", "runtime": "container", "engine": "podman"}


class TestModules(Banc):
    def lancer_module(self, reponses):
        todo = TODO.__new__(TODO)
        lances = []

        class Execute:
            def exec_command_live(inner, cmd, **kwargs):
                lances.append(cmd)
                return 0

        todo.execute = Execute()
        suite = iter(reponses)

        def repondre(prompt=""):
            try:
                return next(suite)
            except StopIteration:
                raise AssertionError(
                    f"question imprévue : {prompt!r}"
                ) from None

        with (
            mock.patch.object(builtins, "input", repondre),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            todo._dolibarr_module()
        return lances

    def test_create_takes_the_first_free_id_and_enables(self):
        self.registre = {"erp": dict(DEV)}
        self.assertEqual(
            self.lancer_module(["1", "Zorglub", "", "y"]),
            [f"{MODULE} create --instance erp --name Zorglub --enable"],
        )

    def test_create_with_an_id(self):
        self.registre = {"erp": dict(DEV)}
        self.assertEqual(
            self.lancer_module(["1", "Zorglub", "500123", "n"]),
            [f"{MODULE} create --instance erp --name Zorglub --id 500123"],
        )

    def test_an_id_that_is_not_a_number_runs_nothing(self):
        self.registre = {"erp": dict(DEV)}
        self.assertEqual(self.lancer_module(["1", "Zorglub", "5e5"]), [])

    def test_link_a_native_instance_to_a_directory(self):
        self.registre = {"erp": dict(DEV)}
        self.assertEqual(
            self.lancer_module(["2", "/src/mon module"]),
            [f"{MODULE} link --instance erp --path '/src/mon module'"],
        )

    def test_a_container_is_not_offered_link(self):
        self.registre = {"erp": dict(CONTENEUR)}
        self.assertEqual(
            self.lancer_module(["2", "Stock"]),
            [f"{MODULE} enable --instance erp --name Stock"],
        )

    def test_disable(self):
        self.registre = {"erp": dict(DEV)}
        self.assertEqual(
            self.lancer_module(["4", "Zorglub"]),
            [f"{MODULE} disable --instance erp --name Zorglub"],
        )

    def test_productions_are_not_offered(self):
        self.registre = {"prod": dict(DEV, mode="prod"), "erp": dict(DEV)}
        self.assertEqual(
            self.lancer_module(["3", "Zorglub"]),
            [f"{MODULE} enable --instance erp --name Zorglub"],
        )
        self.registre = {"prod": dict(DEV, mode="prod")}
        self.assertEqual(self.lancer_module([]), [])

    def test_an_empty_name_runs_nothing(self):
        self.registre = {"erp": dict(DEV)}
        self.assertEqual(self.lancer_module(["1", ""]), [])


PACKAGE = "./.venv.erplibre/bin/python -u script/dolibarr/package.py"


class TestPaquet(Banc):
    def lancer_paquet(self, reponses):
        todo = TODO.__new__(TODO)
        lances = []

        class Execute:
            def exec_command_live(inner, cmd, **kwargs):
                lances.append(cmd)
                return 0

        todo.execute = Execute()
        suite = iter(reponses)
        with (
            mock.patch.object(builtins, "input", lambda p="": next(suite)),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            todo._dolibarr_package()
        return lances

    def test_check_build_and_build_for_dolistore(self):
        self.registre = {"erp": dict(DEV)}
        for choix, fin in (
            ("1", "check --instance erp --name Zorglub"),
            ("2", "build --instance erp --name Zorglub"),
            ("3", "build --instance erp --name Zorglub --dolistore"),
        ):
            self.assertEqual(
                self.lancer_paquet([choix, "Zorglub"]), [f"{PACKAGE} {fin}"]
            )

    def test_only_development_instances_and_a_name(self):
        self.registre = {"prod": dict(DEV, mode="prod")}
        self.assertEqual(self.lancer_paquet([]), [])
        self.registre = {"erp": dict(DEV)}
        self.assertEqual(self.lancer_paquet(["1", ""]), [])


QUALITY = "./.venv.erplibre/bin/python -u script/dolibarr/quality.py"


class TestQualite(Banc):
    def lancer_qualite(self, reponses):
        todo = TODO.__new__(TODO)
        lances = []

        class Execute:
            def exec_command_live(inner, cmd, **kwargs):
                lances.append(cmd)
                return 0

        todo.execute = Execute()
        suite = iter(reponses)
        with (
            mock.patch.object(builtins, "input", lambda p="": next(suite)),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            todo._dolibarr_quality()
        return lances

    def test_both_tools_or_one(self):
        self.registre = {"erp": dict(DEV)}
        base = f"{QUALITY} --instance erp --name Zorglub"
        for choix, fin in (
            ("1", ""),
            ("2", " --only phpcs"),
            ("3", " --only phpstan"),
        ):
            self.assertEqual(
                self.lancer_qualite([choix, "Zorglub"]), [base + fin]
            )

    def test_only_development_instances_and_a_name(self):
        self.registre = {"prod": dict(DEV, mode="prod")}
        self.assertEqual(self.lancer_qualite([]), [])
        self.registre = {"erp": dict(DEV)}
        self.assertEqual(self.lancer_qualite(["1", ""]), [])


HOOKS = "./.venv.erplibre/bin/python -u script/dolibarr/hooks_index.py"


class TestHooks(unittest.TestCase):
    def lancer_hooks(self, reponses):
        todo = TODO.__new__(TODO)
        lances = []

        class Execute:
            def exec_command_live(inner, cmd, **kwargs):
                lances.append(cmd)
                return 0

        todo.execute = Execute()
        suite = iter(reponses)
        with (
            mock.patch.object(builtins, "input", lambda p="": next(suite)),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            todo._dolibarr_hooks()
        return lances

    def test_list_at_the_pin_with_a_filter(self):
        self.assertEqual(
            self.lancer_hooks(["1", "", "^thirdparty"]),
            [f"{HOOKS} list --filter '^thirdparty'"],
        )

    def test_list_at_a_version_without_filter(self):
        self.assertEqual(
            self.lancer_hooks(["1", "23.0.4", ""]),
            [f"{HOOKS} list --at 23.0.4"],
        )

    def test_diff_from_a_version_to_the_pin(self):
        self.assertEqual(
            self.lancer_hooks(["2", "23.0.4"]),
            [f"{HOOKS} diff --from 23.0.4"],
        )

    def test_diff_needs_its_starting_version(self):
        self.assertEqual(self.lancer_hooks(["2", ""]), [])


CORE = "./.venv.erplibre/bin/python -u script/dolibarr/core.py"


class TestCoeur(unittest.TestCase):
    def lancer_coeur(self, reponses):
        todo = TODO.__new__(TODO)
        lances = []

        class Execute:
            def exec_command_live(inner, cmd, **kwargs):
                lances.append(cmd)
                return 0

        todo.execute = Execute()
        suite = iter(reponses)
        with (
            mock.patch.object(builtins, "input", lambda p="": next(suite)),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            todo._dolibarr_core()
        return lances

    def test_each_action(self):
        for choix, fin in (("1", "status"), ("3", "check"), ("4", "patches")):
            self.assertEqual(self.lancer_coeur([choix]), [f"{CORE} {fin}"])

    def test_start_asks_for_the_topic(self):
        self.assertEqual(
            self.lancer_coeur(["2", "fix-total"]),
            [f"{CORE} start --topic fix-total"],
        )
        self.assertEqual(self.lancer_coeur(["2", ""]), [])


API = "./.venv.erplibre/bin/python -u script/dolibarr/api.py"


class TestApi(Banc):
    def lancer_api(self, reponses):
        todo = TODO.__new__(TODO)
        lances = []

        class Execute:
            def exec_command_live(inner, cmd, **kwargs):
                lances.append(cmd)
                return 0

        todo.execute = Execute()
        suite = iter(reponses)
        with (
            mock.patch.object(builtins, "input", lambda p="": next(suite)),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            todo._dolibarr_api()
        return lances

    def test_each_action_on_a_development_instance(self):
        self.registre = {"erp": dict(DEV)}
        for choix, fin in (
            ("1", "enable --instance erp"),
            ("2", "status --instance erp"),
            ("3", "enable --instance erp --rotate"),
            ("4", "disable --instance erp"),
        ):
            self.assertEqual(self.lancer_api([choix]), [f"{API} {fin}"])

    def test_a_production_needs_its_name_to_change(self):
        self.registre = {"erp": dict(DEV, mode="prod")}
        self.assertEqual(
            self.lancer_api(["1", "erp"]),
            [f"{API} enable --instance erp --confirm erp"],
        )
        self.assertEqual(self.lancer_api(["1", "er"]), [])
        self.assertEqual(
            self.lancer_api(["2"]), [f"{API} status --instance erp"]
        )


class TestBilan(unittest.TestCase):
    def test_every_instance_is_checked_at_once(self):
        todo = TODO.__new__(TODO)
        lances = []

        class Execute:
            def exec_command_live(inner, cmd, **kwargs):
                lances.append(cmd)
                return 1

        todo.execute = Execute()
        with contextlib.redirect_stdout(io.StringIO()):
            todo._dolibarr_doctor()
        self.assertEqual(lances, [f"{DOCTOR} --all"])


class TestDetection(unittest.TestCase):
    def lancer(self, alias, reponses):
        todo = TODO.__new__(TODO)
        lances = []

        class Execute:
            def exec_command_live(inner, cmd, **kwargs):
                lances.append(cmd)
                return 0

        todo.execute = Execute()
        suite = iter(reponses)
        with (
            mock.patch.object(
                TODO, "_ssh_config_hosts", staticmethod(lambda: list(alias))
            ),
            mock.patch.object(builtins, "input", lambda p="": next(suite)),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            todo._dolibarr_detect()
        return lances

    def test_this_machine(self):
        self.assertEqual(self.lancer([], ["1"]), [f"{DETECT} --local"])

    def test_one_host_of_the_ssh_config(self):
        lances = self.lancer(["hote-a", "hote-b"], ["4"])
        self.assertEqual(lances, [f"{DETECT} --ssh hote-b"])

    def test_every_host_of_the_ssh_config(self):
        lances = self.lancer(["hote-a", "hote-b"], ["2"])
        self.assertEqual(lances, [f"{DETECT} --ssh hote-a --ssh hote-b"])

    def test_an_alias_is_quoted_for_the_shell(self):
        lances = self.lancer(["a b"], ["3"])
        self.assertEqual(lances, [f"{DETECT} --ssh 'a b'"])

    def test_back_runs_nothing(self):
        self.assertEqual(self.lancer(["hote-a"], ["0"]), [])


PIN = "./.venv.erplibre/bin/python -u script/dolibarr/pin.py"
SYNC = "./script/manifest/update_manifest_local_dolibarr.sh"


class TestEpinglage(unittest.TestCase):
    def lancer(self, codes, reponses):
        todo = TODO.__new__(TODO)
        lances = []
        suite_codes = iter(codes)

        class Execute:
            def exec_command_live(inner, cmd, **kwargs):
                lances.append(cmd)
                return next(suite_codes)

        todo.execute = Execute()
        suite = iter(reponses)
        with (
            mock.patch.object(builtins, "input", lambda *a: next(suite)),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            todo._dolibarr_pin()
        return lances

    def test_the_menu_and_pin_py_agree_on_the_pending_code(self):
        from script.dolibarr import pin

        self.assertEqual(dolibarr_menu.PIN_PENDING, pin.PENDING)

    def test_nothing_pending_asks_nothing(self):
        self.assertEqual(self.lancer([0], []), [f"{PIN} update"])

    def test_pending_changes_apply_then_sync_on_yes(self):
        self.assertEqual(
            self.lancer([3, 0, 0], ["y", "y"]),
            [f"{PIN} update", f"{PIN} update --apply", SYNC],
        )

    def test_no_writes_nothing(self):
        self.assertEqual(self.lancer([3], ["n"]), [f"{PIN} update"])

    def test_a_failed_apply_does_not_sync(self):
        self.assertEqual(
            self.lancer([3, 1], ["y"]),
            [f"{PIN} update", f"{PIN} update --apply"],
        )


class TestExecuteMenu(unittest.TestCase):
    def test_the_execute_menu_leads_to_dolibarr(self):
        self.assertEqual(
            menus.TestExecuteMenuNumbering.EXPECTED.get("Dolibarr"),
            "prompt_execute_dolibarr",
        )
        self.assertEqual(
            TODO._MENU_LABELS.get("prompt_execute_dolibarr"), "Dolibarr"
        )


if __name__ == "__main__":
    unittest.main()
