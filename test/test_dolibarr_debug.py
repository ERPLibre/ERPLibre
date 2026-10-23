#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le profil de déverminage d'une instance Dolibarr : l'allumer, le rendre.

Un système simulé joue PHP (il rend l'état d'avant, reçoit l'état à
remettre) ; conf.php est un vrai fichier. Ce qui se garde :
- allumer retient exactement l'état d'avant, éteindre le remet, y compris
  une constante qui n'existait pas ;
- en développement natif, conf.php passe prod à 0 et le mode strict à 1,
  puis retrouve ses valeurs ;
- une production est refusée sans son nom retapé ;
- le suivi du journal filtre par expression.
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

from script.dolibarr import debug  # noqa: E402

AVANT = {
    "MAIN_FEATURES_LEVEL": None,
    "SYSLOG_LEVEL": "5",
    "MAIN_MODULE_SYSLOG": "1",
    "MAIN_MODULE_DEBUGBAR": None,
}


class Systeme:
    def __init__(self):
        self.appels = []  # (argv, stdin)
        self.echec = False

    def run(self, argv, env=None, stdin_path=None):
        recu = Path(stdin_path).read_text() if stdin_path else ""
        self.appels.append((list(argv), recu))
        if self.echec:
            return 1, "PHP Fatal error"
        code = " ".join(argv)
        if "ERPLIBRE_DEBUG_ON" in code:
            return 0, "bruit\nERPLIBRE_DEBUG " + json.dumps(AVANT) + "\n"
        if "ERPLIBRE_DEBUG_OFF" in code:
            return 0, "ERPLIBRE_DEBUG_OFF\n"
        return 0, ""

    def engine(self, moteur):
        return {
            "moteur": moteur,
            "sans_sudo": True,
            "avec_sudo": False,
            "rootless": True,
            "docker_host": None,
        }


