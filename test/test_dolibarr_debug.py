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
from unittest import mock

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
            "port": 8081,
            "url": "http://127.0.0.1:8081",
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


FPM = "/usr/sbin/php-fpm8.2"


class SystemeXdebug(Systeme):
    """PHP-FPM joué : -m liste Xdebug s'il est chargé pour tout l'hôte, ou
    par le .ini de l'instance quand le .so existe."""

    def __init__(self):
        super().__init__()
        self.hote = False
        self.so = True
        self.installs = []
        self.install_ok = True
        self.install_allume_hote = False
        self.install_fournit_so = True

    def run(self, argv, env=None, stdin_path=None):
        if argv[:2] == [FPM, "-m"]:
            self.appels.append((list(argv), ""))
            charge = self.hote
            avert = ""
            dossier = (env or {}).get("PHP_INI_SCAN_DIR", "").lstrip(":")
            ini = Path(dossier, debug.XDEBUG_INI) if dossier else None
            if ini and ini.exists() and "zend_extension" in ini.read_text():
                if self.so:
                    charge = True
                else:
                    # Ce que php-fpm écrit, sur la même sortie, sans le .so.
                    avert = (
                        "PHP Warning:  Failed loading Zend extension"
                        " 'xdebug.so' (tried: /usr/lib/php/x/xdebug.so)\n"
                    )
            return 0, avert + "[PHP Modules]\nCore\n" + (
                "\n[Zend Modules]\nXdebug\n" if charge else ""
            )
        return super().run(argv, env, stdin_path)

    def interactive(self, argv):
        self.installs.append(list(argv))
        if not self.install_ok:
            return 100
        self.so = self.install_fournit_so
        self.hote = self.hote or self.install_allume_hote
        return 0


