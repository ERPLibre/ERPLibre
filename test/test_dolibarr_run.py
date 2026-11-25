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
- l'état se lit dans les pid de PHP-FPM et de nginx ; un état inconnu
  refuse le démarrage ;
- la page de connexion confirme la version servie (« Login @ 24.0.1 »).
Le port libre et le schéma d'état à quatre valeurs (lancée, arrêtée, à
moitié, inconnue) se vérifient dans test_erp_common_process.
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
        self.envs = []

    # interface attendue par run.py
    def spawn(self, argv, log, env=None):
        self.lances.append(argv)
        self.envs.append(env)
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

    def test_fpm_reads_the_instance_ini_dir_only_when_it_has_one(self):
        # Xdebug de debug.py : un .ini propre à l'instance, ajouté au
        # dossier que PHP lit déjà (« : » en tête), rien dans /etc.
        self.lancer("start", "--instance", "erp")
        self.assertIsNone(self.sys.envs[0])
        self.lancer("stop", "--instance", "erp")
        php_d = self.run_dir / "php.d"
        php_d.mkdir()
        (php_d / "90-erplibre-xdebug.ini").write_text("xdebug.mode=debug\n")
        self.lancer("start", "--instance", "erp")
        self.assertEqual(self.sys.envs[-1], {"PHP_INI_SCAN_DIR": f":{php_d}"})

    def test_start_refuses_an_unknown_state(self):
        (self.run_dir / "nginx.pid").write_bytes(b"\xff\xfe")
        code, _sortie = self.lancer("start", "--instance", "erp")
        self.assertEqual(code, 1)
        self.assertEqual(self.sys.lances, [])

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


NOMS = (
    "erplibre-dolibarr-ctr-db",
    "erplibre-dolibarr-ctr-web",
    "erplibre-dolibarr-ctr-cron",
)


class SystemeConteneurs(Systeme):
    """Le même système, plus un moteur de conteneurs en mémoire."""

    def __init__(self):
        super().__init__()
        self.conteneurs = {nom: "exited" for nom in NOMS}
        self.page = "<title>Login @ 24.0.0</title>"

    def engine(self, moteur):
        return {
            "moteur": moteur,
            "sans_sudo": True,
            "avec_sudo": False,
            "rootless": True,
            "docker_host": None,
        }

    def call(self, argv):
        if argv[0] not in ("podman", "docker"):
            return super().call(argv)
        self.lances.append(argv)
        verbe = argv[1:]
        if verbe[:2] == ["container", "inspect"]:
            etat = self.conteneurs.get(verbe[-1])
            if etat is None:
                return 125, "no such container"
            return 0, "true" if etat == "running" else "false"
        if verbe[0] in ("start", "stop"):
            for nom in verbe[1:]:
                self.conteneurs[nom] = (
                    "running" if verbe[0] == "start" else "exited"
                )
            return 0, "\n".join(verbe[1:])
        if verbe[0] == "logs":
            return 0, f"journal de {verbe[-1]}"
        return 0, ""


class BancConteneur(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.racine = Path(tmp.name)
        registre = self.racine / "private" / "dolibarr" / "instances.json"
        registre.parent.mkdir(parents=True)
        registre.write_text(
            json.dumps(
                {
                    "instances": {
                        "ctr": {
                            "mode": "dev",
                            "runtime": "container",
                            "engine": "podman",
                            "containers": list(NOMS),
                            "port": 8081,
                            "url": "http://127.0.0.1:8081",
                            "version": "24.0.0",
                        }
                    }
                }
            )
        )
        self.sys = SystemeConteneurs()

    def lancer(self, *argv):
        sortie = io.StringIO()
        with contextlib.redirect_stdout(sortie):
            code = run_mod.main(
                list(argv), root=str(self.racine), system=self.sys
            )
        return code, sortie.getvalue()

    def moteur(self):
        return [a for a in self.sys.lances if a[0] == "podman"]


class TestConteneurs(BancConteneur):
    def test_start_starts_the_database_then_the_site_then_cron(self):
        code, sortie = self.lancer("start", "--instance", "ctr")
        self.assertEqual(code, 0, sortie)
        self.assertIn(["podman", "start", *NOMS], self.moteur())
        self.assertIn("24.0.0", sortie)
        self.assertIn("http://127.0.0.1:8081", sortie)

    def test_stop_stops_cron_then_the_site_then_the_database(self):
        self.sys.conteneurs = {nom: "running" for nom in NOMS}
        code, _sortie = self.lancer("stop", "--instance", "ctr")
        self.assertEqual(code, 0)
        self.assertIn(["podman", "stop", *reversed(NOMS)], self.moteur())
        self.assertEqual(set(self.sys.conteneurs.values()), {"exited"})

    def test_status_reads_the_three_containers(self):
        self.sys.conteneurs = {nom: "running" for nom in NOMS}
        _code, sortie = self.lancer("status")
        self.assertIn(
            f"ctr: {run_mod.t(run_mod.STATE_LABELS['running'])}", sortie
        )
        self.sys.conteneurs[NOMS[2]] = "exited"
        _code, sortie = self.lancer("status", "--instance", "ctr")
        self.assertIn(
            run_mod.t(run_mod.CONTAINER_LABELS["half running"]), sortie
        )

    def test_a_missing_container_is_said_and_not_started(self):
        del self.sys.conteneurs[NOMS[1]]
        code, sortie = self.lancer("start", "--instance", "ctr")
        self.assertEqual(code, 1)
        self.assertIn(run_mod.t(run_mod.CONTAINER_LABELS["missing"]), sortie)
        self.assertFalse([a for a in self.moteur() if a[1] == "start"])

    def test_a_running_instance_is_left_alone(self):
        self.sys.conteneurs = {nom: "running" for nom in NOMS}
        code, _sortie = self.lancer("start", "--instance", "ctr")
        self.assertEqual(code, 0)
        self.assertFalse([a for a in self.moteur() if a[1] == "start"])

    def test_a_taken_port_refuses_to_start(self):
        self.sys.ports_pris.add(8081)
        code, _sortie = self.lancer("start", "--instance", "ctr")
        self.assertEqual(code, 1)
        self.assertFalse([a for a in self.moteur() if a[1] == "start"])

    def test_logs_show_the_site_and_cron_containers(self):
        _code, sortie = self.lancer(
            "logs", "--instance", "ctr", "--lines", "5"
        )
        for nom in NOMS[1:]:
            with self.subTest(nom=nom):
                self.assertIn(
                    ["podman", "logs", "--tail", "5", nom], self.moteur()
                )
                self.assertIn(f"journal de {nom}", sortie)


if __name__ == "__main__":
    unittest.main()
