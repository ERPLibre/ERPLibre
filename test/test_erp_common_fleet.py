#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Retrait d'une instance (script/erp_common/fleet).

Le plan est injecté : ce banc prouve le pilote, pas les étapes d'un ERP.
Ce qui se garde :
- rien ne s'enlève sans le nom retapé en entier ; l'essai à blanc montre
  chaque étape sans rien toucher ;
- ce qui est déjà parti compte comme retiré : un retrait interrompu se
  relance ;
- l'entrée du registre private/<erp>/instances.json ne part que si tout a
  réussi, et seulement celle de l'ERP reçu ;
- les étapes communes sont rejouables : IF EXISTS, --if-exists, -f.
Chaque test qui dépend du nom de l'ERP tourne pour deux noms.
"""

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

from script.erp_common import fleet  # noqa: E402

# Deux noms : celui d'un ERP réel et un nom inventé, pour prouver que rien
# n'est écrit en dur.
ERPS = ("dolibarr", "acme")


class Systeme:
    def __init__(self):
        self.appels = []
        self.echec = set()
        self.reponse = "ERROR"

    def run(self, argv):
        self.appels.append(list(argv))
        if any(m in " ".join(argv) for m in self.echec):
            return 1, self.reponse
        return 0, ""


class Banc(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.racine = Path(tmp.name)
        self.etat = self.racine / "etat" / "erp"
        (self.etat / "secrets").mkdir(parents=True)
        self.sys = Systeme()
        self.avis = None

    def plan(self, name, entry, system, root):
        return (
            [
                fleet.Step(["engine", "rm", "-f", f"{name}-web"]),
                fleet.Step(["engine", "volume", "rm", "-f", f"{name}-data"]),
                fleet.remove_tree(str(self.etat)),
            ],
            self.avis,
        )

    def registre(self, erp):
        return self.racine / "private" / erp / "instances.json"

    def ecrire(self, erp, instances):
        chemin = self.registre(erp)
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_text(json.dumps({"instances": instances}))

    def lire(self, erp):
        return json.loads(self.registre(erp).read_text())["instances"]

    def retirer(self, erp, confirm="erp", dry_run=False):
        sortie = io.StringIO()
        with contextlib.redirect_stdout(sortie):
            code = fleet.remove(
                erp,
                "erp",
                {"mode": "dev"},
                confirm,
                dry_run,
                self.sys,
                str(self.racine),
                self.plan,
            )
        return code, sortie.getvalue()


class TestPilote(Banc):
    def test_nothing_goes_without_the_name_retyped(self):
        for erp in ERPS:
            self.ecrire(erp, {"erp": {}})
            for mauvais in ("", "er"):
                with self.subTest(erp=erp, mauvais=mauvais):
                    code, _s = self.retirer(erp, confirm=mauvais)
                    self.assertEqual(code, 2)
            self.assertEqual(self.sys.appels, [])
            self.assertIn("erp", self.lire(erp))
            self.assertTrue((self.etat / "secrets").exists())

    def test_the_dry_run_shows_every_step_and_touches_nothing(self):
        for erp in ERPS:
            with self.subTest(erp=erp):
                self.ecrire(erp, {"erp": {}})
                code, sortie = self.retirer(erp, confirm="", dry_run=True)
                self.assertEqual(code, 0)
                self.assertEqual(self.sys.appels, [])
                self.assertIn("[dry-run] engine rm -f erp-web", sortie)
                self.assertIn(f"[dry-run] rm -rf {self.etat}", sortie)
                self.assertTrue((self.etat / "secrets").exists())
                self.assertIn("erp", self.lire(erp))

    def test_every_step_runs_and_only_this_erp_entry_goes(self):
        for erp in ERPS:
            with self.subTest(erp=erp):
                (self.etat / "secrets").mkdir(parents=True, exist_ok=True)
                self.ecrire(erp, {"erp": {}, "autre": {}})
                autre = "zzz"
                self.ecrire(autre, {"erp": {}})
                self.sys.appels.clear()
                code, sortie = self.retirer(erp)
                self.assertEqual(code, 0, sortie)
                self.assertEqual(
                    self.sys.appels,
                    [
                        ["engine", "rm", "-f", "erp-web"],
                        ["engine", "volume", "rm", "-f", "erp-data"],
                    ],
                )
                self.assertFalse(self.etat.exists())
                self.assertEqual(self.lire(erp), {"autre": {}})
                self.assertIn("erp", self.lire(autre))

    def test_what_is_already_gone_counts_as_removed(self):
        # Relancer un retrait interrompu : les conteneurs ne sont plus là.
        self.sys.echec.add(" rm ")
        self.sys.reponse = "Error: no such container"
        for erp in ERPS:
            with self.subTest(erp=erp):
                self.ecrire(erp, {"erp": {}})
                code, _s = self.retirer(erp)
                self.assertEqual(code, 0)
                self.assertNotIn("erp", self.lire(erp))

    def test_a_failed_step_keeps_the_registry_entry(self):
        self.sys.echec.add("volume rm")
        for erp in ERPS:
            with self.subTest(erp=erp):
                self.ecrire(erp, {"erp": {}})
                code, sortie = self.retirer(erp)
                self.assertEqual(code, 1)
                self.assertIn("erp", self.lire(erp))
                self.assertIn("✗ engine volume rm -f erp-data — ERROR", sortie)

    def test_a_failed_local_action_keeps_the_registry_entry(self):
        def refuse():
            raise PermissionError("refusé")

        self.plan = lambda name, entry, system, root: (
            [fleet.Step(describe="rm -rf /verrou", action=refuse)],
            None,
        )
        self.ecrire("acme", {"erp": {}})
        code, sortie = self.retirer("acme")
        self.assertEqual(code, 1)
        self.assertIn("✗ rm -rf /verrou — refusé", sortie)
        self.assertIn("erp", self.lire("acme"))

    def test_the_notice_is_printed_after_the_steps(self):
        self.avis = "Gardé : vos modules"
        self.ecrire("acme", {"erp": {}})
        for dry_run in (True, False):
            with self.subTest(dry_run=dry_run):
                _code, sortie = self.retirer("acme", dry_run=dry_run)
                self.assertIn("Gardé : vos modules", sortie)


class TestEtapes(unittest.TestCase):
    def test_mariadb_drops_its_database_and_account(self):
        etapes = fleet.drop_database(
            {"db_name": "acme_erp"}, ["sudo", "mariadb"]
        )
        self.assertEqual(len(etapes), 1)
        sql = etapes[0].text()
        self.assertTrue(sql.startswith("sudo mariadb -e"))
        self.assertIn("DROP DATABASE IF EXISTS acme_erp", sql)
        self.assertIn("DROP USER IF EXISTS 'acme_erp'@'localhost'", sql)

    def test_postgresql_drops_its_database_and_role(self):
        etapes = fleet.drop_database(
            {"db_name": "acme_erp", "db": "postgresql"}, ["sudo", "mariadb"]
        )
        self.assertEqual(
            [e.text() for e in etapes],
            [
                "sudo -u postgres dropdb --if-exists acme_erp",
                "sudo -u postgres dropuser --if-exists acme_erp",
            ],
        )

    def test_local_removals_are_replayable(self):
        with tempfile.TemporaryDirectory() as tmp:
            arbre = Path(tmp) / "etat"
            (arbre / "a").mkdir(parents=True)
            fichier = Path(tmp) / "conf.cfg"
            fichier.write_text("x")
            for etape in (
                fleet.remove_tree(str(arbre)),
                fleet.remove_file(str(fichier)),
            ):
                etape.action()
                etape.action()
            self.assertFalse(arbre.exists())
            self.assertFalse(fichier.exists())
            self.assertEqual(
                fleet.remove_file(str(fichier)).text(), f"rm -f {fichier}"
            )
            self.assertEqual(
                fleet.remove_tree(str(arbre)).text(), f"rm -rf {arbre}"
            )


if __name__ == "__main__":
    unittest.main()
