#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La version de PostgreSQL qu'exige une version d'Odoo, et sa pose.

Le catalogue (conf/supported_version_erplibre.json) porte, par entrée, la
version majeure MINIMALE de PostgreSQL dans « postgresql_version ».
version_manager.postgresql_requise la lit ; lib_postgres_version.sh en fait
le plancher de l'installeur Debian quand la version d'Odoo active l'exige,
dit à la fin quand les bases restent sur un cluster plus ancien, et les
profils d'installation des VM la passent en PG_VERSION.

Les fonctions shell tournent pour de vrai, dans un faux checkout qui porte
le vrai catalogue et le vrai version_manager.py, avec un PATH de commandes
factices qui notent leurs appels : rien n'est installé.
"""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from script.todo import version_manager
from script.todo.version_manager import odoo_par_defaut, postgresql_requise

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CATALOGUE = os.path.join(RACINE, "conf", "supported_version_erplibre.json")
DEBIAN = os.path.join(
    RACINE, "script", "install", "install_debian_dependency.sh"
)
# Chemin absolu : un test retire /usr/bin du PATH de bash.
BASH = shutil.which("bash")


def catalogue_temporaire(test, entrees):
    """Écrit `entrees` dans un catalogue jetable et y fait pointer
    version_manager le temps du test."""
    dossier = tempfile.mkdtemp()
    test.addCleanup(shutil.rmtree, dossier)
    chemin = os.path.join(dossier, "catalogue.json")
    with open(chemin, "w") as handle:
        json.dump(entrees, handle)
    patch = mock.patch.object(version_manager, "VERSION_DATA_FILE", chemin)
    patch.start()
    test.addCleanup(patch.stop)


class TestCatalogue(unittest.TestCase):
    def test_odoo_18_19_20_require_postgresql_18(self):
        for odoo in ("18.0", "19.0", "20.0"):
            self.assertEqual(18, postgresql_requise(odoo), odoo)

    def test_older_versions_carry_no_requirement(self):
        with open(CATALOGUE) as handle:
            entrees = json.load(handle).values()
        for entree in entrees:
            if entree["odoo_version"] in ("18.0", "19.0", "20.0"):
                continue
            self.assertNotIn("postgresql_version", entree)
            self.assertIsNone(postgresql_requise(entree["odoo_version"]))

    def test_unknown_version_has_no_requirement(self):
        self.assertIsNone(postgresql_requise("99.0"))

    def test_two_entries_of_one_odoo_give_the_highest(self):
        catalogue_temporaire(
            self,
            {
                "odoo30.0_python3.20.1": {
                    "odoo_version": "30.0",
                    "postgresql_version": "19",
                },
                "odoo30.0_python3.20.2": {
                    "odoo_version": "30.0",
                    "postgresql_version": "21",
                },
            },
        )
        self.assertEqual(21, postgresql_requise("30.0"))


class Base(unittest.TestCase):
    """Un faux checkout : catalogue et version_manager.py réels, les
    bibliothèques shell réelles, et des commandes factices devant /usr/bin.

    apt-cache annonce la version FAUX_DISTRIB de la distribution ;
    pg_lsclusters rend FAUX_CLUSTERS ; sudo note ses arguments."""

    def setUp(self):
        self.racine = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.racine)
        for relatif in (
            "conf/supported_version_erplibre.json",
            "script/todo/version_manager.py",
            "script/install/lib_postgres_version.sh",
        ):
            cible = os.path.join(self.racine, relatif)
            os.makedirs(os.path.dirname(cible), exist_ok=True)
            shutil.copy(os.path.join(RACINE, relatif), cible)
        self.trace = os.path.join(self.racine, "trace")
        self.faux = os.path.join(self.racine, "bin")
        os.makedirs(self.faux)
        self.commande("sudo", f'echo "sudo $*" >> "{self.trace}"')
        self.commande(
            "apt-cache",
            '[[ -n "$FAUX_DISTRIB" ]] && '
            'echo "  Depends: postgresql-$FAUX_DISTRIB"; exit 0',
        )
        self.commande("pg_lsclusters", 'printf "%b" "$FAUX_CLUSTERS"')

    def commande(self, nom, corps):
        chemin = os.path.join(self.faux, nom)
        with open(chemin, "w") as handle:
            handle.write("#!/bin/bash\n" + corps + "\n")
        os.chmod(chemin, 0o755)

    def odoo_active(self, version):
        with open(os.path.join(self.racine, ".odoo-version"), "w") as handle:
            handle.write(version + "\n")

    def ecrire_catalogue(self, entrees):
        chemin = os.path.join(
            self.racine, "conf", "supported_version_erplibre.json"
        )
        with open(chemin, "w") as handle:
            json.dump(entrees, handle)

    def lancer(self, appel, **env_extra):
        env = {
            "PATH": self.faux + ":/usr/bin:/bin",
            "HOME": self.racine,
            "APT_GET": "sudo apt-get",
            **env_extra,
        }
        done = subprocess.run(
            [
                BASH,
                "-c",
                ". ./script/install/lib_postgres_version.sh; " + appel,
            ],
            cwd=self.racine,
            env=env,
            capture_output=True,
            text=True,
        )
        trace = ""
        if os.path.exists(self.trace):
            with open(self.trace) as handle:
                trace = handle.read()
        return done, trace


class TestPlancher(Base):
    def plancher(self):
        done, _trace = self.lancer("el_pg_plancher")
        self.assertEqual(0, done.returncode, done.stderr)
        return done.stdout.strip()

    def test_fresh_clone_follows_the_default_version(self):
        # Sans .odoo-version, l'installation qui suit posera la version par
        # défaut du catalogue : son exigence fixe déjà le plancher.
        defaut = odoo_par_defaut()
        attendu = max(16, postgresql_requise(defaut) or 16)
        self.assertEqual(str(attendu), self.plancher())

    def test_fresh_clone_takes_the_default_entry_requirement(self):
        self.ecrire_catalogue(
            {
                "a": {"odoo_version": "17.0", "postgresql_version": "17"},
                "b": {
                    "odoo_version": "30.0",
                    "postgresql_version": "21",
                    "default": True,
                },
            }
        )
        self.assertEqual("21", self.plancher())

    def test_fresh_clone_whose_default_carries_nothing_stays_16(self):
        self.ecrire_catalogue(
            {
                "a": {"odoo_version": "30.0", "postgresql_version": "21"},
                "b": {"odoo_version": "12.0", "default": True},
            }
        )
        self.assertEqual("16", self.plancher())

    def test_active_odoo_18_raises_the_floor_to_18(self):
        self.odoo_active("18.0")
        self.assertEqual("18", self.plancher())

    def test_active_version_without_requirement_keeps_16(self):
        for odoo in ("16.0", "12.0"):
            self.odoo_active(odoo)
            self.assertEqual("16", self.plancher(), odoo)

    def test_a_lower_requirement_never_lowers_the_floor(self):
        chemin = os.path.join(
            self.racine, "conf", "supported_version_erplibre.json"
        )
        with open(chemin, "w") as handle:
            json.dump(
                {"x": {"odoo_version": "11.0", "postgresql_version": "12"}},
                handle,
            )
        self.odoo_active("11.0")
        self.assertEqual("16", self.plancher())


class TestInstaller(Base):
    def test_distribution_16_with_odoo_18_takes_pgdg_18(self):
        self.odoo_active("18.0")
        done, trace = self.lancer(
            "el_pg_installer && echo choisie=$EL_PG_CHOISIE", FAUX_DISTRIB="16"
        )
        self.assertEqual(0, done.returncode, done.stderr)
        self.assertIn("pgdg/apt.postgresql.org.sh -y", trace)
        self.assertIn("apt-get install postgresql-18 libpq-dev -y", trace)
        self.assertIn("choisie=18", done.stdout)

    def test_distribution_18_with_odoo_18_takes_the_distribution(self):
        self.odoo_active("18.0")
        done, trace = self.lancer(
            "el_pg_installer && echo choisie=$EL_PG_CHOISIE", FAUX_DISTRIB="18"
        )
        self.assertEqual(0, done.returncode, done.stderr)
        self.assertIn("apt-get install postgresql-18 libpq-dev -y", trace)
        self.assertNotIn("pgdg", trace)
        self.assertIn("choisie=18", done.stdout)

    def test_an_available_version_never_pulls_the_metapackages(self):
        # PGDG déjà configuré : « postgresql » mène à la 18 de PGDG, mais
        # « postgresql-contrib » de la distribution tirerait sa propre 15.
        self.odoo_active("18.0")
        _done, trace = self.lancer("el_pg_installer", FAUX_DISTRIB="18")
        self.assertNotIn("postgresql-contrib", trace)
        self.assertNotIn("install postgresql ", trace)

    def test_version_without_requirement_keeps_the_distribution_16(self):
        self.odoo_active("16.0")
        _done, trace = self.lancer("el_pg_installer", FAUX_DISTRIB="16")
        self.assertIn("apt-get install postgresql-16 libpq-dev -y", trace)
        self.assertNotIn("pgdg", trace)

    def test_distribution_below_16_still_takes_pgdg_16(self):
        self.odoo_active("16.0")
        _done, trace = self.lancer("el_pg_installer", FAUX_DISTRIB="15")
        self.assertIn("apt-get install postgresql-16 libpq-dev -y", trace)

    def test_pg_version_overrides_the_requirement(self):
        self.odoo_active("18.0")
        _done, trace = self.lancer(
            "el_pg_installer", FAUX_DISTRIB="16", PG_VERSION="15"
        )
        self.assertIn("apt-get install postgresql-15 libpq-dev -y", trace)
        self.assertNotIn("postgresql-18", trace)

    def test_an_apt_failure_returns_1(self):
        self.commande("sudo", "exit 100")
        done, _trace = self.lancer("el_pg_installer", FAUX_DISTRIB="16")
        self.assertEqual(1, done.returncode)


class TestAvisAncienCluster(Base):
    LIGNE_16 = "16 main 5432 online postgres /var/lib/postgresql/16/main x\\n"
    LIGNE_18 = "18 main 5433 online postgres /var/lib/postgresql/18/main x\\n"

    def avis(self, clusters, choisie="18"):
        done, _trace = self.lancer(
            "el_pg_avis_ancien_cluster",
            FAUX_CLUSTERS=clusters,
            EL_PG_CHOISIE=choisie,
        )
        self.assertEqual(0, done.returncode, done.stderr)
        return done.stdout

    def test_older_cluster_on_the_default_port_is_announced(self):
        sortie = self.avis(self.LIGNE_16 + self.LIGNE_18)
        self.assertIn("16/main (port 5432)", sortie)
        self.assertIn("18/main (port 5433)", sortie)
        self.assertIn("Mettre à niveau le serveur PostgreSQL", sortie)
        self.assertIn('"Upgrade the PostgreSQL server"', sortie)

    def test_a_very_old_major_is_compared_as_a_number(self):
        sortie = self.avis(
            "9.6 main 5432 online postgres /var/lib/postgresql/9.6/main x\\n"
        )
        self.assertIn("9.6/main", sortie)

    def test_same_major_on_the_default_port_says_nothing(self):
        self.assertEqual("", self.avis(self.LIGNE_16, choisie="16"))

    def test_upgraded_machine_says_nothing(self):
        # pg_upgradecluster échange les ports : le nouveau prend 5432, et
        # l'ancien, gardé, n'est plus celui qu'Odoo joint.
        clusters = (
            "16 main 5433 down postgres /var/lib/postgresql/16/main x\\n"
            "18 main 5432 online postgres /var/lib/postgresql/18/main x\\n"
        )
        self.assertEqual("", self.avis(clusters))

    def test_without_pg_lsclusters_says_nothing(self):
        os.remove(os.path.join(self.faux, "pg_lsclusters"))
        done, _trace = self.lancer(
            "el_pg_avis_ancien_cluster",
            EL_PG_CHOISIE="18",
            PATH=self.faux + ":/nonexistent",
        )
        self.assertEqual(0, done.returncode, done.stderr)
        self.assertEqual("", done.stdout)


class TestInstallateurDebian(unittest.TestCase):
    """install_debian_dependency.sh refuse de tourner hors de Debian et
    d'Ubuntu : on vérifie qu'il délègue à la bibliothèque, et où."""

    def setUp(self):
        with open(DEBIAN) as handle:
            self.script = handle.read()

    def test_it_installs_through_the_library_and_stops_on_failure(self):
        self.assertIn(
            ". ./script/install/lib_postgres_version.sh", self.script
        )
        self.assertIn("el_pg_installer || exit 1", self.script)
        self.assertNotIn("PG_MIN=16", self.script)

    def test_the_old_cluster_notice_is_the_last_command(self):
        lignes = [
            ligne
            for ligne in self.script.splitlines()
            if ligne.strip() and not ligne.lstrip().startswith("#")
        ]
        self.assertEqual("el_pg_avis_ancien_cluster", lignes[-1])


if __name__ == "__main__":
    unittest.main()
