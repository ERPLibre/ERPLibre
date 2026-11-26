#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'état du serveur PostgreSQL (script/database/pg_state) et son verdict
dans le bilan de santé.

Un serveur démarré avant la mise à jour de son paquet garde l'ancien
exécutable et échoue au premier chargement d'une bibliothèque, plpgsql par
exemple : le bilan de santé le signale en alerte avec la commande qui le
redémarre. Un dump ne se restaure que vers un serveur de même version
majeure ou plus récent, et Odoo 20 exige PostgreSQL 16 : `verifier` le dit
aussi, pour qui prépare une migration.

Aucun serveur réel : psql et postgres sont des doublures.
"""

import os
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RACINE)

from script.database import pg_state  # noqa: E402
from script.todo import healthcheck  # noqa: E402
from script.todo import todo_i18n  # noqa: E402


def fini(code=0, sortie=""):
    return subprocess.CompletedProcess([], code, sortie, "")


class Doublures(unittest.TestCase):
    """Des bindirs jetables dont l'exécutable postgres existe, et un
    lanceur qui répond à leur place."""

    def setUp(self):
        self.addCleanup(
            setattr, todo_i18n, "_current_lang", todo_i18n._current_lang
        )
        todo_i18n._current_lang = "en"
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name

    def bindir(self, nom):
        chemin = os.path.join(self.tmp, nom)
        os.makedirs(chemin)
        executable = os.path.join(chemin, "postgres")
        with open(executable, "w") as fh:
            fh.write("")
        os.chmod(executable, stat.S_IRWXU)
        return chemin

    def lanceur(self, serveur, binaires):
        """`serveur` : ce que rend SHOW server_version, None s'il ne répond
        pas ; `binaires` : la version de chaque bindir."""

        def lancer(args, **_kw):
            if args[0] == "psql":
                if serveur is None:
                    return fini(2)
                return fini(0, f"{serveur}\n")
            version = binaires[os.path.dirname(args[0])]
            return fini(0, f"postgres (PostgreSQL) {version}\n")

        return lancer


class TestVersions(unittest.TestCase):
    def test_version_lisible_reads_package_suffixes(self):
        self.assertEqual(
            pg_state.version_lisible("18.6 (Debian 18.6-1.pgdg+1)"), "18.6"
        )
        self.assertEqual(
            pg_state.version_lisible("postgres (PostgreSQL) 18.7"), "18.7"
        )
        self.assertIsNone(pg_state.version_lisible(""))

    def test_majeure(self):
        self.assertEqual(pg_state.majeure("16.11"), 16)
        self.assertIsNone(pg_state.majeure(None))

    def test_library_failure_is_recognised(self):
        self.assertTrue(
            pg_state.bibliotheque_en_cause(
                [
                    'ERROR:  could not load library "/usr/lib/postgresql/'
                    'plpgsql.so": undefined symbol: x'
                ]
            )
        )
        self.assertFalse(
            pg_state.bibliotheque_en_cause(["ERROR:  syntax error"])
        )
        # Un module Python mal compilé n'est pas l'affaire du serveur.
        self.assertFalse(
            pg_state.bibliotheque_en_cause(
                ["ImportError: _psycopg.so: undefined symbol: PQx"]
            )
        )
        self.assertFalse(pg_state.bibliotheque_en_cause(None))

    def test_only_a_socket_is_a_local_server(self):
        self.assertTrue(pg_state.serveur_local({}))
        self.assertTrue(pg_state.serveur_local({"PGHOST": "/run/pg"}))
        self.assertFalse(pg_state.serveur_local({"PGHOST": "localhost"}))


class TestVerifier(Doublures):
    def test_a_server_matching_its_binary_is_fine(self):
        b = self.bindir("18")
        lancer = self.lanceur("18.7", {b: "18.7"})
        self.assertEqual(
            pg_state.verifier(
                {}, [b], version_dump=18, cible=19, lancer=lancer
            ),
            [],
        )

    def test_a_server_older_than_its_package_stops(self):
        b = self.bindir("18")
        lancer = self.lanceur("18.6", {b: "18.7"})
        (defaut,) = pg_state.verifier({}, [b], lancer=lancer)
        self.assertEqual(
            defaut, (pg_state.ARRET, pg_state.DECALAGE, ("18.6", "18.7"))
        )

    def test_another_major_installed_beside_says_nothing(self):
        # Un 17 installé à côté ne dit rien du 18 en marche.
        b17, b18 = self.bindir("17"), self.bindir("18")
        lancer = self.lanceur("18.7", {b17: "17.2", b18: "18.7"})
        self.assertEqual(pg_state.verifier({}, [b17, b18], lancer=lancer), [])

    def test_no_installed_binary_is_only_a_warning(self):
        b17 = self.bindir("17")
        lancer = self.lanceur("18.7", {b17: "17.2"})
        (defaut,) = pg_state.verifier({}, [b17], lancer=lancer)
        self.assertEqual(defaut[0], pg_state.AVERTISSEMENT)
        self.assertEqual(defaut[1], pg_state.BINAIRE_INTROUVABLE)

    def test_a_server_that_cannot_be_asked_does_not_stop(self):
        # Un rôle ou un mot de passe que psql n'a pas n'empêche pas Odoo.
        lancer = self.lanceur(None, {})
        self.assertEqual(
            pg_state.verifier({}, [], lancer=lancer),
            [(pg_state.AVERTISSEMENT, pg_state.INJOIGNABLE, ())],
        )

    def test_psql_never_asks_for_a_password(self):
        vus = []

        def lancer(args, **_kw):
            vus.append(args)
            return fini(2)

        pg_state.version_serveur({}, lancer=lancer)
        self.assertIn("-w", vus[0])

    def test_a_backup_from_a_newer_server_only_warns(self):
        b = self.bindir("16")
        lancer = self.lanceur("16.4", {b: "16.4"})
        (defaut,) = pg_state.verifier({}, [b], version_dump=18, lancer=lancer)
        self.assertEqual(
            defaut,
            (pg_state.AVERTISSEMENT, pg_state.DUMP_PLUS_RECENT, (18, 16)),
        )

    def test_a_server_over_tcp_is_not_compared_to_local_binaries(self):
        # Un conteneur ou un autre hôte ne tourne pas sur le binaire d'ici.
        b = self.bindir("18")
        lancer = self.lanceur("18.1", {b: "18.6"})
        with mock.patch.object(
            pg_state, "candidats_bindir_systeme", return_value=[b]
        ) as chercher:
            self.assertEqual(
                pg_state.verifier({"PGHOST": "localhost"}, lancer=lancer), []
            )
            chercher.assert_not_called()
            (defaut,) = pg_state.verifier({}, lancer=lancer)
        self.assertEqual(defaut[1], pg_state.DECALAGE)

    def test_odoo_20_needs_postgresql_16(self):
        b = self.bindir("15")
        lancer = self.lanceur("15.8", {b: "15.8"})
        (defaut,) = pg_state.verifier({}, [b], cible=20, lancer=lancer)
        self.assertEqual(
            defaut, (pg_state.ARRET, pg_state.TROP_ANCIEN_ODOO_20, (15,))
        )
        self.assertEqual(
            pg_state.verifier({}, [b], cible=19, lancer=lancer), []
        )


class TestHealthcheck(unittest.TestCase):
    def setUp(self):
        self.addCleanup(
            setattr, todo_i18n, "_current_lang", todo_i18n._current_lang
        )
        todo_i18n._current_lang = "en"

    def verdict(self, defauts):
        ctx = healthcheck.Contexte(tempfile.gettempdir())
        ctx.lancer = lambda args, *a, **k: fini(
            0, "/run/postgresql:5432 - accepting connections"
        )
        with (
            mock.patch.object(
                healthcheck, "_config_odoo", return_value={"db_port": "5432"}
            ),
            mock.patch.object(
                healthcheck.shutil, "which", return_value="/usr/bin/pg_isready"
            ),
            mock.patch.object(
                healthcheck.pg_state, "verifier", return_value=defauts
            ),
        ):
            return healthcheck.verifier_postgresql(ctx)

    def test_a_server_older_than_its_package_is_an_alert(self):
        resultat = self.verdict(
            [(pg_state.ARRET, pg_state.DECALAGE, ("18.6", "18.7"))]
        )
        self.assertEqual(resultat.statut, healthcheck.ALERTE)
        self.assertIn("running version 18.6", resultat.resume)
        self.assertIn(f"$ {pg_state.COMMANDE_REDEMARRER}", resultat.details)

    def test_the_alert_offers_to_restart_postgresql(self):
        resultat = self.verdict(
            [(pg_state.ARRET, pg_state.DECALAGE, ("18.6", "18.7"))]
        )
        (redemarrer,) = resultat.resolutions
        self.assertEqual(redemarrer.cle, healthcheck.REDEMARRER_POSTGRESQL)
        self.assertTrue(redemarrer.actionnable)
        self.assertIn(
            f"   $ {pg_state.COMMANDE_REDEMARRER}", redemarrer.lignes
        )

    def redemarrer(self, reponse, code=0):
        lances, lignes = [], []
        ctx = healthcheck.Contexte(tempfile.gettempdir())
        change = healthcheck._redemarrer_postgresql(
            ctx,
            lambda _q: reponse,
            lignes.append,
            lancer=lambda commande: lances.append(commande) or code,
        )
        return change, lances, lignes

    def test_the_restart_runs_only_on_a_yes(self):
        change, lances, _ = self.redemarrer("")
        self.assertFalse(change)
        self.assertEqual(lances, [])
        change, lances, _ = self.redemarrer("o")
        self.assertTrue(change)
        self.assertEqual(
            lances, [["sudo", "systemctl", "restart", "postgresql"]]
        )

    def test_a_failed_restart_is_reported(self):
        change, _, lignes = self.redemarrer("y", code=1)
        self.assertFalse(change)
        self.assertTrue(any(ligne.startswith("❌") for ligne in lignes))

    def test_the_resolution_is_dispatched(self):
        res = healthcheck.Resolution(
            healthcheck.REDEMARRER_POSTGRESQL, "🐘", []
        )
        with mock.patch.object(
            healthcheck, "_redemarrer_postgresql", return_value=True
        ) as redemarrer:
            self.assertTrue(
                healthcheck.executer_resolution(
                    healthcheck.Contexte(tempfile.gettempdir()), res
                )
            )
        redemarrer.assert_called_once()

    def test_migration_only_defects_stay_out_of_the_healthcheck(self):
        resultat = self.verdict(
            [(pg_state.AVERTISSEMENT, pg_state.BINAIRE_INTROUVABLE, ())]
        )
        self.assertEqual(resultat.statut, healthcheck.OK)


if __name__ == "__main__":
    unittest.main()
