#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Paquets et emplacements du natif Dolibarr, par famille de distribution.

Données pures, relevées en installant la pile dans des conteneurs jetables
de chaque famille (Debian/Ubuntu, Fedora/EL, Arch, openSUSE) : les noms sont
ceux qui s'installent, pas ceux qu'on attendrait.

Deux familles s'écartent de la forme commune :
- Arch livre mysqli, intl, calendar et soap DANS le paquet php, éteints ;
  extensions_ini rend le fichier qui les allume pour la CLI et FPM.
- openSUSE découpe PHP plus finement : openssl, iconv, fileinfo… sont des
  paquets à part, et sans php8-openssl dolEncrypt de Dolibarr range les
  valeurs en clair, sans erreur.

Absents exprès partout : php-imap (introuvable sur Debian 13, Ubuntu 26.04,
Arch, EL et SUSE), php-opcache (inexistant sur Ubuntu 26.04, et tiré par
php-fpm ailleurs) et php-json (json est dans PHP 8, et le paquet seul tire
apache2 sur Ubuntu 26.04).
"""

FAMILIES = ("apt-get", "dnf", "pacman", "zypper")
DATABASES = ("mariadb", "postgresql")

_PHP = {
    "apt-get": [
        "php-fpm",
        "php-cli",
        "php-gd",
        "php-curl",
        "php-intl",
        "php-xml",
        "php-zip",
        "php-mbstring",
        "php-soap",
    ],
    "dnf": [
        "php-fpm",
        "php-cli",
        "php-gd",
        "php-intl",
        "php-xml",
        "php-pecl-zip",
        "php-mbstring",
        "php-soap",
    ],
    "pacman": ["php", "php-fpm", "php-gd"],
    "zypper": [
        "php8-fpm",
        "php8-cli",
        "php8-gd",
        "php8-curl",
        "php8-intl",
        "php8-dom",
        "php8-zip",
        "php8-mbstring",
        "php8-calendar",
        "php8-soap",
        "php8-openssl",
        "php8-iconv",
        "php8-fileinfo",
        "php8-zlib",
        "php8-ctype",
        "php8-posix",
        "php8-tokenizer",
        "php8-xmlreader",
        "php8-xmlwriter",
    ],
}

# (pilote PHP, serveur) par famille et par base. Sur Arch, mysqli est dans
# le paquet php : aucun pilote à ajouter pour MariaDB.
_DB = {
    "apt-get": {
        "mariadb": (["php-mysql"], ["mariadb-server"]),
        "postgresql": (["php-pgsql"], ["postgresql"]),
    },
    "dnf": {
        "mariadb": (["php-mysqlnd"], ["mariadb-server"]),
        "postgresql": (["php-pgsql"], ["postgresql-server"]),
    },
    "pacman": {
        "mariadb": ([], ["mariadb"]),
        "postgresql": (["php-pgsql"], ["postgresql"]),
    },
    "zypper": {
        "mariadb": (["php8-mysql"], ["mariadb"]),
        "postgresql": (["php8-pgsql"], ["postgresql-server"]),
    },
}


def _check(family, db=None):
    if family not in FAMILIES:
        raise ValueError(f"unknown package family {family!r}")
    if db is not None and db not in DATABASES:
        raise ValueError(f"unknown database {db!r}")


def packages_for(family, db):
    """Paquets à installer : PHP et ses extensions, pilote, serveur, nginx."""
    _check(family, db)
    driver, server = _DB[family][db]
    return _PHP[family] + driver + server + ["nginx"]


def extensions_ini(family, db):
    """(chemin, texte) du fichier qui allume les extensions, ou None.

    Seul Arch en a besoin : son paquet php les porte éteintes. Un fichier à
    part plutôt que php.ini, qui appartient au paquet.
    """
    _check(family, db)
    if family != "pacman":
        return None
    driver = "mysqli" if db == "mariadb" else "pgsql"
    lines = [f"extension={e}" for e in (driver, "gd", "intl", "calendar")]
    lines.append("extension=soap")
    return "/etc/php/conf.d/erplibre-dolibarr.ini", "\n".join(lines) + "\n"


def fpm_layout(family, php_version):
    """Binaire, unité systemd, dossier des pools et compte de nginx.

    `php_version` (« 8.3 ») n'entre dans les chemins que sur Debian/Ubuntu,
    qui versionnent binaire, unité et configuration. web_user est le compte
    sous lequel nginx lit la socket du pool.
    """
    _check(family)
    if family == "apt-get":
        v = php_version
        return {
            "binary": f"/usr/sbin/php-fpm{v}",
            "unit": f"php{v}-fpm.service",
            "pool_dir": f"/etc/php/{v}/fpm/pool.d",
            "web_user": "www-data",
        }
    if family == "dnf":
        return {
            "binary": "/usr/sbin/php-fpm",
            "unit": "php-fpm.service",
            "pool_dir": "/etc/php-fpm.d",
            "web_user": "nginx",
        }
    if family == "pacman":
        return {
            "binary": "/usr/bin/php-fpm",
            "unit": "php-fpm.service",
            "pool_dir": "/etc/php/php-fpm.d",
            "web_user": "http",
        }
    return {
        "binary": "/usr/sbin/php-fpm",
        "unit": "php-fpm.service",
        "pool_dir": "/etc/php8/fpm/php-fpm.d",
        "web_user": "nginx",
    }


def nginx_site(family, instance):
    """(fichier du site, lien d'activation ou None) pour `instance`.

    Debian/Ubuntu activent un site par un lien dans sites-enabled ; les
    autres lisent directement conf.d (vhosts.d sur openSUSE).
    """
    _check(family)
    name = f"erplibre-dolibarr-{instance}"
    if family == "apt-get":
        return (
            f"/etc/nginx/sites-available/{name}",
            f"/etc/nginx/sites-enabled/{name}",
        )
    if family == "zypper":
        return f"/etc/nginx/vhosts.d/{name}.conf", None
    return f"/etc/nginx/conf.d/{name}.conf", None


def nginx_needs_include(family):
    """Vrai si nginx.conf n'inclut aucun dossier de sites (Arch)."""
    _check(family)
    return family == "pacman"
