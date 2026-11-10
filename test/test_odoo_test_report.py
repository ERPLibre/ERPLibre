#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le verdict de chaque test d'un module Odoo, poussé vers le registre.

Aucun test ne lance Odoo ni n'ouvre de connexion. Le journal analysé est
celui de vrais passages d'Odoo 18 en `--log-level=test`, gardés dans
test/fixtures/odoo_test_log/ avec leurs chemins, leur base et leur compte
remplacés par des valeurs inventées : un module de démonstration aux
tests réussi, en échec, en erreur, ignoré, en sous-test, en post_install et
en erreur de setUpClass (verdicts.txt), un module tout vert (green.txt) et
un module dont les tests ne s'importent pas (install_error.txt). Odoo
lui-même est remplacé par un exécutant qui rend ces journaux, et
`urllib.request.urlopen` par le faux registre de test_requirement_report.
"""

import io
import os
import re
import sys
import tempfile
import unittest
import urllib.error
from unittest import mock

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RACINE, "script", "test"))
sys.path.insert(0, os.path.join(RACINE, "test"))

import odoo_test_report as otr  # noqa: E402
import requirement_report as rr  # noqa: E402
from test_requirement_report import CLE, ENV, FauxRegistre  # noqa: E402

FIXTURES = os.path.join(RACINE, "test", "fixtures", "odoo_test_log")

DEMO = "odoo.addons.demo_test_verdicts.tests."
VERDICTS = DEMO + "test_verdicts.TestVerdicts."
SETUP = DEMO + "test_setup_error.TestSetupError."
POST = DEMO + "test_post_install.TestPostInstall."
CASSE = "odoo.addons.demo_test_broken.tests.test_broken.TestBroken."


def journal(nom):
    with open(os.path.join(FIXTURES, nom), encoding="utf-8") as fh:
        return fh.read().splitlines(keepends=True)


class TestLeJournal(unittest.TestCase):
    """parse_odoo_test_log et analyser sur de vrais journaux d'Odoo."""

    def test_each_outcome_of_a_real_run_reaches_its_reference(self):
        verdicts = otr.parse_odoo_test_log(journal("verdicts.txt"))
        self.assertEqual(
            {cle: v["result"] for cle, v in verdicts.items()},
            {
                VERDICTS + "test_pass": "passed",
                VERDICTS + "test_fail": "failed",
                VERDICTS + "test_error": "error",
                VERDICTS + "test_skip": "skipped",
                VERDICTS + "test_subtest": "failed",
                POST + "test_after_install": "passed",
                # La fixture de classe n'a pas de méthode : sa clé est le
                # PRÉFIXE de la classe, que chaque méthode déclarée reçoit.
                SETUP: "error",
            },
        )
        self.assertIsNone(verdicts[VERDICTS + "test_pass"]["log"])
        self.assertIn(
            "deliberate failure", verdicts[VERDICTS + "test_fail"]["log"]
        )
        self.assertIn(
            "RuntimeError: deliberate error",
            verdicts[VERDICTS + "test_error"]["log"],
        )
        self.assertEqual(
            verdicts[VERDICTS + "test_skip"]["log"], "deliberate skip"
        )
        self.assertIn("(i=1)", verdicts[VERDICTS + "test_subtest"]["log"])
        self.assertIn("deliberate setUpClass error", verdicts[SETUP]["log"])
        # Le journal d'un échec ne déborde pas sur la ligne suivante.
        self.assertNotIn("Starting", verdicts[VERDICTS + "test_fail"]["log"])

    def test_durations_come_from_the_detailed_report(self):
        verdicts = otr.parse_odoo_test_log(journal("verdicts.txt"))
        self.assertEqual(verdicts[SETUP]["duration"], 0.04)
        self.assertEqual(verdicts[VERDICTS + "test_pass"]["duration"], 0.0)
        lignes = journal("verdicts.txt")
        lignes = [
            x.replace(
                "TestVerdicts.test_pass: 0.00s",
                "TestVerdicts.test_pass: 1.25s",
            )
            for x in lignes
        ]
        verdicts = otr.parse_odoo_test_log(lignes)
        self.assertEqual(verdicts[VERDICTS + "test_pass"]["duration"], 1.25)

    def test_the_summary_line_marks_a_run_that_reached_its_end(self):
        self.assertEqual(otr.analyser(journal("verdicts.txt")).fin, (2, 2, 6))
        self.assertEqual(otr.analyser(journal("green.txt")).fin, (0, 0, 1))
        self.assertIsNone(otr.analyser(journal("install_error.txt")).fin)

    def test_an_install_error_notes_no_test_and_keeps_its_trace(self):
        analyse = otr.analyser(journal("install_error.txt"))
        self.assertEqual(analyse.verdicts, {})
        self.assertIn("ModuleNotFoundError", analyse.erreurs)
        self.assertIn("Failed to initialize database", analyse.erreurs)

    def test_lines_that_are_not_test_results_give_no_verdict(self):
        lignes = [
            "2026-11-10 12:00:00,000 1 INFO base odoo.service.server:"
            " Starting post tests \n",
            "2026-11-10 12:00:00,001 1 ERROR base"
            " odoo.addons.demo.tests.test_x: une erreur journalisée\n",
            "2026-11-10 12:00:00,002 1 INFO base"
            " odoo.addons.demo.models.x: Starting X.y ... \n",
            "une ligne sans en-tête\n",
        ]
        self.assertEqual(otr.parse_odoo_test_log(lignes), {})

    def test_trailing_spaces_and_crlf_do_not_change_the_reading(self):
        brut = journal("verdicts.txt")
        nettoye = [x.rstrip() + " \r\n" for x in brut]
        self.assertEqual(
            otr.parse_odoo_test_log(brut), otr.parse_odoo_test_log(nettoye)
        )


