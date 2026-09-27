#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Lancer, arrêter, surveiller une instance Dolibarr de développement.

Aucun démon n'est lancé : un Système factice enregistre ce qui aurait été
démarré, envoyé, interrogé. Ce qui se garde :
- les binaires se trouvent là où chaque famille les pose (php-fpmX.Y sous
  Debian, php-fpm ailleurs ; nginx dans /usr/sbin ou /usr/bin) ;
- un port déjà pris refuse le démarrage au lieu de laisser nginx échouer
  plus loin ;
- l'état dit la vérité en trois valeurs : lancée, arrêtée, ou à moitié
  (un démon mort, l'autre vivant) — jamais un « arrêtée » pour « illisible » ;
- la page de connexion confirme la version servie (« Login @ 24.0.1 »).
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

from script.dolibarr import run as run_mod  # noqa: E402


class TestBinaires(unittest.TestCase):
    def test_debian_fpm_carries_the_php_version(self):
        present = {"/usr/sbin/php-fpm8.3"}
        self.assertEqual(
            run_mod.fpm_binary("apt-get", "8.3", exists=present.__contains__),
            "/usr/sbin/php-fpm8.3",
        )

    def test_other_families_use_their_fixed_path(self):
        cas = (
            ("dnf", "/usr/sbin/php-fpm"),
            ("zypper", "/usr/sbin/php-fpm"),
            ("pacman", "/usr/bin/php-fpm"),
        )
        for famille, chemin in cas:
            with self.subTest(famille=famille):
                self.assertEqual(
                    run_mod.fpm_binary(
                        famille, "8.5", exists={chemin}.__contains__
                    ),
                    chemin,
                )

    def test_a_missing_fpm_is_none(self):
        self.assertIsNone(
            run_mod.fpm_binary("apt-get", "8.3", exists=lambda p: False)
        )

    def test_nginx_is_found_in_sbin_or_bin(self):
        self.assertEqual(
            run_mod.nginx_binary(exists={"/usr/bin/nginx"}.__contains__),
            "/usr/bin/nginx",
        )
        self.assertEqual(
            run_mod.nginx_binary(exists={"/usr/sbin/nginx"}.__contains__),
            "/usr/sbin/nginx",
        )
        self.assertIsNone(run_mod.nginx_binary(exists=lambda p: False))


class TestTitre(unittest.TestCase):
    def test_the_login_title_gives_the_served_version(self):
        for html in (
            "<html><title>Login @ 24.0.1</title>",
            "<title>Identifiant @ 24.0.1</title>",
        ):
            with self.subTest(html=html):
                self.assertEqual(run_mod.served_version(html), "24.0.1")

    def test_no_title_no_version(self):
        self.assertIsNone(run_mod.served_version("<title>Dolibarr</title>"))
        self.assertIsNone(run_mod.served_version(""))


class Systeme:
    """Processus, ports et HTTP simulés."""

    def __init__(self):
        self.vivants = set()
        self.lances = []  # argv
        self.envoyes = []  # (pid, signal)
        self.ports_pris = set()
        self.page = "<title>Login @ 24.0.1</title>"
        self.prochain_pid = 4000
        self.run_dir = None

    # interface attendue par run.py
    def spawn(self, argv, log):
        self.lances.append(argv)
        self.prochain_pid += 1
        self.vivants.add(self.prochain_pid)
        if self.run_dir:
            Path(self.run_dir, "php-fpm.pid").write_text(
                f"{self.prochain_pid}\n"
            )
        return self.prochain_pid

    def call(self, argv):
        self.lances.append(argv)
        if "-s" not in argv and self.run_dir:
            self.prochain_pid += 1
            self.vivants.add(self.prochain_pid)
            Path(self.run_dir, "nginx.pid").write_text(
                f"{self.prochain_pid}\n"
            )
        if "-s" in argv and self.run_dir:
            pid = int(Path(self.run_dir, "nginx.pid").read_text())
            self.vivants.discard(pid)
        return 0, ""

    def alive(self, pid):
        return pid in self.vivants

    def kill(self, pid, sig):
        self.envoyes.append((pid, sig))
        self.vivants.discard(pid)

    def port_free(self, port):
        return port not in self.ports_pris

    def http_get(self, url):
        return self.page


class Banc(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.racine = Path(tmp.name)
        self.state = self.racine / "state" / "erp"
        self.run_dir = self.state / "run"
        self.run_dir.mkdir(parents=True)
        (self.run_dir / "php-fpm.conf").write_text("[global]\n")
        (self.run_dir / "nginx.conf").write_text("events {}\n")
        registre = self.racine / "private" / "dolibarr" / "instances.json"
        registre.parent.mkdir(parents=True)
        registre.write_text(
            json.dumps(
                {
                    "instances": {
                        "erp": {
                            "mode": "dev",
                            "runtime": "native",
                            "state_dir": str(self.state),
                            "port": 8080,
                            "url": "http://127.0.0.1:8080",
                            "version": "24.0.1",
                            "data_root": str(self.state / "documents"),
                        }
                    }
                }
            )
        )
        self.sys = Systeme()
        self.sys.run_dir = str(self.run_dir)

    def lancer(self, *argv):
        sortie = io.StringIO()
        with contextlib.redirect_stdout(sortie):
            code = run_mod.main(
                list(argv),
                root=str(self.racine),
                system=self.sys,
                binaries=("/usr/sbin/php-fpm8.3", "/usr/sbin/nginx"),
            )
        return code, sortie.getvalue()


class TestStart(Banc):
    def test_start_launches_fpm_then_nginx_on_the_instance_configs(self):
        code, sortie = self.lancer("start", "--instance", "erp")
        self.assertEqual(code, 0, sortie)
        self.assertEqual(
            self.sys.lances[0],
            ["/usr/sbin/php-fpm8.3", "-y", f"{self.run_dir}/php-fpm.conf"],
        )
        self.assertEqual(
            self.sys.lances[1],
            [
                "/usr/sbin/nginx",
                "-p",
                str(self.run_dir),
                "-c",
                f"{self.run_dir}/nginx.conf",
            ],
        )
        self.assertIn("http://127.0.0.1:8080", sortie)
        self.assertIn("24.0.1", sortie)

    def test_a_taken_port_refuses_to_start(self):
        self.sys.ports_pris.add(8080)
        code, sortie = self.lancer("start", "--instance", "erp")
        self.assertEqual(code, 1)
        self.assertEqual(self.sys.lances, [])
        self.assertIn("8080", sortie)

    def test_an_instance_already_running_is_left_alone(self):
        self.lancer("start", "--instance", "erp")
        lances = len(self.sys.lances)
        code, _sortie = self.lancer("start", "--instance", "erp")
        self.assertEqual(code, 0)
        self.assertEqual(len(self.sys.lances), lances)

    def test_an_unknown_instance_is_refused(self):
        code, sortie = self.lancer("start", "--instance", "autre")
        self.assertEqual(code, 2)
        self.assertIn("autre", sortie)

    def test_a_production_instance_is_not_run_here(self):
        registre = self.racine / "private" / "dolibarr" / "instances.json"
        data = json.loads(registre.read_text())
        data["instances"]["erp"]["mode"] = "prod"
        registre.write_text(json.dumps(data))
        code, _sortie = self.lancer("start", "--instance", "erp")
        self.assertEqual(code, 2)
        self.assertEqual(self.sys.lances, [])


class TestStopStatus(Banc):
    def test_stop_quits_nginx_and_ends_fpm(self):
        self.lancer("start", "--instance", "erp")
        fpm_pid = int((self.run_dir / "php-fpm.pid").read_text())
        code, _sortie = self.lancer("stop", "--instance", "erp")
        self.assertEqual(code, 0)
        self.assertIn(
            [
                "/usr/sbin/nginx",
                "-p",
                str(self.run_dir),
                "-c",
                f"{self.run_dir}/nginx.conf",
                "-s",
                "quit",
            ],
            self.sys.lances,
        )
        self.assertIn((fpm_pid, run_mod.signal.SIGQUIT), self.sys.envoyes)
        self.assertFalse(self.sys.vivants)

    def test_status_says_running_with_the_served_version(self):
        self.lancer("start", "--instance", "erp")
        code, sortie = self.lancer("status", "--instance", "erp")
        self.assertEqual(code, 0)
        self.assertIn(run_mod.t(run_mod.STATE_LABELS["running"]), sortie)
        self.assertIn("24.0.1", sortie)

    def test_status_says_stopped_when_no_pid(self):
        code, sortie = self.lancer("status", "--instance", "erp")
        self.assertEqual(code, 0)
        self.assertIn(run_mod.t(run_mod.STATE_LABELS["stopped"]), sortie)

    def test_half_running_is_not_reported_as_running(self):
        self.lancer("start", "--instance", "erp")
        fpm_pid = int((self.run_dir / "php-fpm.pid").read_text())
        self.sys.vivants.discard(fpm_pid)
        _code, sortie = self.lancer("status", "--instance", "erp")
        self.assertIn(run_mod.t(run_mod.STATE_LABELS["half running"]), sortie)

    def test_stop_on_a_stopped_instance_is_quiet(self):
        code, sortie = self.lancer("stop", "--instance", "erp")
        self.assertEqual(code, 0)
        self.assertEqual(self.sys.envoyes, [])
        # Rien ne tournait : dire « arrêtée » serait faux.
        self.assertNotIn(run_mod.t("Stopped: %s") % "erp", sortie)


class TestLogs(Banc):
    def test_logs_shows_the_tail_of_each_log(self):
        (self.run_dir / "nginx-error.log").write_text(
            "\n".join(f"ligne {i}" for i in range(50)) + "\n"
        )
        docs = self.state / "documents"
        docs.mkdir()
        (docs / "dolibarr.log").write_text("dernier message\n")
        code, sortie = self.lancer("logs", "--instance", "erp", "--lines", "3")
        self.assertEqual(code, 0)
        self.assertIn("ligne 49", sortie)
        self.assertNotIn("ligne 46", sortie)
        self.assertIn("dernier message", sortie)


if __name__ == "__main__":
    unittest.main()
