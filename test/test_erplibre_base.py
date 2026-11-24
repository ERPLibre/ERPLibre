#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La base distante d'un ERPLibre déployé par SSH : la fiche, le fichier
d'environnement, son dépôt sans ligne de commande, et le bloc joué sur la
VM."""

import re
import subprocess
import sys
import unittest

from script.lib_valid import ValidationError
from script.remote import deploy_target as D
from script.remote import erplibre_base as E

DISTANTE = {
    "db_mode": "distant",
    "db_host": "sql-invente.exemple.test",
    "db_user": "role_invente",
    "db_name": "base_inventee",
    "ca_root": "/chemin/invente/racine.crt",
}
MDP = 'mdp"invente\\avec$dollar'
ADMIN = "maitre-invente"


def lit_env(texte):
    """Relit un EnvironmentFile comme systemd le fait pour une valeur entre
    guillemets : `\\\\` et `\\"` désechappés."""
    lu = {}
    for ligne in texte.splitlines():
        m = re.fullmatch(r'([A-Z_]+)="(.*)"', ligne)
        assert m, ligne
        lu[m.group(1)] = re.sub(r"\\(.)", r"\1", m.group(2))
    return lu


class LaFiche(unittest.TestCase):
    def test_local_clears_remote_leftovers(self):
        rendu = E.valider_base(dict(DISTANTE, db_mode="local"))
        self.assertEqual("local", rendu["db_mode"])
        self.assertEqual("", rendu["db_host"])
        self.assertEqual("", rendu["ca_root"])

    def test_remote_defaults_to_verify_full(self):
        rendu = E.valider_base(DISTANTE)
        self.assertEqual("verify-full", rendu["db_sslmode"])
        self.assertEqual("sql-invente.exemple.test", rendu["db_host"])

    def test_an_ip_address_is_accepted(self):
        self.assertEqual(
            "10.0.0.5",
            E.valider_base(dict(DISTANTE, db_host="10.0.0.5"))["db_host"],
        )

    def test_remote_refusals(self):
        for change in (
            {"db_mode": "ailleurs"},
            {"db_host": ""},
            {"db_host": "a;rm -rf"},
            {"db_user": ""},
            {"db_name": "Base-Avec-Tiret"},
            {"db_port": "99999"},
            {"db_sslmode": "peut-etre"},
            {"ca_root": ""},
        ):
            with self.subTest(change=change):
                with self.assertRaises(ValidationError):
                    E.valider_base(dict(DISTANTE, **change))

    def test_no_root_is_needed_when_nothing_is_verified(self):
        rendu = E.valider_base(
            dict(DISTANTE, ca_root="", db_sslmode="require")
        )
        self.assertEqual("require", rendu["db_sslmode"])

    def test_the_target_validates_its_database(self):
        fiche = dict(
            DISTANTE,
            name="cible-inventee",
            target="compte@machine-inventee",
        )
        with self.assertRaises(ValidationError):
            D.validate(dict(fiche, db_host=""))
        self.assertEqual("distant", D.validate(fiche)["db_mode"])
        self.assertEqual(
            "local", D.validate(dict(fiche, db_mode="local"))["db_mode"]
        )


class LeFichierDEnvironnement(unittest.TestCase):
    def test_every_variable_round_trips_the_systemd_quoting(self):
        lu = lit_env(E.texte_env(DISTANTE, MDP, ADMIN))
        self.assertEqual(MDP, lu["PGPASSWORD"])
        self.assertEqual(ADMIN, lu["ODOO_ADMIN_PASSWD"])
        self.assertEqual("5432", lu["PGPORT"])
        self.assertEqual("verify-full", lu["PGSSLMODE"])
        self.assertEqual(E.RACINE_HOTE, lu["PGSSLROOTCERT"])
        self.assertEqual(E.MAGASIN_SYSTEME, lu["REQUESTS_CA_BUNDLE"])

    def test_no_root_no_root_variable(self):
        texte = E.texte_env(
            dict(DISTANTE, ca_root="", db_sslmode="require"), MDP, ADMIN
        )
        self.assertNotIn("PGSSLROOTCERT", texte)

    def test_refusals(self):
        with self.assertRaises(ValidationError):
            E.texte_env(dict(DISTANTE, db_mode="local"), MDP, ADMIN)
        for mdp, admin in (("", ADMIN), (MDP, "")):
            with self.assertRaises(ValidationError):
                E.texte_env(DISTANTE, mdp, admin)


class LeDepot(unittest.TestCase):
    def deposer(self, codes=(0, 0)):
        vus = []
        rendus = iter(codes)

        def run(hote, distante, entree=None):
            vus.append((distante, entree.read()))
            return next(rendus), ""

        code, _s = E.deposer(
            {"target": "machine-inventee"},
            DISTANTE,
            MDP,
            ADMIN,
            lire_racine=lambda c: b"-----RACINE INVENTEE-----",
            run=run,
        )
        return code, vus

    def test_the_secret_travels_on_stdin_never_in_the_command(self):
        code, vus = self.deposer()
        self.assertEqual(0, code)
        self.assertEqual(2, len(vus))
        for distante, octets in vus:
            self.assertNotIn(MDP, distante)
            self.assertNotIn(ADMIN, distante)
            self.assertIn("umask 077", distante)
        self.assertEqual(MDP, lit_env(vus[0][1].decode())["PGPASSWORD"])
        self.assertIn(b"RACINE INVENTEE", vus[1][1])

    def test_a_failed_deposit_stops(self):
        code, vus = self.deposer(codes=(255,))
        self.assertEqual(255, code)
        self.assertEqual(1, len(vus))


class LeBlocSurLaVM(unittest.TestCase):
    def test_it_is_valid_shell(self):
        vu = subprocess.run(
            ["bash", "-n", "-c", E.cmd_service("/opt/erplibre")],
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, vu.returncode, vu.stderr)

    def test_the_unit_is_the_launcher_s_without_local_postgresql(self):
        bloc = E.cmd_service("/opt/erplibre")
        self.assertNotIn("Requires=postgresql.service", bloc)
        self.assertIn(f"EnvironmentFile={E.ENV_HOTE}", bloc)
        self.assertIn("erplibre_serve.py", bloc)
        self.assertIn("--racine $SVC_DIR", bloc)

    def test_the_base_is_proven_before_odoo_starts(self):
        bloc = E.cmd_service("/opt/erplibre")
        self.assertLess(
            bloc.index("SELECT 1"), bloc.index("enable --now erplibre")
        )
        self.assertIn(f"-p EnvironmentFile={E.ENV_HOTE}", bloc)

    def test_the_installer_uses_it_only_for_a_remote_base(self):
        sys.argv, garde = ["todo.py"], sys.argv
        try:
            from script.todo.todo import TODO

            todo = TODO.__new__(TODO)
            distante = todo._qemu_erplibre_remote_cmd(
                "develop", prod=True, base_distante=True
            )
            locale = todo._qemu_erplibre_remote_cmd("develop", prod=True)
        finally:
            sys.argv = garde
        self.assertIn(E.cmd_service("/opt/erplibre").strip()[:60], distante)
        self.assertNotIn("Requires=postgresql.service", distante)
        self.assertIn("Requires=postgresql.service", locale)
        self.assertNotIn("erplibre_serve.py", locale)


if __name__ == "__main__":
    unittest.main()