class TestLeCodeDeSortie(unittest.TestCase):
    def code(self, nom, rc):
        return otr.code_de_sortie(rc, otr.analyser(journal(nom)))

    def test_green_is_zero_a_failure_one_a_setup_error_two(self):
        self.assertEqual(self.code("green.txt", 0), 0)
        self.assertEqual(self.code("verdicts.txt", 1), 1)
        self.assertEqual(self.code("install_error.txt", 255), 2)

    def test_a_run_that_ran_no_test_proved_nothing(self):
        lignes = [
            "2026-11-10 12:00:00,000 1 WARNING base odoo.tests.result:"
            " 0 failed, 0 error(s) of 0 tests when loading database 'b' \n"
        ]
        self.assertEqual(otr.code_de_sortie(0, otr.analyser(lignes)), 2)

    def test_a_run_without_its_summary_is_a_setup_error(self):
        lignes = journal("green.txt")
        lignes = [x for x in lignes if "when loading database" not in x]
        self.assertEqual(otr.code_de_sortie(0, otr.analyser(lignes)), 2)


class TestLaConfiguration(unittest.TestCase):
    SOURCE = (
        "[options]\n"
        "addons_path = /srv/invented-a,/srv/invented-b\n"
        "admin_passwd = secret-invente\n"
        "db_host = False\n"
        "db_port = 5433\n"
        "db_user = invente\n"
        "db_password = mdp-invente\n"
        "db_name = base-de-tous-les-jours\n"
        "dbfilter = .*\n"
        "http_port = 8069\n"
        "list_db = True\n"
        "workers = 4\n"
        "logfile = /srv/invented-log/odoo.log\n"
    )

    def lire(self, texte):
        import configparser

        lu = configparser.ConfigParser(interpolation=None)
        lu.read_string(texte)
        return dict(lu["options"])

    def test_only_addons_and_database_access_come_from_the_checkout(self):
        options = self.lire(
            otr.configuration(self.SOURCE, "/srv/invented-data", 41001, 41002)
        )
        self.assertEqual(
            options,
            {
                "addons_path": "/srv/invented-a,/srv/invented-b",
                "db_port": "5433",
                "db_user": "invente",
                "db_password": "mdp-invente",
                "data_dir": "/srv/invented-data",
                "http_enable": "True",
                "http_interface": "127.0.0.1",
                "http_port": "41001",
                "gevent_port": "41002",
                "list_db": "False",
                "workers": "0",
                "max_cron_threads": "0",
            },
        )

    def test_a_checkout_config_without_addons_path_is_refused(self):
        with self.assertRaises(otr.ConfigurationInvalide):
            otr.configuration("[options]\ndb_user = x\n", "/d", 1, 2)

    def test_free_ports_avoid_the_ports_in_use_on_the_station(self):
        for _ in range(20):
            http, gevent = otr.ports_libres()
            self.assertNotEqual(http, gevent)
            self.assertFalse({http, gevent} & otr.PORTS_RESERVES)
        self.assertTrue(
            {8016, 8017, 8018, 8069, 8072, 8080} <= otr.PORTS_RESERVES
        )

    def test_a_reserved_or_repeated_port_is_drawn_again(self):
        """Le système peut rendre n'importe quel port libre : un port
        réservé, ou celui déjà tiré, ne sort jamais."""
        tirages = iter([8069, 41001, 41001, 8072, 41002])
        sonde = mock.MagicMock()
        sonde.__enter__.return_value.getsockname.side_effect = lambda: (
            "127.0.0.1",
            next(tirages),
        )
        with mock.patch.object(otr.socket, "socket", return_value=sonde):
            self.assertEqual(otr.ports_libres(), (41001, 41002))

    def test_the_command_runs_only_the_tests_of_the_modules(self):
        commande = otr.commande_odoo(
            "/v/python", "/o/odoo-bin", "/t/odoo.conf", "b", ["m1", "m2"]
        )
        self.assertEqual(
            commande,
            [
                "/v/python",
                "/o/odoo-bin",
                "-c",
                "/t/odoo.conf",
                "-d",
                "b",
                "-i",
                "m1,m2",
                "--test-tags",
                "/m1,/m2",
                "--stop-after-init",
                "--log-level=test",
                "--log-handler=odoo.tests.stats:DEBUG",
            ],
        )

    def test_odoo_never_inherits_the_registry_key_nor_test_retries(self):
        env = dict(ENV, ODOO_TEST_FAILURE_RETRIES="2", LANG="C.UTF-8")
        env["ODOO_TEST_MAX_FAILED_TESTS"] = "1"
        propre = otr.environnement_odoo(env)
        self.assertEqual(propre, {"LANG": "C.UTF-8"})


