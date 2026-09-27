#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le menu Installation de TODO : l'ordre des questions et ce qu'il lance.

Le choix se pose AVANT l'étape système. « First system installation? »
installe la pile de l'OS pour Odoo (update_env_version.py --install) ; posée
en premier, elle l'installait aussi pour qui ne voulait qu'une autre
technologie. Elle vient donc juste après le choix, pour les choix qui en ont
besoin.

Rien n'est installé ici : input() répond d'après une liste écrite d'avance,
subprocess.run et exec_command_live sont remplacés par des enregistreurs.
"""

import builtins
import contextlib
import io
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

from script.todo import dolibarr_menu, todo_i18n  # noqa: E402
from script.todo import todo as todo_module  # noqa: E402
from script.todo.todo import TODO  # noqa: E402

QUESTION_SYSTEME = "First system installation?"


class ExecuteFactice:
    def __init__(self):
        self.commandes = []

    def exec_command_live(self, cmd, **kwargs):
        self.commandes.append(cmd)
        return 0


class Banc(unittest.TestCase):
    def jouer(self, reponses):
        """Lance prompt_install ; rend (questions posées, commandes lancées).

        Une question de plus que de réponses fait échouer le test en le
        disant, au lieu d'un StopIteration anonyme.
        """
        todo = TODO.__new__(TODO)
        todo.execute = ExecuteFactice()
        questions = []
        suite = iter(reponses)

        def repondre(prompt=""):
            questions.append(prompt)
            try:
                return next(suite)
            except StopIteration:
                raise AssertionError(
                    f"question sans réponse prévue : {prompt!r}"
                ) from None

        lances = []

        def run(cmd, *args, **kwargs):
            lances.append(cmd)
            # « which pycharm » échoue : pas de question PyCharm ici.
            code = 1 if isinstance(cmd, list) and cmd[:1] == ["which"] else 0
            return subprocess.CompletedProcess(cmd, code, "", "")

        with (
            mock.patch.object(builtins, "input", repondre),
            mock.patch.object(todo_module.subprocess, "run", run),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            todo.prompt_install()
        commandes = todo.execute.commandes + [
            c for c in lances if isinstance(c, str)
        ]
        return questions, commandes


PIN = {
    "version": "24.0.1",
    "branch": "24.0",
    "docker_image": "dolibarr/dolibarr:24.0.0",
    "mariadb_image": "mariadb:11.4",
    "tools_image": "docker.io/library/composer:2",
    "php_min": "7.2",
    "php_max": "8.5",
    # Commit inventé.
    "commit": "0123456789abcdef0123456789abcdef01234567",
    "path": "dolibarr/dolibarr",
}

FAITS_LINUX = {
    "system": "Linux",
    "family": "apt-get",
    "is_nixos": False,
    "has_systemd": True,
    "engine_usable": True,
}


# Ce que lib_dolibarr livre vraiment, lu avant que BancDolibarr ne le
# remplace pour exercer toutes les voies.
AVAILABLE_REEL = dolibarr_menu.lib_dolibarr.AVAILABLE


class BancDolibarr(Banc):
    """Épinglage, faits de l'hôte, registre et port sont injectés."""

    def setUp(self):
        self.faits = dict(FAITS_LINUX)
        self.registre = {}
        self.code = 0
        self.mots_de_passe = []
        patches = [
            # Toutes les voies, pour exercer tout le parcours ; ce qui est
            # livré aujourd'hui se teste à part (TestVoiesLivrees).
            mock.patch.object(
                dolibarr_menu.lib_dolibarr,
                "AVAILABLE",
                frozenset(
                    (m, r)
                    for m in ("dev", "prod")
                    for r in ("native", "container")
                ),
            ),
            mock.patch.object(
                dolibarr_menu.lib_dolibarr, "read_pin", lambda root: dict(PIN)
            ),
            mock.patch.object(
                dolibarr_menu.lib_dolibarr,
                "load_registry",
                lambda root: self.registre,
            ),
            mock.patch.object(
                TODO, "_dolibarr_host_facts", lambda s: dict(self.faits)
            ),
            mock.patch.object(
                TODO, "_dolibarr_port_is_free", lambda s, p: True
            ),
            mock.patch.object(TODO, "_dolibarr_python_ready", lambda s: True),
            mock.patch.object(
                dolibarr_menu.getpass,
                "getpass",
                lambda prompt="": self.mots_de_passe.pop(0),
            ),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def dolibarr(self, reponses):
        """Lance prompt_install_dolibarr ; rend (questions, appels, sortie)."""
        todo = TODO.__new__(TODO)
        appels = []

        class Execute:
            def exec_command_live(inner, cmd, **kwargs):
                appels.append((cmd, kwargs))
                return self.code

        todo.execute = Execute()
        questions = []
        suite = iter(reponses)

        def repondre(prompt=""):
            questions.append(prompt)
            try:
                return next(suite)
            except StopIteration:
                raise AssertionError(
                    f"question sans réponse prévue : {prompt!r}"
                ) from None

        sortie = io.StringIO()
        with (
            mock.patch.object(builtins, "input", repondre),
            contextlib.redirect_stdout(sortie),
        ):
            todo.prompt_install_dolibarr()
        return questions, appels, sortie.getvalue()


class TestEntreeDolibarr(BancDolibarr):
    def menu(self, reponses):
        questions, commandes = self.jouer(reponses)
        return questions[0], commandes

    def test_dolibarr_is_the_last_entry_numbered_after_odoo(self):
        with mock.patch.object(TODO, "prompt_install_dolibarr"):
            ecran, _ = self.menu(["0"])
        lignes = [ligne.strip() for ligne in ecran.splitlines()]
        odoo = [x for x in lignes if re.match(r"^\d+: Odoo ", x)]
        entrees = [x for x in lignes if re.match(r"^\w+: ", x)]
        attendu = f"{len(odoo) + 1}: Dolibarr 24.0.1 (0123456)"
        self.assertTrue(entrees[-1].startswith(attendu), entrees[-1])

    def test_choosing_it_skips_the_system_and_extra_questions(self):
        with mock.patch.object(TODO, "prompt_install_dolibarr") as appel:
            ecran, _ = self.menu(["0"])
            cle = re.search(r"(\d+): Dolibarr", ecran).group(1)
            questions, commandes = self.jouer([cle])
        appel.assert_called_once_with()
        self.assertEqual(len(questions), 1)
        self.assertEqual(commandes, [])

    def test_an_existing_checkout_is_labelled_installed(self):
        with tempfile.TemporaryDirectory() as racine:
            htdocs = Path(racine, "dolibarr", "dolibarr", "htdocs")
            htdocs.mkdir(parents=True)
            (htdocs / "version.inc.php").write_text("<?php\n")
            with (
                mock.patch.object(dolibarr_menu, "ROOT", racine),
                mock.patch.object(TODO, "prompt_install_dolibarr"),
            ):
                ecran, _ = self.menu(["0"])
        self.assertRegex(
            ecran, r"\d+: Dolibarr 24\.0\.1 \(0123456\) - Installed"
        )

    def test_an_unreadable_pin_hides_the_entry_and_says_why(self):
        def refuse(root):
            raise dolibarr_menu.lib_dolibarr.PinError("manifest absent")

        with (
            mock.patch.object(dolibarr_menu.lib_dolibarr, "read_pin", refuse),
            mock.patch.object(TODO, "prompt_install_dolibarr") as appel,
        ):
            ecran, _ = self.menu(["0"])
        self.assertNotIn("Dolibarr 24", ecran)
        appel.assert_not_called()


class TestParcoursDolibarr(BancDolibarr):
    NATIF_DEV = (
        "./.venv.erplibre/bin/python -u script/dolibarr/install_native.py"
        " --mode dev --instance dolibarr --db mariadb --port 8080"
        " --admin-login admin"
    )

    def test_defaults_run_the_native_development_install(self):
        # dev, natif, MariaDB, nom, port et login par défaut, mot de passe
        # vide (généré), confirmation.
        self.mots_de_passe = [""]
        _q, appels, _s = self.dolibarr(["1", "1", "1", "", "", "", "y"])
        self.assertEqual(len(appels), 1)
        cmd, kwargs = appels[0]
        self.assertEqual(cmd, self.NATIF_DEV)
        self.assertFalse(kwargs.get("source_erplibre"))
        self.assertFalse(kwargs.get("new_env"))

    def test_back_at_the_environment_runs_nothing(self):
        _q, appels, _s = self.dolibarr(["0"])
        self.assertEqual(appels, [])

    def test_back_at_the_runtime_runs_nothing(self):
        _q, appels, _s = self.dolibarr(["1", "0"])
        self.assertEqual(appels, [])

    def test_the_container_asks_no_database_and_says_why(self):
        self.mots_de_passe = [""]
        _q, appels, sortie = self.dolibarr(["1", "2", "", "", "", "y"])
        self.assertIn("script/dolibarr/install_container.py", appels[0][0])
        self.assertNotIn("--db", appels[0][0])
        self.assertIn("MariaDB", sortie)

    def test_an_unavailable_native_is_not_listed_and_its_reason_shown(self):
        self.faits.update(system="Linux", family=None, is_nixos=True)
        self.mots_de_passe = [""]
        questions, appels, sortie = self.dolibarr(["1", "1", "", "", "", "y"])
        # Le seul runtime listé est le conteneur, et il porte le numéro 1.
        self.assertNotIn("nginx + PHP-FPM", questions[1])
        self.assertIn("services.dolibarr", sortie)
        self.assertIn("install_container.py", appels[0][0])

    def test_nothing_available_returns_after_the_reasons(self):
        self.faits.update(system="Windows", family=None, engine_usable=False)
        _q, appels, sortie = self.dolibarr(["1"])
        self.assertEqual(appels, [])
        self.assertIn("Docker Desktop", sortie)

    def test_a_typed_password_goes_to_the_environment(self):
        secret = "mot-de-passe-inventé"
        self.mots_de_passe = [secret, secret]
        _q, appels, sortie = self.dolibarr(["1", "1", "1", "", "", "", "y"])
        cmd, kwargs = appels[0]
        self.assertNotIn(secret, cmd)
        self.assertNotIn(secret, sortie)
        self.assertEqual(
            kwargs.get("new_env"), {"EL_DOLIBARR_ADMIN_PASSWORD": secret}
        )

    def test_differing_passwords_are_asked_again(self):
        self.mots_de_passe = ["un-inventé", "autre-inventé", "bon-a", "bon-a"]
        _q, appels, _s = self.dolibarr(["1", "1", "1", "", "", "", "y"])
        self.assertEqual(
            appels[0][1].get("new_env"),
            {"EL_DOLIBARR_ADMIN_PASSWORD": "bon-a"},
        )

    def test_an_existing_instance_is_refused(self):
        self.registre = {"dolibarr": {"mode": "dev"}}
        _q, appels, _s = self.dolibarr(["1", "1", "1", ""])
        self.assertEqual(appels, [])

    def test_an_invalid_name_is_asked_again(self):
        self.mots_de_passe = [""]
        _q, appels, _s = self.dolibarr(
            ["1", "1", "1", "Mauvais-Nom", "erp", "", "", "y"]
        )
        self.assertIn("--instance erp", appels[0][0])

    def test_saying_no_at_the_summary_runs_nothing(self):
        self.mots_de_passe = [""]
        _q, appels, _s = self.dolibarr(["1", "1", "1", "", "", "", "n"])
        self.assertEqual(appels, [])

    def test_production_native_asks_a_domain_and_no_port(self):
        self.mots_de_passe = [""]
        # prod, natif, PostgreSQL, nom, domaine, Let's Encrypt, courriel,
        # login, confirmation.
        _q, appels, _s = self.dolibarr(
            [
                "2",
                "1",
                "2",
                "",
                "erp.example.org",
                "1",
                "ops@example.org",
                "",
                "y",
            ]
        )
        cmd = appels[0][0]
        self.assertIn("--mode prod", cmd)
        self.assertIn("--db postgresql", cmd)
        self.assertIn("--domain erp.example.org --tls certbot", cmd)
        self.assertIn("--email ops@example.org", cmd)
        self.assertNotIn("--port", cmd)

    def test_production_native_asks_the_domain_until_it_is_valid(self):
        # Le natif sert par nginx sous ce nom : l'installateur refuse de
        # partir sans lui, le menu ne le laisse donc ni vide ni invalide.
        self.mots_de_passe = [""]
        questions, appels, sortie = self.dolibarr(
            ["2", "1", "1", "", "", "a b.org", "ERP.Example.org", "2", "", "y"]
        )
        domaine = todo_i18n.t("Domain name (e.g.: example.com): ")
        self.assertEqual(questions.count(domaine), 3)
        self.assertIn(
            todo_i18n.t(
                "Invalid domain name: letters, digits, dots and hyphens."
            ),
            sortie,
        )
        self.assertIn("--domain erp.example.org --tls local", appels[0][0])

    def test_a_failed_install_says_so(self):
        self.code = 3
        self.mots_de_passe = [""]
        _q, _a, sortie = self.dolibarr(["1", "1", "1", "", "", "", "y"])
        self.assertIn(
            todo_i18n.t("Installation failed, see the output above."), sortie
        )

    def test_an_unknown_answer_is_asked_again(self):
        self.mots_de_passe = [""]
        questions, appels, sortie = self.dolibarr(
            ["1", "9", "1", "1", "", "", "", "y"]
        )
        self.assertIn("'9'", sortie)
        self.assertEqual(appels[0][0], self.NATIF_DEV)

    def test_a_missing_tool_venv_is_built_before_the_install(self):
        self.mots_de_passe = [""]
        with mock.patch.object(
            TODO, "_dolibarr_python_ready", lambda s: False
        ):
            _q, appels, _s = self.dolibarr(["1", "1", "1", "", "", "", "y"])
        self.assertEqual(
            [cmd for cmd, _kw in appels],
            ["./script/install/install_erplibre.sh", self.NATIF_DEV],
        )

    def test_a_failed_venv_build_stops_before_the_install(self):
        self.code = 1
        self.mots_de_passe = [""]
        with mock.patch.object(
            TODO, "_dolibarr_python_ready", lambda s: False
        ):
            _q, appels, _s = self.dolibarr(["1", "1", "1", "", "", "", "y"])
        self.assertEqual(
            [cmd for cmd, _kw in appels],
            ["./script/install/install_erplibre.sh"],
        )


class TestVoiesLivrees(BancDolibarr):
    """Seules les voies livrées sont offertes : pas de choix mort."""

    def setUp(self):
        super().setUp()
        p = mock.patch.object(
            dolibarr_menu.lib_dolibarr, "AVAILABLE", AVAILABLE_REEL
        )
        p.start()
        self.addCleanup(p.stop)

    def test_development_offers_native_and_containers(self):
        self.mots_de_passe = [""]
        questions, appels, _s = self.dolibarr(["1", "1", "1", "", "", "", "y"])
        self.assertIn("dolibarr/dolibarr", questions[1])
        self.assertIn("install_native.py --mode dev", appels[0][0])

    def test_a_development_container_takes_no_database_question(self):
        self.mots_de_passe = [""]
        _q, appels, _s = self.dolibarr(["1", "2", "", "", "", "y"])
        self.assertEqual(
            appels[0][0],
            "./.venv.erplibre/bin/python -u script/dolibarr/install_container.py"
            " --mode dev --instance dolibarr --port 8080 --admin-login admin",
        )

    def test_production_offers_native_behind_a_domain(self):
        self.mots_de_passe = [""]
        questions, appels, _s = self.dolibarr(
            ["2", "1", "1", "", "erp.example.org", "3", "", "y"]
        )
        self.assertIn("Production", questions[0])
        self.assertNotIn("dolibarr/dolibarr", questions[1])
        self.assertIn(
            "install_native.py --mode prod --instance dolibarr --db mariadb"
            " --domain erp.example.org --tls none",
            appels[0][0],
        )


class TestOrdreDesQuestions(Banc):
    def test_the_choice_comes_before_the_system_question(self):
        questions, commandes = self.jouer(["0"])
        self.assertEqual(len(questions), 1)
        self.assertNotIn(QUESTION_SYSTEME, questions[0])
        self.assertEqual(commandes, [])

    def test_an_odoo_version_still_asks_the_system_question_after(self):
        questions, commandes = self.jouer(["1", "y", "1"])
        self.assertNotIn(QUESTION_SYSTEME, questions[0])
        self.assertIn(QUESTION_SYSTEME, questions[1])
        self.assertIn(
            "./script/version/update_env_version.py --install", commandes
        )
        self.assertTrue(
            any("--install_dev" in c for c in commandes), commandes
        )

    def test_erplibre_only_keeps_the_system_question(self):
        questions, commandes = self.jouer(["q", "n"])
        self.assertIn(QUESTION_SYSTEME, questions[1])
        self.assertEqual(commandes, ["./script/install/install_erplibre.sh"])


if __name__ == "__main__":
    unittest.main()
