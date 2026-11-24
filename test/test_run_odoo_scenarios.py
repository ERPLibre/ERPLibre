#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""run_odoo_scenarios : la campagne des scénarios Odoo, sans Odoo.

« psql » et odoo_bin.sh sont des commandes factices qui listent des bases
inventées et notent ce qu'on leur demande de supprimer ; les dépôts sont
des dépôts git temporaires. Le cache (XDG_CACHE_HOME) et le verrou des
campagnes pointent dans un répertoire temporaire.
"""

import contextlib
import io
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from script.test import couverture
from script.test import lanceur as moteur
from script.test import run_odoo_scenarios as r
from script.test import scenarios_odoo

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUN_ID = "0a1b2c3d"

# Des bases inventées : celles du passage, celles d'un autre passage,
# celles de l'ancien lanceur et une base qui n'a rien à voir.
BASES = [
    f"test_scn_{RUN_ID}_000000000001_scn_a",
    f"test_scn_{RUN_ID}_000000000002_scn_b",
    "test_scn_9f8e7d6c_000000000003_scn_a",
    "test_demo_00000000-1111-2222-3333-444444444444",
    "base_de_travail_fictive",
]


def _env_git():
    return dict(
        os.environ,
        GIT_AUTHOR_NAME="Auteur Fictif",
        GIT_AUTHOR_EMAIL="auteur@fictif.invalid",
        GIT_COMMITTER_NAME="Auteur Fictif",
        GIT_COMMITTER_EMAIL="auteur@fictif.invalid",
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_CONFIG_NOSYSTEM="1",
    )


class Bac(unittest.TestCase):
    """Un répertoire temporaire, le cache dedans, des commandes factices."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="scn_campagne_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        patcher = mock.patch.dict(
            os.environ, {"XDG_CACHE_HOME": os.path.join(self.tmp, "cache")}
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.racine = os.path.join(self.tmp, "racine")
        os.makedirs(self.racine)
        self.bin = os.path.join(self.tmp, "bin")
        os.makedirs(self.bin)
        self.appels = os.path.join(self.tmp, "appels.log")
        self.ecrire_bases(BASES)
        self.odoo_bin = self.script(
            os.path.join(self.racine, "odoo_bin.sh"),
            f'echo "$*" >> {self.appels}\n',
        )

    def script(self, chemin, corps):
        with open(chemin, "w") as fh:
            fh.write("#!/bin/sh\n" + corps)
        os.chmod(chemin, 0o755)
        return chemin

    def ecrire_bases(self, bases, code=0):
        liste = os.path.join(self.tmp, "bases.txt")
        with open(liste, "w") as fh:
            fh.write("".join(b + "\n" for b in bases))
        self.script(
            os.path.join(self.bin, "psql"),
            f"cat {liste}\nexit {code}\n",
        )

    def env_factice(self):
        return {"PATH": self.bin + os.pathsep + os.environ.get("PATH", "")}

    def supprimees(self):
        try:
            with open(self.appels) as fh:
                return [ligne.split()[-1] for ligne in fh if ligne.strip()]
        except OSError:
            return []

    def depot(self, nom, fichiers):
        chemin = os.path.join(self.racine, nom)
        for relatif, contenu in fichiers.items():
            complet = os.path.join(chemin, relatif)
            os.makedirs(os.path.dirname(complet), exist_ok=True)
            with open(complet, "w") as fh:
                fh.write(contenu)
        env = _env_git()
        for cmd in (["init", "-q", "."], ["add", "."], ["commit", "-qm", "i"]):
            subprocess.run(
                ["git", *cmd],
                cwd=chemin,
                env=env,
                check=True,
                capture_output=True,
            )
        return chemin

    def campagne(self, entrees=(), **options):
        c = r.CampagneOdoo(
            os.path.join(self.tmp, "scenarios.json"),
            RUN_ID,
            list(entrees),
            "99.0",
            racine=self.racine,
            **options,
        )
        c.odoo_bin = self.odoo_bin
        c.env_scenarios = self.env_factice()
        return c


class TestEnvironnement(unittest.TestCase):
    def test_path_and_inherited_variables(self):
        base = {
            "PATH": "/fictif/usr/bin:/fictif/bin",
            "PYTHONPATH": ".",
            "ODOO_MODE_DEV": "true",
            "ODOO_MODE_COVERAGE": "true",
            "ODOO_RC": "/fictif/odoorc",
            "COVERAGE_FILE": "/fictif/.coverage",
            "COVERAGE_PROCESS_START": "/fictif/rc",
            "HOME": "/fictif/home",
        }
        env = r.environnement(
            base, "/depot", "/doublures", {"COVERAGE_RCFILE": "/conf.toml"}
        )
        self.assertEqual(
            env["PATH"].split(os.pathsep),
            [
                "/depot/.venv.erplibre/bin",
                "/doublures",
                "/fictif/usr/bin",
                "/fictif/bin",
            ],
        )
        for retiree in (
            "PYTHONPATH",
            "ODOO_MODE_DEV",
            "ODOO_MODE_COVERAGE",
            "ODOO_RC",
            "COVERAGE_FILE",
            "COVERAGE_PROCESS_START",
        ):
            self.assertNotIn(retiree, env)
        self.assertEqual(env["HOME"], "/fictif/home")
        self.assertEqual(env["COVERAGE_RCFILE"], "/conf.toml")

    def test_without_doubles_the_path_has_no_empty_entry(self):
        env = r.environnement({"PATH": "/fictif/usr/bin"}, "/depot")
        self.assertNotIn("", env["PATH"].split(os.pathsep))


class TestCampagne(Bac):
    def test_doubles_refuse_host_commands(self):
        c = self.campagne()
        env = c.env(None, self.tmp)
        sudo = subprocess.run(
            ["sudo", "-n", "true"], env=env, capture_output=True, text=True
        )
        self.assertEqual(sudo.returncode, 1)
        self.assertIn("refusé", sudo.stderr)
        self.assertTrue(
            env["PATH"].startswith(
                os.path.join(self.racine, ".venv.erplibre", "bin") + os.pathsep
            )
        )

    def test_coverage_env_points_to_the_odoo_set(self):
        donnees = os.path.join(self.tmp, "couverture")
        with mock.patch.object(couverture, "CACHE", donnees):
            env = self.campagne(coverage=True).env(None, self.tmp)
        self.assertTrue(env["COVERAGE_RCFILE"].endswith("coverage.odoo.cfg"))
        self.assertTrue(
            env["COVERAGE_FILE"].startswith(
                os.path.join(donnees, "odoo") + os.sep
            )
        )

    def test_state_files_belong_to_the_campaign(self):
        c = self.campagne()
        cache = os.path.join(self.tmp, "cache", "erplibre")
        self.assertEqual(
            c.fichier_durees, os.path.join(cache, "odoo_scenarios.durations")
        )
        self.assertEqual(
            c.fichier_echecs, os.path.join(cache, "odoo_scenarios.failed")
        )
        self.assertFalse(c.tranches)
        self.assertEqual((c.grace, c.signal), (60.0, 300))

    def test_command_of_an_element(self):
        c = self.campagne(keep_cache=True, coverage=True)

        class Lanceur:
            py = "/py"

        element = moteur.Element("scn_a", nom="scn_a")
        cmd = c.commande(Lanceur, element, "/travail/0.scn_a")
        self.assertEqual(cmd[:3], ["/py", "-u", r.SCENARIO])
        self.assertIn("--coverage", cmd)
        for option, valeur in (
            ("--name", "scn_a"),
            ("--run-id", RUN_ID),
            ("--detail", "/travail/0.scn_a.json"),
            ("--racine", self.racine),
            (
                "--keep-cache",
                os.path.join(
                    self.tmp,
                    "cache",
                    "erplibre",
                    "odoo_scenarios",
                    RUN_ID,
                    "scn_a",
                ),
            ),
        ):
            self.assertEqual(cmd[cmd.index(option) + 1], valeur)


class TestDemontage(Bac):
    def test_only_this_run_s_databases_are_dropped(self):
        c = self.campagne()
        c.demontage(None)
        self.assertEqual(sorted(self.supprimees()), sorted(BASES[:2]))
        self.assertEqual(c.problemes, [])
        self.assertTrue(c.demonte.is_set())

    def test_keep_cache_keeps_the_databases(self):
        c = self.campagne(keep_cache=True)
        c.demontage(None)
        self.assertEqual(self.supprimees(), [])
        self.assertEqual(
            [m for m in c.messages if m.startswith("base gardée")],
            [f"base gardée : {b}" for b in BASES[:2]],
        )

    def test_a_silent_psql_is_a_campaign_problem(self):
        self.ecrire_bases([], code=2)
        c = self.campagne()
        c.demontage(None)
        self.assertEqual(self.supprimees(), [])
        self.assertTrue(any("psql" in p for p in c.problemes))

    def _entree_origine(self):
        (e,) = scenarios_odoo.charger_et_valider(
            '{"lst_test": [{"run_test_exec": true, "test_name": "scn_a",'
            ' "path_module_check": "./depot_fictif",'
            ' "restore_db_image_name": "image_fictive",'
            ' "file_to_restore": "mod/i18n/fr.po",'
            ' "file_to_restore_origin": true}]}'
        )
        return e

    def test_declared_paths_restored_only_if_clean_at_start(self):
        depot = self.depot(
            "depot_fictif", {"mod/i18n/fr.po": "a\n", "x": "1\n"}
        )
        fichier = os.path.join(depot, "mod/i18n/fr.po")
        c = self.campagne([self._entree_origine()])
        c.depots = ["./depot_fictif"]
        c.releve_initial()
        os.remove(fichier)
        shutil.rmtree(os.path.dirname(fichier))
        c.entre_phases(None, 10)
        self.assertTrue(os.path.exists(fichier))
        self.assertEqual(c.problemes, [])

    def test_a_path_dirty_at_start_is_left_alone(self):
        depot = self.depot("depot_fictif", {"mod/i18n/fr.po": "a\n"})
        fichier = os.path.join(depot, "mod/i18n/fr.po")
        with open(fichier, "w") as fh:
            fh.write("travail en cours\n")
        c = self.campagne([self._entree_origine()])
        c.depots = []
        c.releve_initial()
        c.demontage(None)
        with open(fichier) as fh:
            self.assertEqual(fh.read(), "travail en cours\n")

    def test_a_repository_dirtied_by_the_run_fails_the_campaign(self):
        depot = self.depot("depot_fictif", {"x": "1\n"})
        c = self.campagne()
        c.depots = ["./depot_fictif", "./absent"]
        c.releve_initial()
        with open(os.path.join(depot, "nouveau"), "w") as fh:
            fh.write("\n")
        c.demontage(None)
        self.assertEqual(len(c.problemes), 1)
        self.assertIn("./depot_fictif", c.problemes[0])
        self.assertIn("nouveau", c.problemes[0])

    def test_a_repository_dirty_at_start_is_only_reported(self):
        depot = self.depot("depot_fictif", {"x": "1\n"})
        with open(os.path.join(depot, "x"), "w") as fh:
            fh.write("2\n")
        c = self.campagne()
        c.depots = ["./depot_fictif"]
        c.releve_initial()
        c.demontage(None)
        self.assertEqual(c.problemes, [])
        self.assertTrue(any("déjà modifié" in m for m in c.messages))


class TestPhases(Bac):
    def test_phases_barrier_and_teardown_through_the_engine(self):
        """Le moteur appelle entre_phases avant la phase 10, puis le
        démontage, qui supprime les bases du passage."""
        entrees = scenarios_odoo.charger_et_valider(
            '{"lst_test": ['
            '{"run_command": true, "test_name": "a", "script": "./x"},'
            '{"run_command": true, "test_name": "b", "script": "./x",'
            ' "sequence": 10}]}'
        )
        ordre = []

        class Campagne(r.CampagneOdoo):
            def commande(self, lanceur, element, base):
                return [
                    sys.executable,
                    "-c",
                    f"open({self.trace!r}, 'a').write({element.nom!r})",
                ]

            def entre_phases(self, lanceur, phase):
                with open(self.trace) as fh:
                    ordre.append(("entre", phase, fh.read()))
                super().entre_phases(lanceur, phase)

        c = Campagne(
            os.path.join(self.tmp, "s.json"),
            RUN_ID,
            entrees,
            "99.0",
            racine=self.racine,
        )
        c.trace = os.path.join(self.tmp, "trace")
        open(c.trace, "w").close()
        c.odoo_bin = self.odoo_bin
        lanceur = moteur.Lanceur(
            scenarios_odoo.elements(entrees),
            sys.executable,
            2,
            30,
            {},
            campagne=c,
        )
        self.addCleanup(lanceur.nettoyer)
        # La campagne pose ses doublures ; psql factice en tête.
        lanceur.env["PATH"] = self.bin + os.pathsep + lanceur.env["PATH"]
        c.env_scenarios = lanceur.env
        lanceur.lancer()
        self.assertEqual(ordre, [("entre", 10, "a")])
        self.assertEqual([f.etat for f in lanceur.fichiers], [moteur.OK] * 2)
        self.assertEqual(sorted(self.supprimees()), sorted(BASES[:2]))


class TestMakeTestLog(Bac):
    def test_logs_are_concatenated_with_a_header(self):
        journaux = []
        for nom, etat in (("scn_a", moteur.OK), ("scn_b", moteur.ECHEC)):
            f = moteur.Element(nom, nom=nom)
            f.etat = etat
            f.log = os.path.join(self.tmp, f"{nom}.log")
            with open(f.log, "w") as fh:
                fh.write(f"journal de {nom}\n")
            journaux.append(f)

        class Lanceur:
            fichiers = journaux

        chemin = os.path.join(self.tmp, "make_test.log")
        r.ecrire_make_test_log(Lanceur, chemin)
        with open(chemin) as fh:
            texte = fh.read()
        self.assertIn(f"Test execution 1 - {moteur.VERT}PASS", texte)
        self.assertIn(f"Test execution 2 - {moteur.ROUGE}FAIL", texte)
        self.assertLess(texte.index("journal de scn_a"), texte.index("scn_b"))

    def test_the_log_goes_next_to_the_odoo_venv(self):
        with open(os.path.join(self.racine, ".erplibre-version"), "w") as fh:
            fh.write("odoo99.0_python9.9\n")
        self.assertIsNone(r.chemin_make_test_log(self.racine))
        os.makedirs(os.path.join(self.racine, ".venv.odoo99.0_python9.9"))
        self.assertEqual(
            r.chemin_make_test_log(self.racine),
            os.path.join(
                self.racine, ".venv.odoo99.0_python9.9", "make_test.log"
            ),
        )


class TestPurge(Bac):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.dict(
            os.environ, {"PATH": self.env_factice()["PATH"]}
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_purge_drops_scenario_databases_only(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(r.purger(self.racine, oui=True), 0)
        self.assertEqual(sorted(self.supprimees()), sorted(BASES[:4]))

    def test_purge_without_terminal_asks_for_oui(self):
        with mock.patch.object(sys, "stdin", io.StringIO()):
            with contextlib.redirect_stdout(io.StringIO()) as sortie:
                self.assertEqual(r.purger(self.racine, oui=False), 1)
        self.assertEqual(self.supprimees(), [])
        self.assertIn("--oui", sortie.getvalue())


class AvecVerrou(Bac):
    """Le verrou des campagnes dans le répertoire temporaire ; cwd et
    gestionnaire de SIGTERM rétablis après main()."""

    def setUp(self):
        super().setUp()
        self.addCleanup(os.chdir, os.getcwd())
        self.addCleanup(
            signal.signal, signal.SIGTERM, signal.getsignal(signal.SIGTERM)
        )
        patcher = mock.patch.object(
            moteur, "VERROU", os.path.join(self.tmp, "campagne.lock")
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        # Lancés par le lanceur unitaire, ces tests font partie de sa
        # campagne, que le verrou laisse passer : ils en sortent pour
        # éprouver le verrou d'une campagne neuve.
        hors = mock.patch.dict(os.environ)
        hors.start()
        self.addCleanup(hors.stop)
        os.environ.pop(moteur.DANS_UNE_CAMPAGNE, None)


class TestMain(AvecVerrou):
    def main(self, *argv):
        with contextlib.redirect_stdout(io.StringIO()) as sortie:
            code = r.main(list(argv), racine=RACINE)
        return code, sortie.getvalue()

    def test_a_held_lock_refuses_naming_the_holder(self):
        # Un scénario inoffensif : si le verrou cédait, rien de réel ne
        # partirait (ni Odoo, ni base).
        inoffensif = os.path.join(self.tmp, "inoffensif.json")
        with open(inoffensif, "w") as fh:
            fh.write(
                '{"lst_test": [{"run_command": true,'
                ' "test_name": "inoffensif", "script": "./absent_fictif.sh"}]}'
            )
        with moteur.verrou_campagne("suite fictive"):
            code, sortie = self.main(
                "--json", inoffensif, "--ignore_init_check_git"
            )
        self.assertEqual(code, 1)
        self.assertIn("suite fictive", sortie)

    def test_an_unknown_scenario_is_refused(self):
        code, sortie = self.main("--scenario", "scenario_inexistant")
        self.assertEqual(code, 2)
        self.assertIn("scenario_inexistant", sortie)

    def test_an_invalid_json_is_refused_before_anything(self):
        mauvais = os.path.join(self.tmp, "mauvais.json")
        with open(mauvais, "w") as fh:
            fh.write(
                '{"lst_test": [{"run_command": true, "test_name": "x",'
                ' "script": "./x", "generated_path": "./y"}]}'
            )
        code, sortie = self.main("--json", mauvais)
        self.assertEqual(code, 2)
        self.assertIn("generated_path", sortie)

    def test_failed_with_nothing_retained_runs_nothing(self):
        code, sortie = self.main("--failed")
        self.assertEqual(code, 0)
        self.assertIn("Aucun scénario", sortie)


class TestPassageComplet(AvecVerrou):
    """main() de bout en bout sur une racine factice : le moteur, le vrai
    pilote, le JUnit, make_test.log et les fichiers d'état."""

    def setUp(self):
        super().setUp()
        patcher = mock.patch.dict(
            os.environ, {"PATH": self.env_factice()["PATH"]}
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        for nom, contenu in (
            (".odoo-version", "99.0"),
            (".erplibre-version", "odoo99.0_python9.9\n"),
        ):
            with open(os.path.join(self.racine, nom), "w") as fh:
                fh.write(contenu)
        os.makedirs(os.path.join(self.racine, ".venv.odoo99.0_python9.9"))
        self.script(
            os.path.join(self.racine, "vert.sh"), "echo tout va bien\n"
        )
        self.script(
            os.path.join(self.racine, "rouge.sh"),
            "echo 2031-01-01 4242 ERROR base_fictive odoo.registry: boum\n",
        )
        self.json = os.path.join(self.tmp, "scenarios.json")
        with open(self.json, "w") as fh:
            fh.write(
                '{"lst_test": ['
                '{"run_command": true, "test_name": "vert_a",'
                ' "script": "./vert.sh"},'
                '{"run_command": true, "test_name": "rouge_b",'
                ' "script": "./rouge.sh", "sequence": 10}]}'
            )

    def test_a_full_run(self):
        junit = os.path.join(self.tmp, "junit.xml")
        with contextlib.redirect_stdout(io.StringIO()) as sortie:
            code = r.main(
                [
                    "--json",
                    self.json,
                    "--ignore_init_check_git",
                    "--junit",
                    junit,
                ],
                racine=self.racine,
            )
        self.assertEqual(code, 1, sortie.getvalue())
        with open(junit) as fh:
            xml = fh.read()
        self.assertIn('name="script"', xml)
        self.assertIn("odoo.registry: boum", xml)
        journal = os.path.join(
            self.racine, ".venv.odoo99.0_python9.9", "make_test.log"
        )
        with open(journal) as fh:
            texte = fh.read()
        self.assertIn("vert_a", texte)
        self.assertIn(f"{moteur.ROUGE}FAIL{moteur.FIN} - rouge_b", texte)
        # Odoo sort en 0 : la commande passe, le scénario échoue sur la
        # ligne d'erreur.
        self.assertIn("PASS [rouge_b]", texte)
        self.assertIn("ÉCHEC [rouge_b]", texte)
        cache = os.path.join(self.tmp, "cache", "erplibre")
        with open(os.path.join(cache, "odoo_scenarios.failed")) as fh:
            self.assertEqual(fh.read(), "rouge_b\n")
        with open(os.path.join(cache, "odoo_scenarios.durations")) as fh:
            self.assertEqual(
                sorted(ligne.split()[1] for ligne in fh), ["rouge_b", "vert_a"]
            )
        self.assertFalse(
            any(n.startswith("run_unit_test.") for n in os.listdir(cache))
        )


if __name__ == "__main__":
    unittest.main()