class TestXdebug(Banc):
    def setUp(self):
        super().setUp()
        self.sys = SystemeXdebug()
        self.redemarrages = []
        for cible, valeur in (
            ("restart_fpm", lambda nom, racine: self.redemarrages.append(nom)),
            ("_fpm_binary", lambda: FPM),
            ("_family", lambda: "apt-get"),
        ):
            p = mock.patch.object(debug, cible, valeur)
            p.start()
            self.addCleanup(p.stop)
        self.ini = self.etat / "run" / "php.d" / debug.XDEBUG_INI
        self.launch = self.checkout / ".vscode" / "launch.json"

    def test_xdebug_is_loaded_in_the_instance_pool_only(self):
        code, sortie = self.lancer("on", "--instance", "erp", "--xdebug")
        self.assertEqual(code, 0, sortie)
        texte = self.ini.read_text()
        for attendu in (
            "zend_extension=xdebug.so",
            "xdebug.mode=debug",
            "xdebug.start_with_request=trigger",
            "xdebug.client_port=9003",
        ):
            self.assertIn(attendu, texte)
        self.assertEqual(self.redemarrages, ["erp"])
        self.assertEqual(self.sys.installs, [])
        config = json.loads(self.launch.read_text())["configurations"]
        self.assertEqual(
            config,
            [
                {
                    "name": "Dolibarr erp (Xdebug)",
                    "type": "php",
                    "request": "launch",
                    "port": 9003,
                }
            ],
        )
        self.assertTrue(
            json.loads((self.etat / "debug.json").read_text())["xdebug"]
        )
        self.assertIn("PhpStorm", sortie)

    def test_a_host_that_loads_it_already_gets_no_second_load(self):
        self.sys.hote = True
        code, sortie = self.lancer("on", "--instance", "erp", "--xdebug")
        self.assertEqual(code, 0, sortie)
        self.assertNotIn("zend_extension", self.ini.read_text())
        self.assertIn("xdebug.mode=debug", self.ini.read_text())

    def test_a_missing_xdebug_is_installed_then_not_loaded_twice(self):
        # Le paquet Debian l'allume pour tout l'hôte dès l'installation.
        self.sys.so = False
        self.sys.install_allume_hote = True
        code, sortie = self.lancer("on", "--instance", "erp", "--xdebug")
        self.assertEqual(code, 0, sortie)
        self.assertIn("php-xdebug", self.sys.installs[0])
        self.assertNotIn("zend_extension", self.ini.read_text())
        self.assertEqual(self.redemarrages, ["erp"])

    def test_a_failed_install_leaves_nothing(self):
        self.sys.so = False
        self.sys.install_ok = False
        code, _s = self.lancer("on", "--instance", "erp", "--xdebug")
        self.assertEqual(code, 1)
        self.assertFalse(self.ini.exists())
        self.assertEqual(self.redemarrages, [])
        etat = self.etat / "debug.json"
        self.assertFalse(
            etat.exists() and json.loads(etat.read_text()).get("xdebug")
        )

    def test_an_install_that_does_not_load_it_fails(self):
        self.sys.so = False
        self.sys.install_fournit_so = False
        code, _s = self.lancer("on", "--instance", "erp", "--xdebug")
        self.assertEqual(code, 1)
        self.assertFalse(self.ini.exists())
        self.assertEqual(len(self.sys.installs), 1)
        self.assertEqual(self.redemarrages, [])

    def test_xdebug_twice_restarts_once(self):
        self.lancer("on", "--instance", "erp", "--xdebug")
        code, _s = self.lancer("on", "--instance", "erp", "--xdebug")
        self.assertEqual(code, 0)
        self.assertEqual(self.redemarrages, ["erp"])

    def test_containers_and_productions_are_refused(self):
        conteneur = {
            "mode": "dev",
            "runtime": "container",
            "engine": "podman",
            "containers": ["x-db", "x-web", "x-cron"],
            "state_dir": str(self.etat),
        }
        prod = dict(self.entree, mode="prod", user="dolibarr_erp")
        for entree, extra in ((conteneur, ()), (prod, ("--confirm", "erp"))):
            code, _s = self.lancer(
                "on", "--instance", "erp", "--xdebug", *extra, entree=entree
            )
            self.assertEqual(code, 2)
        self.assertEqual(self.sys.appels, [])

    def test_off_removes_it_and_keeps_the_ide_config(self):
        self.lancer("on", "--instance", "erp", "--xdebug")
        code, _s = self.lancer("off", "--instance", "erp")
        self.assertEqual(code, 0)
        self.assertFalse(self.ini.exists())
        self.assertEqual(self.redemarrages, ["erp", "erp"])
        self.assertTrue(self.launch.exists())

    def test_xdebug_joins_a_profile_already_on(self):
        self.lancer("on", "--instance", "erp")
        code, _s = self.lancer("on", "--instance", "erp", "--xdebug")
        self.assertEqual(code, 0)
        self.assertTrue(self.ini.exists())
        etat = json.loads((self.etat / "debug.json").read_text())
        self.assertTrue(etat["xdebug"])
        self.assertEqual(etat["constants"], AVANT)

    def test_the_vscode_config_is_merged_and_never_doubled(self):
        self.launch.parent.mkdir(parents=True)
        self.launch.write_text(
            json.dumps(
                {"version": "0.2.0", "configurations": [{"name": "Autre"}]}
            )
        )
        self.lancer("on", "--instance", "erp", "--xdebug")
        self.lancer("off", "--instance", "erp")
        self.lancer("on", "--instance", "erp", "--xdebug")
        noms = [
            c["name"]
            for c in json.loads(self.launch.read_text())["configurations"]
        ]
        self.assertEqual(noms, ["Autre", "Dolibarr erp (Xdebug)"])

    def test_a_launch_json_with_comments_is_left_alone(self):
        self.launch.parent.mkdir(parents=True)
        self.launch.write_text(
            '{\n  // mes réglages\n  "configurations": []\n}\n'
        )
        avant = self.launch.read_text()
        code, sortie = self.lancer("on", "--instance", "erp", "--xdebug")
        self.assertEqual(code, 0)
        self.assertEqual(self.launch.read_text(), avant)
        self.assertIn('"port": 9003', sortie)


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
