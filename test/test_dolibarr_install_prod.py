#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'installateur natif de Dolibarr en PRODUCTION, sur un système simulé.

La production pose le code dans /opt (root, lecture seule), les données
dans /var/lib et les secrets dans /etc, fait tourner PHP-FPM sous un compte
système propre à l'instance, sert par nginx, et planifie les tâches de
Dolibarr par une minuterie systemd. Rien n'est installé ici : les fichiers
écrits sous sudo vont dans un dictionnaire, relu par « sudo cat ».

Ce qui se garde :
- l'installation et le cron tournent sous le compte de l'instance ;
- conf.php finit en lecture seule pour ce compte, prod à 1 ;
- aucun secret sur argv : mots de passe et clé cron par stdin ou fichier ;
- un domaine valide est exigé, SELinux en mode enforcing est refusé tant
  qu'il n'est pas éprouvé ;
- relancer ne recrée ni le compte ni le code.
"""

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

from script.dolibarr import install_native, native_prod  # noqa: E402

COMMIT = "0123456789abcdef0123456789abcdef01234567"
CODE = "/opt/erplibre-dolibarr/erp"
HTDOCS = f"{CODE}/htdocs"
STATE = "/var/lib/erplibre-dolibarr/erp"
ETC = "/etc/erplibre-dolibarr/erp"
USER = "dolibarr_erp"


class FauxRunner:
    def __init__(self, sys_):
        self.sys = sys_
        self.dry_run = False
        self.lances = []  # (argv, stdin)
        self.modes = {}  # chemin -> (mode, owner, group)
        self.sortie = []

    def out(self, texte):
        self.sortie.append(texte)

    def run(self, argv, input=None, cwd=None, env=None):
        self.lances.append((list(argv), input))
        return self.sys.repondre(list(argv), input) or (0, "")

    def probe(self, argv, cwd=None):
        return self.sys.repondre(list(argv), None)

    def write(
        self, path, text, mode=0o600, sudo=False, owner=None, group=None
    ):
        if sudo:
            # « install » n'écrit pas dans un dossier qui n'existe pas.
            parent = os.path.dirname(path)
            if path.startswith(ETC) and parent not in self.sys.dossiers:
                raise install_native.StepError(f"Cannot write {path}")
            self.sys.fichiers[path] = text
            self.modes[path] = (mode, owner, group)
            return
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(text)
        os.chmod(path, mode)


class Systeme:
    def __init__(self):
        self.fichiers = {
            "/etc/nginx/nginx.conf": "http {\n    include mime.types;\n}\n"
        }
        self.compte = False
        self.version_installee = None
        self.selinux = None
        self.absents = set()
        self.dossiers = set()
        self.base_refuse = False
        self.rhel = ""
        self.echec = {}
        self.cron = "ERPLIBRE_CRON_OK"

    def repondre(self, argv, stdin):
        joint = " ".join(argv)
        if argv[0] == "dpkg-query":
            if argv[-1] in self.absents:
                return 1, "no packages found"
            return 0, "install ok installed"
        if argv[:2] == ["rpm", "-q"]:
            return (1, "") if argv[-1] in self.absents else (0, argv[-1])
        if argv[:3] in (["sudo", "install", "-d"], ["sudo", "mkdir", "-p"]):
            self.dossiers.add(argv[-1])
            return 0, ""
        if argv == ["sudo", "mariadb"] and self.base_refuse:
            return 1, "ERROR 2002: Can't connect"
        if argv == ["rpm", "-E", "%{?rhel}"]:
            return 0, self.rhel + "\n"
        if argv == ["getenforce"]:
            return (0, self.selinux) if self.selinux else (127, "")
        if argv[:2] == ["systemctl", "is-active"]:
            return 3, ""
        if argv[:2] == ["id", "-u"]:
            return (0, "990") if self.compte else (1, "no such user")
        if argv[:2] == ["sudo", "useradd"]:
            self.compte = True
            return 0, ""
        if argv[:2] == ["sudo", "cat"]:
            f = self.fichiers.get(argv[2])
            return (0, f) if f is not None else (1, "No such file")
        if argv[:3] == ["sudo", "test", "-e"] or argv[:3] == [
            "sudo",
            "test",
            "-s",
        ]:
            return (0, "") if argv[3] in self.fichiers else (1, "")
        if argv[:2] == ["bash", "-c"] and "archive" in argv[2]:
            self.fichiers[f"{HTDOCS}/version.inc.php"] = "<?php"
            return 0, ""
        if "git" in argv and "cat-file" in argv:
            return 0, ""
        if argv[0] == "php" and "PHP_MAJOR" in joint:
            return 0, "8.2"
        if argv == ["php", "-m"]:
            return 0, "\n".join(
                install_native.REQUIRED_EXTENSIONS + ("mysqli",)
            )
        if argv[:4] == ["sudo", "-u", USER, "php"]:
            script = argv[4]
            if script in self.echec:
                return self.echec[script]
            if script == "step1.php":
                self.fichiers[f"{HTDOCS}/conf/conf.php"] = (
                    "<?php\n$dolibarr_main_db_type='mysqli';\n"
                    "$dolibarr_main_prod='0';\n$dolibarr_main_force_https='0';\n"
                )
            if script == "step5.php":
                self.version_installee = "24.0.1"
                self.fichiers[f"{STATE}/documents/install.lock"] = ""
            if script == "-r" and "activateModule" in argv[5]:
                return 0, self.cron
            if script == "-r":
                return 0, "ERPLIBRE_CHECK 24.0.1 24.0.1"
            return 0, f"{script} ok"
        if "MAIN_VERSION_LAST_INSTALL" in joint:
            if self.version_installee:
                return 0, self.version_installee
            return 1, "ERROR 1146"
        return None


class Banc(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.racine = Path(tmp.name, "erplibre")
        (self.racine / "conf").mkdir(parents=True)
        (self.racine / "manifest").mkdir()
        (self.racine / "conf" / "supported_version_dolibarr.json").write_text(
            json.dumps(
                {
                    "version": "24.0.1",
                    "branch": "24.0",
                    "docker_image": "docker.io/dolibarr/dolibarr:24.0.0",
                    "mariadb_image": "docker.io/library/mariadb:11.4",
                    "tools_image": "docker.io/library/composer:2",
                    "php_min": "7.2",
                    "php_max": "8.5",
                }
            )
        )
        (self.racine / "manifest" / "git_manifest_dolibarr.xml").write_text(
            '<manifest><project name="dolibarr.git" path="dolibarr/dolibarr"'
            f' remote="Dolibarr" revision="{COMMIT}" upstream="24.0"'
            ' groups="dolibarr" /></manifest>'
        )
        htdocs = self.racine / "dolibarr" / "dolibarr" / "htdocs"
        htdocs.mkdir(parents=True)
        (htdocs / "version.inc.php").write_text("<?php\n")
        self.home = Path(tmp.name, "home")
        patches = [
            mock.patch.object(install_native, "ROOT", str(self.racine)),
            mock.patch.dict(
                os.environ,
                {"HOME": str(self.home), "XDG_DATA_HOME": str(self.home)},
            ),
            mock.patch.object(
                native_prod,
                "http_get",
                lambda url, host: "<title>Login @ 24.0.1</title>",
            ),
            mock.patch.object(
                native_prod, "issue_local_cert", self._certificat
            ),
            mock.patch.object(
                native_prod, "nologin", lambda: "/usr/sbin/nologin"
            ),
            mock.patch.object(native_prod.time, "sleep"),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        os.environ.pop(install_native.lib_dolibarr.ENV_ADMIN_PASSWORD, None)
        self.sys = Systeme()
        self.emis = []
        self.faits = {
            "system": "Linux",
            "family": "apt-get",
            "is_nixos": False,
            "has_systemd": True,
        }

    def _certificat(self, directory, names):
        self.emis.append((directory, names))
        Path(directory).mkdir(parents=True, exist_ok=True)
        Path(directory, "server.crt").write_text("CERT")
        Path(directory, "server.key").write_text("KEY")
        return (
            os.path.join(directory, "server.crt"),
            os.path.join(directory, "server.key"),
            "/srv/autorite/ca.crt",
        )

    def installer(self, *extra, domaine="erp.example.org", dry_run=False):
        runner = FauxRunner(self.sys)
        runner.dry_run = dry_run
        argv = [
            "--mode",
            "prod",
            "--db",
            "mariadb",
            "--instance",
            "erp",
            "--yes",
        ]
        if domaine:
            argv += ["--domain", domaine]
        with (
            contextlib.redirect_stdout(io.StringIO()),
            mock.patch(
                "builtins.input", side_effect=AssertionError("input() appelé")
            ),
        ):
            code = install_native.main(
                argv + list(extra), facts=self.faits, runner=runner
            )
        return code, runner

    def argvs(self, runner):
        return [a for a, _ in runner.lances]


class TestInstallationComplete(Banc):
    def test_a_full_production_install_succeeds(self):
        code, runner = self.installer()
        self.assertEqual(code, 0, "\n".join(runner.sortie))
        registre = json.loads(
            (self.racine / "private/dolibarr/instances.json").read_text()
        )
        entree = registre["instances"]["erp"]
        self.assertEqual(entree["mode"], "prod")
        self.assertEqual(entree["url"], "http://erp.example.org")
        self.assertEqual(entree["code_root"], CODE)

    def test_the_install_runs_as_the_instance_account(self):
        _code, runner = self.installer()
        steps = [a for a in self.argvs(runner) if "step1.php" in a]
        self.assertEqual(
            steps[0][:5], ["sudo", "-u", USER, "php", "step1.php"]
        )
        self.assertIn(
            "useradd", [a[1] for a in self.argvs(runner) if a[0] == "sudo"]
        )

    def test_conf_php_ends_production_and_read_only(self):
        _code, runner = self.installer()
        conf = f"{HTDOCS}/conf/conf.php"
        self.assertIn("$dolibarr_main_prod='1';", self.sys.fichiers[conf])
        self.assertEqual(runner.modes[conf], (0o440, "root", USER))
        self.assertIn(f"{HTDOCS}/install.lock", self.sys.fichiers)

    def test_the_pool_runs_as_the_instance_and_nginx_serves_the_domain(self):
        _code, runner = self.installer()
        pool = "/etc/php/8.2/fpm/pool.d/erplibre-dolibarr-erp.conf"
        self.assertIn(f"user = {USER}", self.sys.fichiers[pool])
        site = "/etc/nginx/sites-available/erplibre-dolibarr-erp"
        self.assertIn("server_name erp.example.org;", self.sys.fichiers[site])
        self.assertIn(
            [
                "sudo",
                "ln",
                "-sf",
                site,
                "/etc/nginx/sites-enabled/erplibre-dolibarr-erp",
            ],
            self.argvs(runner),
        )
        self.assertIn(["sudo", "nginx", "-t"], self.argvs(runner))

    def test_the_cron_timer_is_written_and_enabled(self):
        _code, runner = self.installer()
        self.assertIn(
            "/etc/systemd/system/erplibre-dolibarr-cron-erp.timer",
            self.sys.fichiers,
        )
        self.assertIn(
            [
                "sudo",
                "systemctl",
                "enable",
                "--now",
                "erplibre-dolibarr-cron-erp.timer",
            ],
            self.argvs(runner),
        )
        env = self.sys.fichiers[f"{ETC}/cron.env"]
        self.assertTrue(env.startswith("CRON_KEY="))
        self.assertEqual(runner.modes[f"{ETC}/cron.env"][0], 0o600)


class TestSecrets(Banc):
    def test_no_secret_ever_reaches_argv(self):
        code, runner = self.installer()
        self.assertEqual(code, 0, "\n".join(runner.sortie))
        secrets = install_native.parse_secrets(
            self.sys.fichiers[f"{ETC}/secrets.env"]
        )
        self.assertEqual(
            set(secrets), {"ADMIN_PASSWORD", "CRON_KEY", "DB_PASSWORD"}
        )
        for valeur in secrets.values():
            for argv in self.argvs(runner):
                self.assertFalse(any(valeur in a for a in argv), argv)
        self.assertEqual(runner.modes[f"{ETC}/secrets.env"][0], 0o600)

    def test_the_cron_key_goes_through_stdin(self):
        _code, runner = self.installer()
        cle = install_native.parse_secrets(
            self.sys.fichiers[f"{ETC}/secrets.env"]
        )["CRON_KEY"]
        stdins = [
            s for a, s in runner.lances if "activateModule" in " ".join(a)
        ]
        self.assertIn(cle, stdins[0])

    def test_a_failed_cron_activation_stops(self):
        self.sys.cron = "ERPLIBRE_CRON_FAIL ErrorModuleRequirePHPVersion"
        code, _runner = self.installer()
        self.assertEqual(code, 1)


class TestRefus(Banc):
    def test_a_domain_is_required(self):
        code, runner = self.installer(domaine=None)
        self.assertEqual(code, 2)
        self.assertFalse(runner.lances)

    def test_an_invalid_domain_is_refused_before_anything(self):
        code, runner = self.installer(domaine="erp.example.org;evil")
        self.assertEqual(code, 2)
        self.assertFalse(runner.lances)

    def test_selinux_enforcing_is_refused_until_proven(self):
        self.sys.selinux = "Enforcing"
        code, runner = self.installer()
        self.assertEqual(code, 1)
        self.assertFalse([a for a in self.argvs(runner) if "useradd" in a])

    def test_the_install_file_goes_even_when_a_step_fails(self):
        self.sys.echec["step2.php"] = (1, "SQL error")
        code, runner = self.installer()
        self.assertEqual(code, 1)
        self.assertIn(
            ["sudo", "rm", "-f", f"{HTDOCS}/install/install.forced.php"],
            self.argvs(runner),
        )


class TestRejouer(Banc):
    def test_an_existing_account_and_code_are_kept(self):
        self.sys.compte = True
        self.sys.fichiers[f"{HTDOCS}/version.inc.php"] = "<?php"
        _code, runner = self.installer()
        joints = [" ".join(a) for a in self.argvs(runner)]
        self.assertFalse([j for j in joints if "useradd" in j])
        self.assertFalse([j for j in joints if "archive" in j])

    def test_every_secret_is_written_before_the_database_is_touched(self):
        self.sys.base_refuse = True
        code, runner = self.installer("--tls", "local")
        self.assertEqual(code, 1)
        gardes = install_native.parse_secrets(
            self.sys.fichiers[f"{ETC}/secrets.env"]
        )
        self.assertEqual(
            set(gardes), {"ADMIN_PASSWORD", "CRON_KEY", "DB_PASSWORD"}
        )
        self.assertEqual(runner.modes[f"{ETC}/secrets.env"][0], 0o600)

    def test_a_rerun_after_a_late_failure_keeps_every_secret(self):
        # conf.php porte déjà le mot de passe de la base quand une étape
        # tardive échoue ; relancer ne doit pas réaligner le compte sur un
        # nouveau.
        with mock.patch.object(native_prod, "http_get", lambda u, h: "502"):
            code, premier = self.installer("--tls", "local")
        self.assertEqual(code, 1)
        gardes = install_native.parse_secrets(
            self.sys.fichiers[f"{ETC}/secrets.env"]
        )
        self.assertEqual(
            set(gardes), {"ADMIN_PASSWORD", "CRON_KEY", "DB_PASSWORD"}
        )
        code, second = self.installer("--tls", "local")
        self.assertEqual(code, 0, "\n".join(second.sortie))

        def sql(runner):
            return [s for a, s in runner.lances if a == ["sudo", "mariadb"]]

        self.assertEqual(sql(premier), sql(second))


class TestTls(Banc):
    def test_local_tls_serves_443_with_a_copied_certificate(self):
        code, runner = self.installer("--tls", "local")
        self.assertEqual(code, 0, "\n".join(runner.sortie))
        site = self.sys.fichiers[
            "/etc/nginx/sites-available/erplibre-dolibarr-erp"
        ]
        self.assertIn("listen 443 ssl;", site)
        self.assertIn(f"ssl_certificate {ETC}/tls/server.crt;", site)
        self.assertEqual(runner.modes[f"{ETC}/tls/server.key"][0], 0o600)
        conf = self.sys.fichiers[f"{HTDOCS}/conf/conf.php"]
        self.assertIn("$dolibarr_main_force_https='1';", conf)

    def test_local_tls_names_the_authority_to_import(self):
        # La même que celle du mandataire inverse : importée une fois.
        code, runner = self.installer("--tls", "local")
        self.assertEqual(code, 0)
        self.assertEqual(self.emis[0][1], ["erp.example.org"])
        self.assertIn(
            f"{native_prod.t('Authority to import in the browser:')}"
            " /srv/autorite/ca.crt",
            "\n".join(runner.sortie),
        )

    def test_a_dry_run_issues_no_certificate(self):
        code, runner = self.installer("--tls", "local", dry_run=True)
        self.assertEqual(code, 0, "\n".join(runner.sortie))
        self.assertEqual(self.emis, [])

    def test_certbot_rewrites_the_site_with_a_redirect(self):
        code, runner = self.installer(
            "--tls", "certbot", "--email", "ops@example.org"
        )
        self.assertEqual(code, 0, "\n".join(runner.sortie))
        self.assertIn(
            [
                "sudo",
                "certbot",
                "--nginx",
                "-d",
                "erp.example.org",
                "--non-interactive",
                "--agree-tos",
                "--redirect",
                "-m",
                "ops@example.org",
            ],
            self.argvs(runner),
        )


class TestCertbotPackages(Banc):
    CERTBOT = ("--tls", "certbot", "--email", "ops@example.org")

    def lancer(self, *extra):
        code, runner = self.installer(*extra)
        self.assertEqual(code, 0, "\n".join(runner.sortie))
        argvs = self.argvs(runner)
        certbot = [
            i for i, a in enumerate(argvs) if a[:2] == ["sudo", "certbot"]
        ]
        return argvs, certbot

    def test_certbot_is_installed_before_it_runs(self):
        self.sys.absents = {"certbot", "python3-certbot-nginx"}
        argvs, certbot = self.lancer(*self.CERTBOT)
        installe = [
            "sudo",
            "apt-get",
            "install",
            "-y",
            "certbot",
            "python3-certbot-nginx",
        ]
        self.assertIn(installe, argvs)
        self.assertLess(argvs.index(installe), certbot[0])

    def sans_certbot(self, tls):
        self.sys.absents = {"certbot", "python3-certbot-nginx"}
        argvs, _certbot = self.lancer("--tls", tls)
        self.assertFalse([a for a in argvs if "certbot" in a])

    def test_plain_http_installs_no_certbot(self):
        self.sans_certbot("none")

    def test_local_tls_installs_no_certbot(self):
        self.sans_certbot("local")

    def test_enterprise_linux_enables_epel_first(self):
        # EL 9/10 n'ont certbot que dans EPEL ; Fedora l'a dans ses dépôts.
        self.faits["family"] = "dnf"
        self.sys.absents = {"epel-release", "certbot"}
        self.sys.rhel = "9"
        argvs, _certbot = self.lancer(*self.CERTBOT)
        epel = ["sudo", "dnf", "install", "-y", "epel-release"]
        certbot = ["sudo", "dnf", "install", "-y", "certbot"]
        self.assertLess(argvs.index(epel), argvs.index(certbot))

    def test_fedora_needs_no_epel(self):
        self.faits["family"] = "dnf"
        self.sys.absents = {"epel-release", "certbot"}
        argvs, _certbot = self.lancer(*self.CERTBOT)
        self.assertFalse([a for a in argvs if "epel-release" in a])
        self.assertIn(["sudo", "dnf", "install", "-y", "certbot"], argvs)


class TestControleHttp(Banc):
    """nginx rechargé ferme ses anciennes connexions, et le pool vient de
    redémarrer : la première requête du contrôle peut tomber."""

    def pages(self, *reponses):
        suite = list(reponses)
        appels = []

        def http_get(url, host):
            appels.append((url, host))
            return suite.pop(0) if len(suite) > 1 else suite[0]

        return appels, mock.patch.object(native_prod, "http_get", http_get)

    def test_a_dropped_first_request_is_tried_again(self):
        appels, patch = self.pages(
            "ERROR Remote end closed connection without response",
            "ERROR Remote end closed connection without response",
            "<title>Login @ 24.0.1</title>",
        )
        with patch:
            code, runner = self.installer("--tls", "local")
        self.assertEqual(code, 0, "\n".join(runner.sortie))
        self.assertEqual(len(appels), 3)
        self.assertEqual(appels[0], ("https://127.0.0.1/", "erp.example.org"))

    def test_a_site_that_never_answers_fails_after_the_last_try(self):
        appels, patch = self.pages("502 Bad Gateway")
        with patch:
            code, runner = self.installer("--tls", "local")
        self.assertEqual(code, 1)
        self.assertEqual(len(appels), native_prod.CHECK_TRIES)
        self.assertEqual(
            native_prod.time.sleep.call_count, native_prod.CHECK_TRIES - 1
        )
        self.assertIn(
            native_prod.t("nginx does not serve the login page."),
            "\n".join(runner.sortie),
        )


class TestAutoriteLocale(unittest.TestCase):
    def test_the_reverse_proxy_authority_signs_every_instance(self):
        # Importée une fois dans le navigateur pour le mandataire, elle vaut
        # pour chaque instance ; le certificat serveur reste à l'instance.
        from script.reverse_proxy import local_cert

        rendu = {
            "server_crt": "/w/server.crt",
            "server_key": "/w/server.key",
            "ca_crt": "/ca/ca.crt",
        }
        with mock.patch.object(
            local_cert, "issue", return_value=rendu
        ) as issue:
            triple = native_prod.issue_local_cert("/w", ["erp.example.org"])
        issue.assert_called_once_with(
            "/w", ["erp.example.org"], ca_dir=local_cert.DEFAULT_DIR
        )
        self.assertEqual(
            triple, ("/w/server.crt", "/w/server.key", "/ca/ca.crt")
        )


# Forme du nginx.conf livré par Arch : un serveur dans http{}, aucun
# dossier de sites inclus.
NGINX_ARCH = """worker_processes  1;
events {
    worker_connections  1024;
}
http {
    include       mime.types;
    server {
        listen       80;
        server_name  localhost;
        location / {
            root   /usr/share/nginx/html;
        }
    }
}
"""


class TestArch(unittest.TestCase):
    def test_the_include_line_is_added_once(self):
        une = native_prod.ensure_conf_d_include(NGINX_ARCH)
        self.assertIn("    include conf.d/*.conf;\n", une)
        self.assertEqual(native_prod.ensure_conf_d_include(une), une)

    def test_the_include_comes_after_the_distribution_server(self):
        # En tête de http{}, le site ERPLibre passerait avant le serveur de
        # la distribution et deviendrait le serveur par défaut.
        une = native_prod.ensure_conf_d_include(NGINX_ARCH)
        self.assertLess(
            une.index("server_name  localhost;"),
            une.index("include conf.d/*.conf;"),
        )
        # Toujours DANS http{} : juste avant son accolade de colonne 0.
        self.assertTrue(une.endswith("    include conf.d/*.conf;\n}\n"))

    def test_a_config_whose_http_block_it_cannot_find_is_refused(self):
        # Sans accolade en colonne 0, la ligne irait n'importe où.
        for texte in ("events {\n}\n", "http { include mime.types; }\n"):
            with self.subTest(texte=texte):
                with self.assertRaises(ValueError):
                    native_prod.ensure_conf_d_include(texte)


if __name__ == "__main__":
    unittest.main()
