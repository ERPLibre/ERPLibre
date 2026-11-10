#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""TODO › Execute › Database › « Upgrade the PostgreSQL server ».

Le parcours tourne pour de vrai, contre des commandes factices placées en
tête du PATH : pg_lsclusters, pg_upgradecluster, pg_dropcluster, pg_dump,
psql, systemctl, dpkg-query, make et sudo. Chacune note ses arguments dans
une trace ; l'état des clusters vit dans un fichier que pg_upgradecluster,
pg_dropcluster et make réécrivent comme le feraient les vrais. Rien n'est
installé, arrêté ni migré.
"""

import contextlib
import datetime
import io
import os
import shutil
import tempfile
import unittest
from unittest import mock

from script.todo import postgresql_upgrade, todo_i18n

FAUSSES = {
    # sudo note, retire « -u compte », puis lance la commande.
    "sudo": 'echo "sudo $*" >> "$TRACE"\n'
    '[[ "$1" == -u ]] && shift 2\nexec "$@"',
    "pg_lsclusters": 'echo "pg_lsclusters $*" >> "$TRACE"\n'
    'cat "$ETAT/clusters"',
    "pg_upgradecluster": 'echo "pg_upgradecluster $*" >> "$TRACE"\n'
    'code="${FAUX_UPGRADE_CODE:-0}"\n'
    '(( code )) && exit "$code"\n'
    'cp "$ETAT/clusters_apres" "$ETAT/clusters"',
    "pg_dropcluster": 'echo "pg_dropcluster $*" >> "$TRACE"\n'
    '[[ "$1" == --stop ]] && shift\n'
    'grep -v "^$1 $2 " "$ETAT/clusters" > "$ETAT/c" || true\n'
    'mv "$ETAT/c" "$ETAT/clusters"',
    # psql rend le contenu de bases_<port>, ou échoue s'il n'existe pas.
    "psql": 'echo "psql $*" >> "$TRACE"\n'
    'while [[ $# -gt 0 && "$1" != -p ]]; do shift; done\n'
    '[[ -f "$ETAT/bases_$2" ]] || exit 2\n'
    'cat "$ETAT/bases_$2"',
    "pg_dump": 'echo "pg_dump $*" >> "$TRACE"\n'
    'base="${@: -1}"\n'
    '[[ "$base" == "$FAUX_DUMP_ECHEC" ]] && exit 1\n'
    'while [[ "$1" != -f ]]; do shift; done\n'
    'echo dump > "$2"',
    "systemctl": 'echo "systemctl $*" >> "$TRACE"\n'
    '[[ "$1" == is-active ]] && { [[ "$3" == "$FAUX_ACTIF" ]]; exit; }\n'
    "exit 0",
    "dpkg-query": 'echo "dpkg-query $*" >> "$TRACE"\n'
    'paquet="${@: -1}"\n'
    '[[ -f "$ETAT/installe_${paquet#postgresql-}" ]] || exit 1\n'
    'echo -n "install ok installed"',
    # make pose le paquet et, comme apt, un cluster <version>/main vide.
    "make": 'echo "make $*" >> "$TRACE"\n'
    'v="${2#PG_VERSION=}"\n'
    'touch "$ETAT/installe_$v"\n'
    'echo "$v main 5433 online postgres" >> "$ETAT/clusters"\n'
    ': > "$ETAT/bases_5433"',
}

AVANT = "16 main 5432 online postgres /var/lib/postgresql/16/main x.log\n"
APRES = (
    "16 main 5433 down postgres /var/lib/postgresql/16/main x.log\n"
    "18 main 5432 online postgres /var/lib/postgresql/18/main x.log\n"
)
BASES = "base_a\t12 MB\nbase_b\t3 MB\n"


class Base(unittest.TestCase):
    def setUp(self):
        self.racine = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.racine)
        self.etat = os.path.join(self.racine, "etat")
        self.faux = os.path.join(self.racine, "bin")
        os.makedirs(self.etat)
        os.makedirs(self.faux)
        self.trace = os.path.join(self.racine, "trace")
        open(self.trace, "w").close()
        for nom, corps in FAUSSES.items():
            chemin = os.path.join(self.faux, nom)
            with open(chemin, "w") as handle:
                handle.write("#!/bin/bash\n" + corps + "\n")
            os.chmod(chemin, 0o755)
        self.ecrire(".odoo-version", "18.0\n", dans=self.racine)
        self.ecrire("clusters", AVANT)
        self.ecrire("clusters_apres", APRES)
        self.ecrire("bases_5432", BASES)
        self.environ(
            PATH=f"{self.faux}:{os.environ['PATH']}",
            TRACE=self.trace,
            ETAT=self.etat,
        )
        for cible, valeur in (
            (todo_i18n, ("_current_lang", "en")),
            (postgresql_upgrade, ("RACINE_BINAIRES", self.etat)),
        ):
            patch = mock.patch.object(cible, *valeur)
            patch.start()
            self.addCleanup(patch.stop)
        self.questions = []

    def environ(self, **valeurs):
        patch = mock.patch.dict(os.environ, valeurs)
        patch.start()
        self.addCleanup(patch.stop)

    def ecrire(self, nom, texte, dans=None):
        with open(os.path.join(dans or self.etat, nom), "w") as handle:
            handle.write(texte)

    def lancer(self, reponse=""):
        def demander(question):
            self.questions.append(question)
            return reponse

        sortie = io.StringIO()
        with contextlib.redirect_stdout(sortie):
            fini = postgresql_upgrade.mettre_a_niveau(
                racine=self.racine,
                demander=demander,
                maintenant=datetime.datetime(2030, 1, 2, 3, 4, 5),
            )
        self.sortie = sortie.getvalue()
        return fini

    def appels(self):
        with open(self.trace) as handle:
            return handle.read().splitlines()

    @property
    def dossier(self):
        return os.path.join(
            self.racine,
            "image_db",
            "postgresql_16_to_18_2030-01-02_03h04m05s",
        )


class TestPlan(Base):
    def test_the_plan_is_shown_and_the_default_answer_refuses(self):
        self.environ(FAUX_ACTIF="erplibre.service")
        self.assertFalse(self.lancer(reponse=""))
        self.assertEqual(1, len(self.questions))
        for attendu in (
            "16/main, port 5432",
            "16 -> 18",
            "the minimum Odoo 18.0 requires",
            "base_a  12 MB",
            "base_b  3 MB",
            self.dossier,
            "postgresql-18 installed by: make install_os PG_VERSION=18",
            "Service erplibre.service stopped, then restarted.",
            "The old cluster 16/main is kept, stopped",
        ):
            self.assertIn(attendu, self.sortie)
        self.assertIn("Cancelled.", self.sortie)
        # Rien n'a bougé : aucune commande qui écrit, aucun dossier créé.
        for appel in self.appels():
            self.assertFalse(
                appel.startswith(
                    ("sudo", "pg_dump", "pg_upgradecluster", "make")
                ),
                appel,
            )
        self.assertFalse(os.path.exists(self.dossier))

    def test_nothing_is_done_when_already_up_to_date(self):
        self.ecrire("clusters", APRES)
        self.assertTrue(self.lancer(reponse="y"))
        self.assertIn("nothing to do", self.sortie)
        self.assertEqual([], self.questions)
        self.assertEqual(["pg_lsclusters -h"], self.appels())

    def test_without_requirement_the_newest_available_is_offered(self):
        # Odoo 16 n'exige rien : le maximum du catalogue l'emporte sur un
        # serveur 17 installé, et un 19 installé l'emporte sur le catalogue.
        self.ecrire(".odoo-version", "16.0\n", dans=self.racine)
        for version in ("17", "19"):
            os.makedirs(os.path.join(self.etat, version, "bin"))
            self.ecrire(os.path.join(version, "bin", "postgres"), "")
        self.assertEqual((19, False), postgresql_upgrade.version_cible("16.0"))
        shutil.rmtree(os.path.join(self.etat, "19"))
        self.assertEqual((18, False), postgresql_upgrade.version_cible("16.0"))
        self.lancer(reponse="")
        self.assertIn("the newest available", self.sortie)

    def test_elsewhere_than_debian_it_says_it_is_not_supported(self):
        vide = os.path.join(self.racine, "vide")
        os.makedirs(vide)
        self.environ(PATH=vide)
        self.assertFalse(self.lancer(reponse="y"))
        self.assertIn("Debian and Ubuntu only", self.sortie)
        self.assertIn("pg_dump -Fc", self.sortie)
        self.assertEqual([], self.appels())


class TestApplication(Base):
    def test_a_failed_backup_stops_before_anything_is_upgraded(self):
        self.environ(FAUX_ACTIF="erplibre.service", FAUX_DUMP_ECHEC="base_b")
        self.assertFalse(self.lancer(reponse="y"))
        appels = self.appels()
        self.assertIn("Backup of base_b failed (exit code 1).", self.sortie)
        self.assertIn("16/main was not touched", self.sortie)
        self.assertTrue(
            os.path.isfile(os.path.join(self.dossier, "base_a.dump"))
        )
        self.assertFalse(any(a.startswith("make") for a in appels))
        self.assertFalse(any("pg_upgradecluster" in a for a in appels))
        # Le service arrêté pour la sauvegarde est relancé.
        self.assertIn("sudo systemctl stop erplibre.service", appels)
        self.assertIn("sudo systemctl start erplibre.service", appels)

    def test_the_full_upgrade_prints_the_drop_command_without_running_it(
        self,
    ):
        self.environ(FAUX_ACTIF="erplibre.service")
        self.assertTrue(self.lancer(reponse="o"))
        appels = self.appels()
        ordre = [
            "sudo systemctl stop erplibre.service",
            f"pg_dump -Fc -p 5432 -f {self.dossier}/base_a.dump base_a",
            f"pg_dump -Fc -p 5432 -f {self.dossier}/base_b.dump base_b",
            "make install_os PG_VERSION=18",
            "sudo pg_dropcluster --stop 18 main",
            "sudo pg_upgradecluster -v 18 16 main",
            "sudo systemctl start erplibre.service",
        ]
        positions = [appels.index(a) for a in ordre]
        self.assertEqual(sorted(positions), positions)
        # Le cluster vide n'est retiré qu'après avoir été lu, en postgres.
        self.assertTrue(
            any(a.startswith("sudo -u postgres psql -p 5433") for a in appels)
        )
        self.assertIn("sudo pg_dropcluster 16 main", self.sortie)
        self.assertFalse(
            any(a.startswith("pg_dropcluster 16") for a in appels), appels
        )

    def test_an_installed_package_is_not_reinstalled(self):
        self.ecrire("installe_18", "")
        self.assertTrue(self.lancer(reponse="y"))
        appels = self.appels()
        self.assertFalse(any(a.startswith("make") for a in appels))
        self.assertFalse(any("pg_dropcluster" in a for a in appels))

    def test_a_new_cluster_that_holds_databases_is_not_dropped(self):
        self.ecrire("installe_18", "")
        self.ecrire("clusters", AVANT + "18 main 5433 online postgres\n")
        self.ecrire("bases_5433", "autre\t1 MB\n")
        self.assertFalse(self.lancer(reponse="y"))
        appels = self.appels()
        self.assertIn("18/main already holds databases: autre", self.sortie)
        self.assertFalse(any("pg_dropcluster" in a for a in appels))
        self.assertFalse(any("pg_upgradecluster" in a for a in appels))

    def test_a_failed_upgrade_says_how_to_go_back(self):
        self.ecrire("installe_18", "")
        self.environ(FAUX_ACTIF="erplibre.service", FAUX_UPGRADE_CODE="3")
        self.assertFalse(self.lancer(reponse="y"))
        self.assertIn("pg_upgradecluster failed (exit code 3)", self.sortie)
        self.assertIn("sudo pg_ctlcluster 16 main start", self.sortie)
        self.assertIn("sudo systemctl start erplibre.service", self.sortie)
        # Le cluster est dans un état incertain : le service n'est pas
        # relancé dessus d'office, la commande est donnée.
        self.assertNotIn(
            "sudo systemctl start erplibre.service", self.appels()
        )

    def test_a_missing_database_after_the_upgrade_is_a_failure(self):
        self.ecrire("installe_18", "")
        with open(os.path.join(self.faux, "pg_upgradecluster"), "a") as f:
            f.write('echo "base_a\t12 MB" > "$ETAT/bases_5432"\n')
        self.assertFalse(self.lancer(reponse="y"))
        self.assertIn("does not list the same databases", self.sortie)
        self.assertIn("still on disk", self.sortie)


class TestLecture(unittest.TestCase):
    def test_clusters_are_read_from_pg_lsclusters(self):
        self.assertEqual(
            [
                {
                    "version": "9.6",
                    "nom": "main",
                    "port": 5432,
                    "etat": "down",
                },
                {"version": "18", "nom": "b", "port": 5433, "etat": "online"},
            ],
            postgresql_upgrade.lire_clusters(
                "9.6 main 5432 down postgres /d /l\n\n18 b 5433 online\n"
            ),
        )

    def test_old_numbering_compares_below_new(self):
        self.assertLess(
            postgresql_upgrade.majeure("9.6"), postgresql_upgrade.majeure(18)
        )


if __name__ == "__main__":
    unittest.main()
