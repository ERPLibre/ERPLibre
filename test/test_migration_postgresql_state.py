#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le serveur PostgreSQL vu par la migration (script/todo/todo_upgrade).

La migration vérifie son serveur avant de commencer et à chaque reprise
(pg_state.verifier) : elle ne s'arrête que sur un défaut qui ferait
échouer un saut à coup sûr. Une commande qui échoue sur une bibliothèque
que le serveur ne charge pas dit de le redémarrer. Une base passée de
PostgreSQL 17 à 18 se répare seule à la neutralisation.

Aucun serveur réel : pg_state et l'exécution des commandes sont des
doublures.
"""

import io
import os
import subprocess
import sys
import unittest
from contextlib import redirect_stdout
from unittest import mock

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RACINE)

from script.database import pg_state  # noqa: E402
from script.todo import todo_i18n  # noqa: E402
from script.todo import todo_upgrade  # noqa: E402
from script.todo.todo_upgrade import TodoUpgrade  # noqa: E402


def fini(code=0, sortie=""):
    return subprocess.CompletedProcess([], code, sortie, "")


class Migration(unittest.TestCase):
    def setUp(self):
        self.addCleanup(
            setattr, todo_i18n, "_current_lang", todo_i18n._current_lang
        )
        todo_i18n._current_lang = "en"
        self.upgrade = TodoUpgrade.__new__(TodoUpgrade)
        self.upgrade.dct_progression = {}
        self.upgrade.file_path = "/b.zip"
        self.upgrade.write_config = lambda: None

    def verifier(self, defauts):
        """Lance verifier_postgresql, pg_state.verifier rendant
        `defauts`."""
        with (
            mock.patch.object(
                todo_upgrade.pg_state, "verifier", return_value=defauts
            ) as lire,
            mock.patch.object(
                todo_upgrade.pg_state, "version_du_dump", return_value=18
            ),
            redirect_stdout(io.StringIO()) as sortie,
        ):
            rendu = self.upgrade.verifier_postgresql(18)
        return rendu, sortie.getvalue(), lire


class TestVerifierPostgresql(Migration):
    DECALE = [(pg_state.ARRET, pg_state.DECALAGE, ("18.6", "18.7"))]

    def test_a_sound_server_lets_the_migration_go(self):
        rendu, sortie, lire = self.verifier([])
        self.assertTrue(rendu)
        self.assertEqual(sortie, "")
        self.assertEqual(lire.call_args.kwargs["version_dump"], 18)
        self.assertEqual(lire.call_args.kwargs["cible"], 18)

    def test_a_server_older_than_its_package_stops_with_the_command(self):
        rendu, sortie, _lire = self.verifier(self.DECALE)
        self.assertFalse(rendu)
        self.assertIn("running version 18.6", sortie)
        self.assertIn("installed version 18.7", sortie)
        self.assertIn(pg_state.COMMANDE_REDEMARRER, sortie)
        self.assertIn("resumes here", sortie)

    def test_a_warning_does_not_stop(self):
        rendu, sortie, _lire = self.verifier(
            [(pg_state.AVERTISSEMENT, pg_state.BINAIRE_INTROUVABLE, ())]
        )
        self.assertTrue(rendu)
        self.assertIn("⚠️", sortie)


class Execution(Migration):
    """Un pilote dont la commande échoue avec `sortie`, sans invite."""

    def lancer(self, sortie_commande, statuts, on_error=None, **kw):
        self.upgrade.lst_command_executed = []
        self.upgrade.record_event = lambda *a, **k: None
        self.lances = []
        suite = iter(statuts)

        class FauxExecute:
            def exec_command_live(_self, cmd, **options):
                self.lances.append(cmd)
                statut = next(suite)
                if options.get("return_status_and_output_and_command"):
                    return statut, cmd, list(sortie_commande)
                return statut, cmd

        self.upgrade.execute = FauxExecute()
        with redirect_stdout(io.StringIO()) as sortie:
            rendu = self.upgrade.todo_upgrade_execute(
                "cmd", wait_at_error=False, on_error=on_error, **kw
            )
        return rendu, sortie.getvalue()


class TestBibliotheque(Execution):
    def test_a_library_failure_names_the_restart(self):
        _, sortie = self.lancer(
            ['ERROR:  could not load library "plpgsql.so": undefined symbol'],
            [3],
            get_output=True,
        )
        self.assertIn(pg_state.COMMANDE_REDEMARRER, sortie)

    def test_an_ordinary_failure_says_nothing_of_postgresql(self):
        _, sortie = self.lancer(["ERROR:  syntax error"], [3], get_output=True)
        self.assertNotIn(pg_state.COMMANDE_REDEMARRER, sortie)

    def test_a_success_says_nothing(self):
        _, sortie = self.lancer(
            ['could not load library "x.so"'], [0], get_output=True
        )
        self.assertEqual(sortie, "")


class TestOnError(Execution):
    def test_a_repair_reruns_the_command(self):
        vus = []

        def reparer(sortie):
            vus.append(sortie)
            return True

        rendu, _ = self.lancer(["boom"], [1, 0], on_error=reparer)
        self.assertEqual(rendu, (0, "cmd"))
        self.assertEqual(self.lances, ["cmd", "cmd"])
        self.assertEqual(vus, [["boom"]])

    def test_the_rerun_is_bounded(self):
        rendu, _ = self.lancer(
            ["boom"],
            [1] * TodoUpgrade.MAX_ERROR_RETRY,
            on_error=lambda _s: True,
        )
        self.assertEqual(rendu[0], 1)
        self.assertEqual(len(self.lances), TodoUpgrade.MAX_ERROR_RETRY)

    def test_no_repair_no_rerun(self):
        rendu, _ = self.lancer(["boom"], [1], on_error=lambda _s: False)
        self.assertEqual(rendu, (1, "cmd"))
        self.assertEqual(self.lances, ["cmd"])

    def test_a_success_never_calls_it(self):
        appels = []
        self.lancer(["ok"], [0], on_error=lambda s: appels.append(s))
        self.assertEqual(appels, [])


class TestNotNullPostgresql18(Execution):
    SIGNATURE = (
        'ERROR: insert or update on table "discuss_channel_member" violates'
        ' foreign key constraint "discuss_channel_member_channel_id_fkey"'
    )

    def test_without_its_signature_nothing_runs(self):
        self.upgrade.todo_upgrade_execute = mock.Mock()
        self.assertFalse(
            self.upgrade.reparer_not_null_postgresql_18("db", ["autre"])
        )
        self.upgrade.todo_upgrade_execute.assert_not_called()

    def test_its_signature_runs_the_fix_on_the_database(self):
        self.upgrade.todo_upgrade_execute = mock.Mock(
            side_effect=[(0, "q", ["1"]), (0, "x")]
        )
        with redirect_stdout(io.StringIO()):
            self.assertTrue(
                self.upgrade.reparer_not_null_postgresql_18(
                    "db", [self.SIGNATURE]
                )
            )
        requete, correctif = [
            appel.args[0]
            for appel in self.upgrade.todo_upgrade_execute.call_args_list
        ]
        self.assertIn(todo_upgrade.CONTRAINTE_PG18, requete)
        self.assertIn("-w", requete)
        self.assertIn("-d db", correctif)
        self.assertIn(todo_upgrade.FIX_PG18_DISCUSS_CHANNEL, correctif)

    def test_without_the_constraint_nothing_is_rerun(self):
        # La signature sans la contrainte : le correctif ne changerait
        # rien, relancer ne ferait que refaire le même échec.
        self.upgrade.todo_upgrade_execute = mock.Mock(
            return_value=(0, "q", ["0"])
        )
        self.assertFalse(
            self.upgrade.reparer_not_null_postgresql_18(
                "db", ['relation "discuss_channel" does not exist']
            )
        )
        self.assertEqual(self.upgrade.todo_upgrade_execute.call_count, 1)

    def test_a_failed_fix_does_not_claim_a_repair(self):
        self.upgrade.todo_upgrade_execute = mock.Mock(
            side_effect=[(0, "q", ["1"]), (1, "x")]
        )
        with redirect_stdout(io.StringIO()):
            self.assertFalse(
                self.upgrade.reparer_not_null_postgresql_18(
                    "db", ['relation "discuss_channel" does not exist']
                )
            )

    def test_the_fix_file_exists_and_is_idempotent(self):
        chemin = os.path.join(RACINE, todo_upgrade.FIX_PG18_DISCUSS_CHANNEL)
        with open(chemin, encoding="utf-8") as fh:
            texte = fh.read()
        self.assertIn("IF EXISTS discuss_channel", texte)
        self.assertIn(
            "DROP CONSTRAINT IF EXISTS discuss_channel_channel_type_not_null",
            texte,
        )


if __name__ == "__main__":
    unittest.main()
