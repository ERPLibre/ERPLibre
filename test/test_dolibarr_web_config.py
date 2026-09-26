#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Configurations nginx et PHP-FPM d'une instance Dolibarr de développement.

En développement, nginx et PHP-FPM tournent sous le compte du développeur,
sur un port local : rien dans /etc, rien en root. Ce qui se garde :
- PATH_INFO arrive jusqu'à PHP (l'API REST de Dolibarr en dépend) : il est
  capturé AVANT try_files, qui le viderait ;
- aucun PHP ne s'exécute sous /conf/ ni /includes/ ;
- tout ce que les deux démons écrivent reste dans le dossier run/ de
  l'instance, que le compte possède.
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


if __name__ == "__main__":
    unittest.main()
