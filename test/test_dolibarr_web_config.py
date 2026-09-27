#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Configurations nginx et PHP-FPM d'une instance Dolibarr.

En développement, nginx et PHP-FPM tournent sous le compte du développeur,
sur un port local : rien dans /etc, rien en root. Ce qui se garde :
- PATH_INFO arrive jusqu'à PHP (l'API REST de Dolibarr en dépend) : il est
  capturé AVANT try_files, qui le viderait ;
- aucun PHP ne s'exécute sous /conf/ ni /includes/ ;
- tout ce que les deux démons écrivent reste dans le dossier run/ de
  l'instance, que le compte possède.

En production, chaque bloc server refuse un nom d'hôte autre que le
domaine : nginx confie à un bloc les requêtes qu'aucun server_name ne
prend dès qu'il est le premier sur son port, ce qui arrive selon l'ordre
d'inclusion de la distribution, en IPv6 et sur 443.
"""

import os
import sys
import unittest

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
if RACINE not in sys.path:
    sys.path.insert(0, RACINE)

from script.dolibarr import web_config  # noqa: E402

RUN = "/srv/essai/dolibarr/erp/run"
HTDOCS = "/srv/essai/checkout/htdocs"


class TestDevFpm(unittest.TestCase):
    def setUp(self):
        self.texte = web_config.render_dev_fpm(RUN)
        self.lignes = [ligne.strip() for ligne in self.texte.splitlines()]

    def test_every_file_it_writes_stays_in_run(self):
        for ligne in (
            f"pid = {RUN}/php-fpm.pid",
            f"error_log = {RUN}/php-fpm.log",
            f"listen = {RUN}/php-fpm.sock",
            f"php_admin_value[session.save_path] = {RUN}/sessions",
        ):
            with self.subTest(ligne=ligne):
                self.assertIn(ligne, self.lignes)

    def test_no_user_directive_for_a_non_root_master(self):
        self.assertFalse(
            [x for x in self.lignes if x.startswith(("user ", "group "))]
        )

    def test_it_stays_in_the_foreground(self):
        # run.py le lance et l'arrête ; un démon détaché lui échapperait.
        self.assertIn("daemonize = no", self.lignes)

    def test_uploads_bigger_than_the_php_default(self):
        self.assertIn(
            "php_admin_value[upload_max_filesize] = 64M", self.lignes
        )
        self.assertIn("php_admin_value[post_max_size] = 64M", self.lignes)


class TestDevNginx(unittest.TestCase):
    def setUp(self):
        self.texte = web_config.render_dev_nginx(RUN, HTDOCS, 8080)
        self.lignes = [ligne.strip() for ligne in self.texte.splitlines()]

    def test_listens_on_loopback_only(self):
        self.assertIn("listen 127.0.0.1:8080;", self.lignes)

    def test_serves_htdocs(self):
        self.assertIn(f"root {HTDOCS};", self.lignes)
        self.assertIn("index index.php index.html;", self.lignes)

    def test_path_info_is_captured_before_try_files(self):
        i_set = self.lignes.index("set $path_info $fastcgi_path_info;")
        i_try = self.lignes.index("try_files $fastcgi_script_name =404;")
        self.assertLess(i_set, i_try)
        self.assertIn("fastcgi_param PATH_INFO $path_info;", self.lignes)
        self.assertIn(
            "fastcgi_split_path_info ^(.+?\\.php)(/.*)$;", self.lignes
        )

    def test_php_goes_to_the_instance_socket(self):
        self.assertIn(f"fastcgi_pass unix:{RUN}/php-fpm.sock;", self.lignes)
        self.assertIn(
            "fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;",
            self.lignes,
        )
        # httpoxy : l'en-tête Proxy du client ne devient pas HTTP_PROXY.
        self.assertIn('fastcgi_param HTTP_PROXY "";', self.lignes)

    def test_no_php_runs_under_conf_or_includes(self):
        i_deny = self.lignes.index("location ~ ^/(conf|includes)/.*\\.php$ {")
        i_php = self.lignes.index("location ~ [^/]\\.php(/|$) {")
        # nginx prend la première regex qui correspond : le refus d'abord.
        self.assertLess(i_deny, i_php)
        self.assertEqual(self.lignes[i_deny + 1], "deny all;")

    def test_every_file_it_writes_stays_in_run(self):
        for ligne in (
            f"pid {RUN}/nginx.pid;",
            f"error_log {RUN}/nginx-error.log;",
            f"access_log {RUN}/nginx-access.log;",
            f"client_body_temp_path {RUN}/tmp/client;",
            f"fastcgi_temp_path {RUN}/tmp/fastcgi;",
            f"proxy_temp_path {RUN}/tmp/proxy;",
            f"uwsgi_temp_path {RUN}/tmp/uwsgi;",
            f"scgi_temp_path {RUN}/tmp/scgi;",
        ):
            with self.subTest(ligne=ligne):
                self.assertIn(ligne, self.lignes)

    def test_the_port_must_be_unprivileged(self):
        with self.assertRaises(ValueError):
            web_config.render_dev_nginx(RUN, HTDOCS, 80)


class TestRunDirs(unittest.TestCase):
    def test_the_directories_nginx_and_fpm_expect(self):
        self.assertEqual(
            web_config.run_dirs(RUN),
            [
                RUN,
                f"{RUN}/sessions",
                f"{RUN}/tmp/client",
                f"{RUN}/tmp/fastcgi",
                f"{RUN}/tmp/proxy",
                f"{RUN}/tmp/uwsgi",
                f"{RUN}/tmp/scgi",
            ],
        )


CODE = "/opt/erplibre-dolibarr/erp"
DATA = "/var/lib/erplibre-dolibarr/erp"
SOCK = "/run/erplibre-dolibarr-erp.sock"


class TestProdFpm(unittest.TestCase):
    def setUp(self):
        self.texte = web_config.render_prod_fpm(
            "erp", "dolibarr_erp", "www-data", SOCK, CODE, DATA
        )
        self.lignes = [ligne.strip() for ligne in self.texte.splitlines()]

    def test_the_pool_runs_as_the_instance_account(self):
        self.assertEqual(self.lignes[0], "[erplibre-dolibarr-erp]")
        self.assertIn("user = dolibarr_erp", self.lignes)
        self.assertIn("group = dolibarr_erp", self.lignes)

    def test_only_nginx_reads_the_socket(self):
        self.assertIn(f"listen = {SOCK}", self.lignes)
        self.assertIn("listen.owner = www-data", self.lignes)
        self.assertIn("listen.group = www-data", self.lignes)
        self.assertIn("listen.mode = 0660", self.lignes)

    def test_php_is_confined_to_code_data_and_tmp(self):
        self.assertIn(
            f"php_admin_value[open_basedir] = {CODE}/:{DATA}/:/tmp/",
            self.lignes,
        )
        self.assertIn(
            f"php_admin_value[session.save_path] = {DATA}/sessions",
            self.lignes,
        )
        self.assertIn("php_admin_flag[display_errors] = off", self.lignes)


CERT = "/etc/erplibre-dolibarr/erp/tls/server.crt"
KEY = "/etc/erplibre-dolibarr/erp/tls/server.key"


class TestProdNginx(unittest.TestCase):
    def rendre(self, tls, **kw):
        texte = web_config.render_prod_nginx(
            "erp", f"{CODE}/htdocs", "erp.example.org", SOCK, tls, **kw
        )
        return [ligne.strip() for ligne in texte.splitlines()]

    def test_plain_http_serves_the_application_on_80(self):
        lignes = self.rendre("none")
        self.assertIn("listen 80;", lignes)
        self.assertIn("server_name erp.example.org;", lignes)
        self.assertIn(f"root {CODE}/htdocs;", lignes)
        self.assertNotIn("listen 443 ssl;", lignes)

    def test_the_install_directory_is_refused(self):
        lignes = self.rendre("none")
        i = lignes.index("location ^~ /install/ {")
        self.assertEqual(lignes[i + 1], "deny all;")

    def test_path_info_and_socket_as_in_development(self):
        lignes = self.rendre("none")
        i_set = lignes.index("set $path_info $fastcgi_path_info;")
        i_try = lignes.index("try_files $fastcgi_script_name =404;")
        self.assertLess(i_set, i_try)
        self.assertIn(f"fastcgi_pass unix:{SOCK};", lignes)
        self.assertIn('fastcgi_param HTTP_PROXY "";', lignes)

    def test_hidden_files_and_conf_php_are_refused(self):
        lignes = self.rendre("none")
        self.assertIn("location ~ /\\. {", lignes)
        self.assertIn("location ~ ^/(conf|includes)/.*\\.php$ {", lignes)

    def test_local_tls_redirects_80_and_serves_443(self):
        lignes = self.rendre(
            "local",
            cert="/etc/erplibre-dolibarr/erp/tls/server.crt",
            key="/etc/erplibre-dolibarr/erp/tls/server.key",
        )
        self.assertIn("listen 443 ssl;", lignes)
        self.assertIn(
            "ssl_certificate /etc/erplibre-dolibarr/erp/tls/server.crt;",
            lignes,
        )
        self.assertIn(
            "ssl_certificate_key /etc/erplibre-dolibarr/erp/tls/server.key;",
            lignes,
        )
        # L'application n'est servie qu'une fois, en HTTPS.
        self.assertEqual(lignes.count(f"root {CODE}/htdocs;"), 1)

    def test_every_server_refuses_another_host_name(self):
        for tls in web_config.TLS_MODES:
            with self.subTest(tls=tls):
                texte = web_config.render_prod_nginx(
                    "erp",
                    f"{CODE}/htdocs",
                    "erp.example.org",
                    SOCK,
                    tls,
                    cert=CERT,
                    key=KEY,
                )
                blocs = texte.split("server {")[1:]
                self.assertTrue(blocs)
                for bloc in blocs:
                    lignes = [x.strip() for x in bloc.splitlines()]
                    i = lignes.index('if ($host != "erp.example.org") {')
                    self.assertEqual(lignes[i + 1], "return 444;")

    def test_the_host_is_compared_in_lowercase(self):
        # nginx met $host en minuscules : un domaine saisi en capitales
        # refuserait sinon son propre nom.
        texte = web_config.render_prod_nginx(
            "erp", f"{CODE}/htdocs", "ERP.Example.org", SOCK, "none"
        )
        self.assertIn('if ($host != "erp.example.org") {', texte)

    def test_the_redirect_names_the_domain_not_the_request(self):
        # $host renverrait vers le nom que le client a envoyé.
        lignes = self.rendre("local", cert=CERT, key=KEY)
        self.assertIn(
            "return 301 https://erp.example.org$request_uri;", lignes
        )
        self.assertFalse([x for x in lignes if "https://$host" in x])

    def test_the_php_version_is_not_announced(self):
        self.assertIn("fastcgi_hide_header X-Powered-By;", self.rendre("none"))

    def test_certbot_starts_from_plain_http_it_will_rewrite(self):
        # certbot --nginx ajoute lui-même le bloc 443 et la redirection.
        lignes = self.rendre("certbot")
        self.assertIn("listen 80;", lignes)
        self.assertNotIn("listen 443 ssl;", lignes)

    def test_local_tls_needs_its_certificate(self):
        with self.assertRaises(ValueError):
            self.rendre("local")

    def test_an_unknown_tls_mode_is_refused(self):
        with self.assertRaises(ValueError):
            self.rendre("maybe")

    def test_a_domain_with_a_space_or_semicolon_is_refused(self):
        # Il entre tel quel dans le fichier : « ; » y fermerait la directive.
        for mauvais in ("a b.org", "a.org;", "a.org\n"):
            with self.subTest(mauvais=mauvais):
                with self.assertRaises(ValueError):
                    web_config.render_prod_nginx(
                        "erp", f"{CODE}/htdocs", mauvais, SOCK, "none"
                    )


if __name__ == "__main__":
    unittest.main()
