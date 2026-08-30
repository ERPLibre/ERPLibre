#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Quel fichier de configuration Odoo lit, quand personne ne le dit.

Sans ODOO_RC, Odoo retombe sur `~/.odoorc` — un fichier PERSONNEL que
rien ne synchronise avec le `config.conf` du dépôt. Mesuré sur une vraie
migration : un `~/.odoorc` portant un mot de passe maître haché faisait
échouer « odoo_bin.sh db --drop » par AccessDenied, alors que
`db_restore.py` venait de lire « admin_passwd = admin » dans config.conf
et d'en conclure qu'aucun mot de passe n'était nécessaire.

Les deux avaient raison. Ils ne parlaient pas du même fichier — et rien,
nulle part, ne les confrontait. Le drop échouait, le clone butait ensuite
sur « database already exists », et la boucle de reprise faisait passer
les deux pour un accident. Huit fois par migration.
"""

import io
import os
import subprocess
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.join(REPO, "script", "lib_odoo_rc.sh")


class Base(unittest.TestCase):
    def resoudre(self, racine, environ=None):
        """Ce que la résolution pose dans ODOO_RC, pour cette racine."""
        env = dict(os.environ)
        env.pop("ODOO_RC", None)
        env.update(environ or {})
        done = subprocess.run(
            [
                "bash",
                "-c",
                f'source {LIB!r}; odoo_rc_resolve "$1"; echo "${{ODOO_RC:-}}"',
                "bash",
                racine,
            ],
            capture_output=True,
            text=True,
            env=env,
        )
        self.assertEqual(0, done.returncode, done.stderr)
        return done.stdout.strip()


class TestWhichFileIsChosen(Base):
    def setUp(self):
        import shutil
        import tempfile

        self.dossier = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dossier)

    def config(self):
        chemin = os.path.join(self.dossier, "config.conf")
        with io.open(chemin, "w", encoding="utf-8") as handle:
            handle.write("[options]\nadmin_passwd = admin\n")
        return chemin

    def test_the_repository_config_wins_over_the_personal_one(self):
        # C'est tout le propos : ~/.odoorc n'est plus consulté.
        self.assertEqual(self.config(), self.resoudre(self.dossier))

    def test_an_explicit_choice_is_never_overridden(self):
        # Odoo lit ODOO_RC avant ~/.odoorc, et « -c » avant ODOO_RC :
        # écraser une valeur posée exprès retirerait ce choix.
        self.config()
        self.assertEqual(
            "/ailleurs/odoo.conf",
            self.resoudre(self.dossier, {"ODOO_RC": "/ailleurs/odoo.conf"}),
        )

    def test_without_a_repository_config_nothing_is_forced(self):
        # Sur une machine sans config.conf ni /etc/odoo/odoo.conf, on
        # laisse Odoo faire ce qu'il a toujours fait.
        vide = self.resoudre(self.dossier)
        self.assertIn(vide, ("", "/etc/odoo/odoo.conf"))

    def test_it_never_fails_the_command_that_sourced_it(self):
        # Elle est appelée au tout début d'odoo_bin.sh : y échouer
        # empêcherait de lancer Odoo, pour une question de configuration.
        done = subprocess.run(
            ["bash", "-c", f"source {LIB!r}; odoo_rc_resolve /inexistant"],
            capture_output=True,
            text=True,
            env={k: v for k, v in os.environ.items() if k != "ODOO_RC"},
        )
        self.assertEqual(0, done.returncode, done.stderr)


class TestTheEntryPointUsesIt(unittest.TestCase):
    def source(self, nom):
        with io.open(os.path.join(REPO, nom), encoding="utf-8") as handle:
            return handle.read()

    def test_odoo_bin_resolves_before_running_odoo(self):
        source = self.source("odoo_bin.sh")
        self.assertIn("odoo_rc_resolve", source)
        self.assertLess(
            source.index("odoo_rc_resolve"), source.index("odoo-bin")
        )

    def test_the_order_matches_what_db_restore_checks(self):
        # `db_restore.py` lit ./config.conf puis /etc/odoo/odoo.conf pour
        # décider s'il faut un mot de passe maître. Si Odoo en lisait un
        # autre, cette vérification ne vérifierait rien.
        lib = self.source(os.path.join("script", "lib_odoo_rc.sh"))
        restore = self.source(
            os.path.join("script", "database", "db_restore.py")
        )
        for candidat in ("config.conf", "/etc/odoo/odoo.conf"):
            self.assertIn(candidat, lib, candidat)
            self.assertIn(candidat, restore, candidat)
        self.assertLess(
            lib.index("config.conf"), lib.index("/etc/odoo/odoo.conf")
        )
        self.assertLess(
            restore.index("config.conf"),
            restore.index("/etc/odoo/odoo.conf"),
        )


if __name__ == "__main__":
    unittest.main()