class FauxOdoo:
    """Exécutant d'Odoo : rend `journal` et `rc` pour le lancement des
    tests, 0 pour la suppression de la base, et garde chaque commande avec
    son environnement. `interruption` : lève KeyboardInterrupt au
    lancement des tests."""

    def __init__(self, nom="verdicts.txt", rc=1, interruption=False):
        self.lignes = journal(nom)
        self.rc = rc
        self.interruption = interruption
        self.commandes = []
        self.configurations = []

    def __call__(self, commande, env, sortie=None):
        self.commandes.append((commande, env))
        conf = commande[commande.index("-c") + 1]
        with open(conf, encoding="utf-8") as fh:
            self.configurations.append(fh.read())
        if "drop" in commande:
            return 0, []
        if self.interruption:
            raise KeyboardInterrupt
        if sortie is not None:
            sortie.writelines(self.lignes)
        return self.rc, self.lignes

    def base(self):
        commande = self.commandes[0][0]
        return commande[commande.index("-d") + 1]

    def suppressions(self):
        return [c for c, _ in self.commandes if "drop" in c]


class TestLeLanceur(unittest.TestCase):
    """principal : une racine provisoire tient lieu de dépôt, avec son
    config.conf, ses fichiers de version et un addons_path qui porte les
    modules de démonstration."""

    MODULES = ("demo_test_verdicts", "demo_test_broken", "demo_test_green")

    def setUp(self):
        self._dossier = tempfile.TemporaryDirectory()
        self.racine = self._dossier.name
        self.addCleanup(self._dossier.cleanup)
        addons = os.path.join(self.racine, "addons")
        for module in self.MODULES:
            os.makedirs(os.path.join(addons, module))
            with open(
                os.path.join(addons, module, "__manifest__.py"), "w"
            ) as fh:
                fh.write("{}\n")
        with open(os.path.join(self.racine, "config.conf"), "w") as fh:
            fh.write(f"[options]\naddons_path = {addons}\ndb_user = x\n")
        for nom, valeur in (
            (".odoo-version", "18.0"),
            (".erplibre-version", "odoo18.0_python3.12.10"),
        ):
            with open(os.path.join(self.racine, nom), "w") as fh:
                fh.write(valeur + "\n")
        for chemin in (
            ".venv.odoo18.0_python3.12.10/bin/python",
            "odoo18.0/odoo/odoo-bin",
        ):
            chemin = os.path.join(self.racine, chemin)
            os.makedirs(os.path.dirname(chemin))
            open(chemin, "w").close()
        self.temporaire = os.path.join(self.racine, "tmp")
        os.mkdir(self.temporaire)

    def lancer(self, args, faux, env=None, reseau=None):
        """(code, sortie, reseau) de principal(args). `reseau` remplace
        urlopen ; par défaut, toute connexion est refusée."""
        sortie = io.StringIO()
        if reseau is None:
            reseau = mock.Mock(side_effect=urllib.error.URLError("refusé"))
        # Le journal est celui d'un passage dans CE dépôt : ses chemins
        # portent la racine provisoire.
        faux.lignes = [
            x.replace("/srv/invented-erplibre", self.racine)
            for x in faux.lignes
        ]
        with (
            mock.patch("urllib.request.urlopen", reseau),
            mock.patch("tempfile.tempdir", self.temporaire),
        ):
            code = otr.principal(
                args,
                env={} if env is None else env,
                racine=self.racine,
                executer=faux,
                sortie=sortie,
            )
        return code, sortie.getvalue(), reseau

    def test_unset_environment_opens_no_connection_and_adds_no_line(self):
        faux = FauxOdoo()
        code, sortie, reseau = self.lancer(
            ["--modules", "demo_test_verdicts"], faux
        )
        self.assertEqual(code, 1)
        reseau.assert_not_called()
        self.assertNotIn("Registre", sortie)
        # Avec le registre, la sortie est la même, plus sa seule ligne.
        faux_registre = FauxRegistre()
        _, avec, _ = self.lancer(
            ["--modules", "demo_test_verdicts"],
            FauxOdoo(),
            env=ENV,
            reseau=faux_registre,
        )
        sans_base = re.compile(r"erplibre_odoo_test_[0-9a-f]+")
        self.assertEqual(
            [
                sans_base.sub("B", x)
                for x in avec.splitlines()
                if "Registre" not in x
            ],
            [sans_base.sub("B", x) for x in sortie.splitlines()],
        )
        self.assertEqual(len(avec.splitlines()) - len(sortie.splitlines()), 1)

    def test_the_run_uses_a_throwaway_database_and_drops_it(self):
        faux = FauxOdoo()
        code, sortie, _ = self.lancer(
            ["--modules", "demo_test_verdicts"], faux
        )
        base = faux.base()
        self.assertRegex(base, r"^erplibre_odoo_test_[0-9a-f]{8,}$")
        self.assertEqual(len(faux.suppressions()), 1)
        suppression = faux.suppressions()[0]
        self.assertEqual(suppression[-2:], ["drop", base])
        self.assertEqual(suppression[2], "db")
        # La configuration générée ne survit pas au passage.
        self.assertEqual(os.listdir(self.temporaire), [])
        conf = faux.configurations[0]
        self.assertIn("list_db = False", conf)
        self.assertIn("http_interface = 127.0.0.1", conf)

    def test_keep_db_keeps_the_database_and_names_it(self):
        faux = FauxOdoo("green.txt", rc=0)
        code, sortie, _ = self.lancer(
            ["--modules", "demo_test_green", "--keep-db"], faux
        )
        self.assertEqual(code, 0)
        self.assertEqual(faux.suppressions(), [])
        self.assertIn(faux.base(), sortie)

    def test_the_database_is_dropped_when_odoo_fails_or_is_interrupted(self):
        for faux, attendu in (
            (FauxOdoo("install_error.txt", rc=255), 2),
            (FauxOdoo(interruption=True), 130),
        ):
            with self.subTest(attendu=attendu):
                code, _, reseau = self.lancer(
                    ["--modules", "demo_test_verdicts"], faux, env=ENV
                )
                self.assertEqual(code, attendu)
                self.assertEqual(len(faux.suppressions()), 1)
                if attendu == 130:
                    # Interrompu, le passage ne prouve rien : rien ne part.
                    reseau.assert_not_called()

    def test_an_unknown_module_stops_before_any_database(self):
        faux = FauxOdoo()
        code, sortie, _ = self.lancer(["--modules", "inexistant"], faux)
        self.assertEqual(code, 2)
        self.assertEqual(faux.commandes, [])
        self.assertIn("inexistant", sortie)

    def test_the_summary_lists_what_did_not_pass(self):
        code, sortie, _ = self.lancer(
            ["--modules", "demo_test_verdicts"], FauxOdoo()
        )
        # Le bilan suit la dernière ligne d'Odoo.
        bilan = sortie.rsplit(journal("verdicts.txt")[-1], 1)[-1]
        for attendu in (
            VERDICTS + "test_fail",
            VERDICTS + "test_error",
            VERDICTS + "test_subtest",
            SETUP.rstrip("."),
        ):
            self.assertIn(attendu, bilan)
        self.assertNotIn(VERDICTS + "test_pass", bilan)

    def test_the_push_reads_only_python_lines_of_the_tested_modules(self):
        faux_registre = FauxRegistre(
            declarees=[
                VERDICTS + "test_pass",
                VERDICTS + "test_fail",
                SETUP + "test_never_runs",
                # Renommé ou supprimé : le module a tourné jusqu'au bout.
                VERDICTS + "test_renamed",
            ]
        )
        code, sortie, _ = self.lancer(
            ["--modules", "demo_test_verdicts"],
            FauxOdoo(),
            env=ENV,
            reseau=faux_registre,
        )
        self.assertEqual(code, 1)
        lecture = faux_registre.appels[1][1]["args"]
        self.assertEqual(
            lecture[5],
            [
                [
                    ["kind", "=", "python"],
                    ["reference", "=like", "odoo.addons.demo_test_verdicts.%"],
                ]
            ],
        )
        envois = {
            args[1]: (args[0], args[2]) for args, _ in faux_registre.envois()
        }
        self.assertEqual(
            envois,
            {
                VERDICTS + "test_pass": ("python", "passed"),
                VERDICTS + "test_fail": ("python", "failed"),
                SETUP + "test_never_runs": ("python", "error"),
                VERDICTS + "test_renamed": ("python", "error"),
            },
        )
        journaux = {args[1]: kw["log"] for args, kw in faux_registre.envois()}
        self.assertIn(
            "deliberate setUpClass error", journaux[SETUP + "test_never_runs"]
        )
        self.assertIn(
            "TestVerdicts.test_renamed", journaux[VERDICTS + "test_renamed"]
        )

    def test_two_modules_are_read_in_one_domain(self):
        faux_registre = FauxRegistre()
        self.lancer(
            ["--modules", "demo_test_verdicts,demo_test_green"],
            FauxOdoo(),
            env=ENV,
            reseau=faux_registre,
        )
        self.assertEqual(
            faux_registre.appels[1][1]["args"][5],
            [
                [
                    ["kind", "=", "python"],
                    "|",
                    ["reference", "=like", "odoo.addons.demo_test_verdicts.%"],
                    ["reference", "=like", "odoo.addons.demo_test_green.%"],
                ]
            ],
        )

    def test_an_install_error_errs_the_declared_tests_of_its_module(self):
        faux_registre = FauxRegistre(declarees=[CASSE + "test_unreachable"])
        code, _, _ = self.lancer(
            ["--modules", "demo_test_broken"],
            FauxOdoo("install_error.txt", rc=255),
            env=ENV,
            reseau=faux_registre,
        )
        self.assertEqual(code, 2)
        [(args, kwargs)] = faux_registre.envois()
        self.assertEqual(args, ["python", CASSE + "test_unreachable", "error"])
        self.assertIn("ModuleNotFoundError", kwargs["log"])
        # Le chemin du dépôt part relatif, comme pour les tests unitaires.
        self.assertIn("odoo18.0/odoo/odoo/tests/loader.py", kwargs["log"])
        self.assertNotIn(self.racine, kwargs["log"])

    def test_the_key_is_never_printed_nor_given_to_odoo(self):
        echo = {
            "login": {
                "code": 200,
                "message": "Odoo Server Error",
                "data": {"message": f"clé {CLE} refusée"},
            }
        }
        faux = FauxOdoo()
        _, sortie, _ = self.lancer(
            ["--modules", "demo_test_verdicts"],
            faux,
            env=ENV,
            reseau=FauxRegistre(erreur=echo),
        )
        self.assertNotIn(CLE, sortie)
        self.assertIn("***", sortie)
        for commande, env in faux.commandes:
            self.assertNotIn(CLE, " ".join(commande))
            self.assertNotIn(CLE, " ".join(env.values()))
        for conf in faux.configurations:
            self.assertNotIn(CLE, conf)

    def test_a_failed_push_leaves_the_exit_code_alone(self):
        for nom, rc, attendu in (("green.txt", 0, 0), ("verdicts.txt", 1, 1)):
            with self.subTest(attendu=attendu):
                module = (
                    "demo_test_green"
                    if nom == "green.txt"
                    else "demo_test_verdicts"
                )
                code, sortie, reseau = self.lancer(
                    ["--modules", module], FauxOdoo(nom, rc=rc), env=ENV
                )
                self.assertEqual(code, attendu)
                self.assertEqual(reseau.call_count, 1)
                lignes = [x for x in sortie.splitlines() if "Registre" in x]
                self.assertEqual(len(lignes), 1)


