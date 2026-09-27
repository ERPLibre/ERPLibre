#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'API REST d'une instance : module, utilisateur technique, clé, /status.

Un système simulé joue PHP (il reçoit la clé sur stdin) et HTTP. Ce qui se
garde :
- enable allume le module API, crée l'utilisateur technique en lecture
  seule et lui pose une clé que seul stdin transporte ;
- la clé est gardée dans private/dolibarr/api/<instance>.key, 0600, sous un
  dossier 0700, et n'est remplacée que sur --rotate (ou si elle manque) ;
- /status, appelé avec DOLAPIKEY, prouve que la clé ouvre l'API ; un refus
  se dit ;
- une production exige son nom retapé pour enable et disable.
"""

import contextlib
import io
import json
import stat
import sys
import tempfile
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

from script.dolibarr import api  # noqa: E402

STATUT = json.dumps({"success": {"code": 200, "dolibarr_version": "24.0.1"}})


class Systeme:
    def __init__(self):
        self.php = []  # (argv, stdin)
        self.http_appels = []
        self.php_sortie = (0, "bruit\nERPLIBRE_API_OK 7 42\n")
        self.http_reponse = (200, STATUT)

    def run(self, argv, env=None, stdin_path=None):
        recu = Path(stdin_path).read_text() if stdin_path else ""
        self.php.append((list(argv), recu))
        return self.php_sortie

    def http(self, url, host, headers):
        self.http_appels.append((url, host, dict(headers)))
        return self.http_reponse

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
        self.entree = {
            "mode": "dev",
            "runtime": "native",
            "code_root": str(self.racine / "dolibarr"),
            "data_root": str(self.racine / "etat" / "documents"),
            "state_dir": str(self.racine / "etat"),
            "url": "http://127.0.0.1:8081",
        }
        self.cle = self.racine / "private" / "dolibarr" / "api" / "erp.key"
        self.sys = Systeme()

    def lancer(self, *argv, entree=None):
        registre = self.racine / "private" / "dolibarr" / "instances.json"
        registre.parent.mkdir(parents=True, exist_ok=True)
        registre.write_text(
            json.dumps({"instances": {"erp": entree or self.entree}})
        )
        sortie = io.StringIO()
        with contextlib.redirect_stdout(sortie):
            code = api.main(list(argv), root=str(self.racine), system=self.sys)
        return code, sortie.getvalue()


class TestAllumer(Banc):
    def test_enable_sets_a_key_that_only_stdin_carries(self):
        code, sortie = self.lancer("enable", "--instance", "erp")
        self.assertEqual(code, 0, sortie)
        cle = self.cle.read_text().strip()
        self.assertRegex(cle, r"^[A-Za-z0-9]{32}$")
        argv, recu = self.sys.php[0]
        self.assertEqual(
            json.loads(recu), {"login": "erplibre_api", "key": cle}
        )
        self.assertNotIn(cle, " ".join(argv))
        texte = " ".join(argv)
        for attendu in ("modApi", "rights_def", "ERPLIBRE_API_OK"):
            self.assertIn(attendu, texte)
        self.assertEqual(stat.S_IMODE(self.cle.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.cle.parent.stat().st_mode), 0o700)
        url, _hote, entetes = self.sys.http_appels[0]
        self.assertEqual(url, "http://127.0.0.1:8081/api/index.php/status")
        self.assertEqual(entetes["DOLAPIKEY"], cle)
        self.assertIn("24.0.1", sortie)
        self.assertIn("/api/index.php/explorer/", sortie)
        self.assertNotIn(cle, sortie)

    def test_enable_again_keeps_the_key(self):
        self.lancer("enable", "--instance", "erp")
        avant = self.cle.read_text()
        code, _s = self.lancer("enable", "--instance", "erp")
        self.assertEqual(code, 0)
        self.assertEqual(self.cle.read_text(), avant)
        self.assertEqual(json.loads(self.sys.php[-1][1])["key"], "")

    def test_rotate_or_a_lost_key_gives_a_new_one(self):
        self.lancer("enable", "--instance", "erp")
        avant = self.cle.read_text()
        self.lancer("enable", "--instance", "erp", "--rotate")
        apres = self.cle.read_text()
        self.assertNotEqual(apres, avant)
        self.assertEqual(json.loads(self.sys.php[-1][1])["key"], apres.strip())
        self.cle.unlink()
        self.lancer("enable", "--instance", "erp")
        self.assertTrue(self.cle.exists())

    def test_a_php_refusal_keeps_no_key(self):
        self.sys.php_sortie = (
            1,
            'ERPLIBRE_API_ERRORS ["no active administrator"]\n',
        )
        code, sortie = self.lancer("enable", "--instance", "erp")
        self.assertEqual(code, 1)
        self.assertIn("no active administrator", sortie)
        self.assertFalse(self.cle.exists())
        self.assertEqual(self.sys.http_appels, [])

    def test_keys_are_letters_and_digits(self):
        for _ in range(300):
            self.assertRegex(api.new_key(), r"^[A-Za-z0-9]{32}$")

    def test_modes_are_tightened_on_what_already_exists(self):
        # os.open ne pose le mode qu'à la création ; un fichier ou un
        # dossier déjà là garderait le sien.
        self.cle.parent.mkdir(parents=True)
        self.cle.parent.chmod(0o755)
        self.cle.write_text("ancienne\n")
        self.cle.chmod(0o644)
        self.lancer("enable", "--instance", "erp", "--rotate")
        self.assertEqual(stat.S_IMODE(self.cle.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.cle.parent.stat().st_mode), 0o700)

    def test_php_failing_after_its_answer_keeps_no_key(self):
        self.sys.php_sortie = (255, "ERPLIBRE_API_OK 7 42\nPHP Fatal error\n")
        code, _s = self.lancer("enable", "--instance", "erp")
        self.assertEqual(code, 1)
        self.assertFalse(self.cle.exists())

    def test_the_login_is_checked(self):
        code, _s = self.lancer(
            "enable", "--instance", "erp", "--login", "a b'"
        )
        self.assertEqual(code, 2)
        self.assertEqual(self.sys.php, [])

    def test_the_container_runs_php_as_www_data(self):
        entree = {
            "mode": "dev",
            "runtime": "container",
            "engine": "podman",
            "containers": ["x-db", "x-web", "x-cron"],
            "state_dir": str(self.racine / "etat"),
            "url": "http://127.0.0.1:8090",
        }
        code, sortie = self.lancer(
            "enable", "--instance", "erp", entree=entree
        )
        self.assertEqual(code, 0, sortie)
        argv = self.sys.php[0][0]
        self.assertEqual(
            argv[:6], ["podman", "exec", "-i", "-u", "www-data", "x-web"]
        )
        self.assertTrue(
            self.sys.http_appels[0][0].startswith("http://127.0.0.1:8090/")
        )


class TestStatut(Banc):
    def test_status_names_what_refuses(self):
        self.lancer("enable", "--instance", "erp")
        for reponse, code_attendu in (
            ((200, STATUT), 0),
            ((401, '{"error":{"code":401}}'), 1),
            ((404, "Not Found"), 1),
            # Module éteint : Dolibarr répond 200, en texte, pas en JSON.
            ((200, "Module <b>Api</b> must be enabled.<br><br>"), 1),
            ((0, "ERROR timed out"), 1),
        ):
            self.sys.http_reponse = reponse
            code, _s = self.lancer("status", "--instance", "erp")
            self.assertEqual(code, code_attendu, reponse)

    def test_status_without_key_says_to_enable(self):
        code, _s = self.lancer("status", "--instance", "erp")
        self.assertEqual(code, 1)
        self.assertEqual(self.sys.http_appels, [])

    def test_a_production_is_reached_through_its_domain(self):
        prod = dict(
            self.entree, mode="prod", domain="erp.example.org", tls="local"
        )
        self.lancer(
            "enable", "--instance", "erp", "--confirm", "erp", entree=prod
        )
        url, hote, _e = self.sys.http_appels[0]
        self.assertEqual(url, "https://127.0.0.1/api/index.php/status")
        self.assertEqual(hote, "erp.example.org")


class TestProduction(Banc):
    def test_enable_and_disable_need_the_name(self):
        prod = dict(
            self.entree, mode="prod", domain="erp.example.org", tls="local"
        )
        for action in ("enable", "disable"):
            code, _s = self.lancer(action, "--instance", "erp", entree=prod)
            self.assertEqual(code, 2, action)
        self.assertEqual(self.sys.php, [])


class TestEteindre(Banc):
    def test_disable_turns_the_module_off_and_keeps_the_key(self):
        self.lancer("enable", "--instance", "erp")
        self.sys.php_sortie = (0, "ERPLIBRE_API_OK\n")
        code, _s = self.lancer("disable", "--instance", "erp")
        self.assertEqual(code, 0)
        self.assertIn(
            'unActivateModule("modApi")', " ".join(self.sys.php[-1][0])
        )
        self.assertTrue(self.cle.exists())


if __name__ == "__main__":
    unittest.main()
