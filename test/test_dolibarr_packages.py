#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Paquets et emplacements du natif Dolibarr, par famille de distribution.

Les attentes sont des NOMS qui s'installent sur Debian 12/13, Ubuntu
24.04/26.04, Fedora 44, AlmaLinux 9/10, Arch et openSUSE Tumbleweed/Leap :
une liste fausse ne se voit qu'à l'installation, sur la machine d'un autre.
"""

import os
import sys
import unittest

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
if RACINE not in sys.path:
    sys.path.insert(0, RACINE)

from script.dolibarr import packages  # noqa: E402


class TestPackages(unittest.TestCase):
    def test_debian_family_mariadb(self):
        self.assertEqual(
            packages.packages_for("apt-get", "mariadb"),
            [
                "php-fpm",
                "php-cli",
                "php-gd",
                "php-curl",
                "php-intl",
                "php-xml",
                "php-zip",
                "php-mbstring",
                "php-soap",
                "php-mysql",
                "mariadb-server",
                "nginx",
            ],
        )

    def test_debian_family_postgresql(self):
        liste = packages.packages_for("apt-get", "postgresql")
        self.assertIn("php-pgsql", liste)
        self.assertIn("postgresql", liste)
        self.assertNotIn("php-mysql", liste)
        self.assertNotIn("mariadb-server", liste)

    def test_rpm_family(self):
        liste = packages.packages_for("dnf", "mariadb")
        # php-mysqlnd porte mysqli ; php-pecl-zip porte zip ; php-process
        # porte posix, que les autres familles livrent avec PHP.
        for nom in (
            "php-mysqlnd",
            "php-pecl-zip",
            "php-process",
            "mariadb-server",
            "nginx",
        ):
            with self.subTest(nom=nom):
                self.assertIn(nom, liste)
        self.assertIn(
            "postgresql-server", packages.packages_for("dnf", "postgresql")
        )

    def test_arch_ships_most_extensions_inside_php(self):
        self.assertEqual(
            packages.packages_for("pacman", "mariadb"),
            ["php", "php-fpm", "php-gd", "mariadb", "nginx"],
        )
        self.assertEqual(
            packages.packages_for("pacman", "postgresql"),
            ["php", "php-fpm", "php-gd", "php-pgsql", "postgresql", "nginx"],
        )

    def test_suse_needs_openssl_and_the_mariadb_package_name(self):
        liste = packages.packages_for("zypper", "mariadb")
        # Sans php8-openssl, dolEncrypt range les valeurs en clair.
        self.assertIn("php8-openssl", liste)
        self.assertIn("mariadb", liste)
        self.assertNotIn("mariadb-server", liste)
        self.assertTrue(all(not n.startswith("php-") for n in liste), liste)

    def test_no_package_that_does_not_exist_everywhere(self):
        # php-imap manque à Debian 13, Ubuntu 26.04, Arch, EL et SUSE ;
        # php-opcache à Ubuntu 26.04 ; php-json tire apache2 sur 26.04.
        for famille in packages.FAMILIES:
            for db in ("mariadb", "postgresql"):
                liste = packages.packages_for(famille, db)
                for absent in ("php-imap", "php-opcache", "php-json"):
                    with self.subTest(famille=famille, db=db, absent=absent):
                        self.assertNotIn(absent, liste)

    def test_unknown_family_or_database_is_refused(self):
        with self.assertRaises(ValueError):
            packages.packages_for("emerge", "mariadb")
        with self.assertRaises(ValueError):
            packages.packages_for("apt-get", "sqlite")


class TestExtensionsIni(unittest.TestCase):
    def test_arch_enables_extensions_by_a_drop_in(self):
        chemin, texte = packages.extensions_ini("pacman", "postgresql")
        self.assertEqual(chemin, "/etc/php/conf.d/erplibre-dolibarr.ini")
        lignes = texte.splitlines()
        # iconv éteint, dolSlugify perd sa translittération ASCII.
        for ext in ("pgsql", "gd", "intl", "calendar", "iconv"):
            with self.subTest(ext=ext):
                self.assertIn(f"extension={ext}", lignes)
        self.assertNotIn("extension=mysqli", lignes)

    def test_other_families_load_their_extensions_already(self):
        for famille in ("apt-get", "dnf", "zypper"):
            with self.subTest(famille=famille):
                self.assertIsNone(packages.extensions_ini(famille, "mariadb"))


class TestCertbot(unittest.TestCase):
    def test_certbot_and_its_nginx_plugin_per_family(self):
        attendu = {
            "apt-get": ["certbot", "python3-certbot-nginx"],
            # Le greffon nginx de Fedora 44 ne tire pas pyparsing, sans
            # lequel toute commande certbot échoue.
            "dnf": ["certbot", "python3-certbot-nginx", "python3-pyparsing"],
            "pacman": ["certbot", "certbot-nginx"],
            # zypper résout ces noms par capacité (python3NN-certbot…).
            "zypper": ["certbot", "python3-certbot-nginx"],
        }
        for famille, noms in attendu.items():
            with self.subTest(famille=famille):
                self.assertEqual(packages.certbot_packages(famille), noms)

    def test_unknown_family_is_refused(self):
        with self.assertRaises(ValueError):
            packages.certbot_packages("brew")


class TestFpmLayout(unittest.TestCase):
    def test_debian_paths_carry_the_php_version(self):
        self.assertEqual(
            packages.fpm_layout("apt-get", "8.3"),
            {
                "binary": "/usr/sbin/php-fpm8.3",
                "unit": "php8.3-fpm.service",
                "pool_dir": "/etc/php/8.3/fpm/pool.d",
                "web_user": "www-data",
            },
        )

    def test_rpm_arch_and_suse(self):
        self.assertEqual(
            packages.fpm_layout("dnf", "8.5")["pool_dir"], "/etc/php-fpm.d"
        )
        self.assertEqual(
            packages.fpm_layout("pacman", "8.5")["binary"], "/usr/bin/php-fpm"
        )
        suse = packages.fpm_layout("zypper", "8.4")
        self.assertEqual(suse["pool_dir"], "/etc/php8/fpm/php-fpm.d")
        self.assertEqual(suse["web_user"], "nginx")
        self.assertEqual(
            packages.fpm_layout("pacman", "8.5")["web_user"], "http"
        )
        self.assertEqual(
            packages.fpm_layout("dnf", "8.5")["web_user"], "nginx"
        )


class TestNginxSite(unittest.TestCase):
    def test_debian_writes_sites_available_and_links_it(self):
        self.assertEqual(
            packages.nginx_site("apt-get", "erp"),
            (
                "/etc/nginx/sites-available/erplibre-dolibarr-erp",
                "/etc/nginx/sites-enabled/erplibre-dolibarr-erp",
            ),
        )

    def test_rpm_and_arch_use_conf_d_suse_vhosts_d(self):
        self.assertEqual(
            packages.nginx_site("dnf", "erp"),
            ("/etc/nginx/conf.d/erplibre-dolibarr-erp.conf", None),
        )
        self.assertEqual(
            packages.nginx_site("pacman", "erp"),
            ("/etc/nginx/conf.d/erplibre-dolibarr-erp.conf", None),
        )
        self.assertEqual(
            packages.nginx_site("zypper", "erp"),
            ("/etc/nginx/vhosts.d/erplibre-dolibarr-erp.conf", None),
        )

    def test_only_arch_needs_an_include_line(self):
        # nginx d'Arch n'a ni conf.d ni sites-* : l'installateur crée
        # conf.d et ajoute « include conf.d/*.conf; » dans http{}.
        self.assertTrue(packages.nginx_needs_include("pacman"))
        for famille in ("apt-get", "dnf", "zypper"):
            with self.subTest(famille=famille):
                self.assertFalse(packages.nginx_needs_include(famille))


if __name__ == "__main__":
    unittest.main()