class TestLEnvoiGenerique(unittest.TestCase):
    """Registre.pousser_verdicts, que pousser et ce lanceur partagent."""

    def test_a_prefix_reaches_the_declared_tests_under_it(self):
        faux = FauxRegistre(declarees=["p.C.test_a", "p.C.test_b", "q.D.t"])
        sortie = io.StringIO()
        with mock.patch("urllib.request.urlopen", faux):
            interrompu = rr.Registre(
                "https://registre.invalid", "registre", "lanceur", CLE
            ).pousser_verdicts(
                {
                    "p.C.": {"result": "error", "log": "x", "duration": 0.5},
                    "p.C.test_a": {
                        "result": "passed",
                        "log": None,
                        "duration": 0.1,
                    },
                    # Un préfixe ne déborde pas sur un voisin de même
                    # début : p.C n'est pas p.Cx.
                    "p.Cx.": {"result": "failed", "log": "y", "duration": 0},
                },
                "python",
                "p.%",
                racine="/depot",
                sortie=sortie,
            )
        self.assertFalse(interrompu)
        self.assertEqual(
            sorted((a[1], a[2]) for a, _ in faux.envois()),
            [("p.C.test_a", "error"), ("p.C.test_b", "error")],
        )
        self.assertEqual(len(sortie.getvalue().splitlines()), 1)


if __name__ == "__main__":
    unittest.main()