class Banc(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.racine = Path(tmp.name)
        self.etat = self.racine / "etat" / "erp"
        self.etat.mkdir(parents=True)
        self.checkout = self.racine / "dolibarr"
        conf = self.checkout / "htdocs" / "conf" / "conf.php"
        conf.parent.mkdir(parents=True)
        conf.write_text(
            "<?php\n$dolibarr_main_prod='1';\n$dolibarr_main_db_name='x';\n"
        )
        conf.chmod(0o600)
        self.conf = conf
        self.entree = {
            "mode": "dev",
            "runtime": "native",
            "code_root": str(self.checkout),
            "data_root": str(self.etat / "documents"),
            "state_dir": str(self.etat),
        }
        self.sys = Systeme()

    def lancer(self, *argv, entree=None):
        registre = self.racine / "private" / "dolibarr" / "instances.json"
        registre.parent.mkdir(parents=True, exist_ok=True)
        registre.write_text(
            json.dumps({"instances": {"erp": entree or self.entree}})
        )
        sortie = io.StringIO()
        with contextlib.redirect_stdout(sortie):
            code = debug.main(
                list(argv), root=str(self.racine), system=self.sys
            )
        return code, sortie.getvalue()


class TestAllumer(Banc):
    def test_on_saves_what_was_there_and_sets_the_debug_profile(self):
        code, sortie = self.lancer("on", "--instance", "erp")
        self.assertEqual(code, 0, sortie)
        etat = json.loads((self.etat / "debug.json").read_text())
        self.assertEqual(etat["constants"], AVANT)
        self.assertEqual(
            etat["conf"],
            {"dolibarr_main_prod": "1", "dolibarr_strict_mode": None},
        )
        texte = self.conf.read_text()
        self.assertIn("$dolibarr_main_prod='0';", texte)
        self.assertIn("$dolibarr_strict_mode='1';", texte)
        self.assertEqual(self.conf.stat().st_mode & 0o777, 0o600)
        php = " ".join(self.sys.appels[0][0])
        for attendu in ("modDebugBar", "modSyslog", "MAIN_FEATURES_LEVEL"):
            self.assertIn(attendu, php)

    def test_on_twice_keeps_the_first_saved_state(self):
        self.lancer("on", "--instance", "erp")
        premier = (self.etat / "debug.json").read_text()
        code, _s = self.lancer("on", "--instance", "erp")
        self.assertEqual(code, 0)
        self.assertEqual((self.etat / "debug.json").read_text(), premier)

    def test_a_php_failure_changes_nothing(self):
        self.sys.echec = True
        code, _s = self.lancer("on", "--instance", "erp")
        self.assertEqual(code, 1)
        self.assertFalse((self.etat / "debug.json").exists())
        self.assertIn("$dolibarr_main_prod='1';", self.conf.read_text())


class TestSansMarqueur(Banc):
    def test_php_without_its_marker_is_a_failure(self):
        # PHP mort après un avertissement, sortie 0 : rien n'a été allumé.
        self.sys.run = lambda argv, env=None, stdin_path=None: (
            0,
            "Warning: x\n",
        )
        code, _s = self.lancer("on", "--instance", "erp")
        self.assertEqual(code, 1)
        self.assertFalse((self.etat / "debug.json").exists())


class TestEteindre(Banc):
    def test_off_puts_everything_back_and_forgets_the_state(self):
        self.lancer("on", "--instance", "erp")
        code, sortie = self.lancer("off", "--instance", "erp")
        self.assertEqual(code, 0, sortie)
        argv, recu = self.sys.appels[-1]
        self.assertIn("ERPLIBRE_DEBUG_OFF", " ".join(argv))
        self.assertEqual(json.loads(recu), AVANT)
        texte = self.conf.read_text()
        self.assertIn("$dolibarr_main_prod='1';", texte)
        self.assertNotIn("dolibarr_strict_mode", texte)
        self.assertFalse((self.etat / "debug.json").exists())

    def test_a_failed_off_keeps_the_saved_state(self):
        self.lancer("on", "--instance", "erp")
        self.sys.echec = True
        code, _s = self.lancer("off", "--instance", "erp")
        self.assertEqual(code, 1)
        self.assertTrue((self.etat / "debug.json").exists())
        self.assertIn("$dolibarr_main_prod='0';", self.conf.read_text())

    def test_off_without_on_does_nothing(self):
        code, _s = self.lancer("off", "--instance", "erp")
        self.assertEqual(code, 0)
        self.assertEqual(self.sys.appels, [])


class TestProduction(Banc):
    def test_production_needs_its_name_retyped(self):
        prod = dict(self.entree, mode="prod", user="dolibarr_erp")
        code, _s = self.lancer("on", "--instance", "erp", entree=prod)
        self.assertEqual(code, 2)
        self.assertEqual(self.sys.appels, [])


class TestConteneur(Banc):
    def test_the_container_gets_the_constants_through_its_engine(self):
        entree = {
            "mode": "dev",
            "runtime": "container",
            "engine": "podman",
            "containers": ["x-db", "x-web", "x-cron"],
            "state_dir": str(self.etat),
        }
        code, sortie = self.lancer("on", "--instance", "erp", entree=entree)
        self.assertEqual(code, 0, sortie)
        argv = self.sys.appels[0][0]
        # En www-data : root y laisserait des dossiers que le site ne peut
        # plus écrire.
        self.assertEqual(
            argv[:6], ["podman", "exec", "-u", "www-data", "x-web", "php"]
        )
        self.assertIn("conf.php", sortie)  # dit que conf.php n'est pas touché
        self.lancer("off", "--instance", "erp", entree=entree)
        argv = self.sys.appels[-1][0]
        self.assertEqual(
            argv[:7],
            ["podman", "exec", "-i", "-u", "www-data", "x-web", "php"],
        )


class TestJournal(unittest.TestCase):
    def test_the_filter_keeps_matching_lines(self):
        lignes = ["INFO  x", "ERR   sql error", "DEBUG y", "ERR   other"]
        self.assertEqual(
            list(debug.matching(lignes, "ERR")),
            ["ERR   sql error", "ERR   other"],
        )
        self.assertEqual(list(debug.matching(lignes, None)), lignes)


if __name__ == "__main__":
    unittest.main()
