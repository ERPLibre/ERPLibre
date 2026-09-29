#!/usr/bin/env bash
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
#
# Les binaires de PostgreSQL 16 du cluster de migration.
#
#   ./script/install/install_postgresql_migration.sh
#
# Ils s'installent À CÔTÉ du serveur du système, sans créer ni démarrer de
# cluster système : script/database/migration_cluster.py monte le sien dans
# private/postgresql/16, sous le compte qui lance la migration.
#
# Arch : le paquet AUR postgresql16, construit par makepkg sous ce compte,
# s'installe sous /opt/postgresql16 et coexiste avec le paquet officiel.
# --nocheck évite « make check-world », que makepkg lance sinon. Son
# /opt/postgresql16/bin/pgenv.sh pointe PGDATA sur /var/lib/postgres/data16 :
# ce script ne le source pas, et le cluster de migration n'en dépend pas.
#
# Debian et Ubuntu : postgresql-16, de la distribution ou de PGDG, sous
# /usr/lib/postgresql/16/bin. Un cluster 16/main n'est créé que sur une
# machine qui n'en a encore aucun.
#
# Fedora : le postgresql16-server de la distribution est en conflit avec le
# serveur par défaut ; la voie PGDG n'est pas prise en charge ici.

set -euo pipefail

VERSION=16
OS_RELEASE="${EL_OS_RELEASE:-/etc/os-release}"
# shellcheck disable=SC1090
. "${OS_RELEASE}"
FAMILLE=" ${ID:-} ${ID_LIKE:-} "

case "${FAMILLE}" in
  *" arch "*)
    sudo pacman -S --needed --noconfirm base-devel git
    CONSTRUCTION="${XDG_CACHE_HOME:-${HOME}/.cache}/erplibre/aur/postgresql${VERSION}"
    rm -rf "${CONSTRUCTION}"
    mkdir -p "$(dirname "${CONSTRUCTION}")"
    git clone --depth 1 "https://aur.archlinux.org/postgresql${VERSION}.git" \
      "${CONSTRUCTION}"
    (cd "${CONSTRUCTION}" \
      && MAKEFLAGS="-j$(nproc)" makepkg -si --noconfirm --needed --nocheck)
    ;;
  *" debian "* | *" ubuntu "*)
    if ! apt-cache show "postgresql-${VERSION}" > /dev/null 2>&1; then
      sudo apt-get install -y postgresql-common
      sudo /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh -y
    fi
    sudo apt-get install -y "postgresql-${VERSION}"
    ;;
  *" fedora "* | *" rhel "*)
    echo "Fedora : le postgresql${VERSION}-server de la distribution entre en" >&2
    echo "  conflit avec le serveur par defaut. Posez les binaires ${VERSION}" >&2
    echo "  a la main, puis indiquez leur repertoire par EL_PG${VERSION}_BINDIR." >&2
    exit 1
    ;;
  *)
    echo "Distribution non prise en charge : ${ID:-inconnue}." >&2
    echo "  Indiquez le repertoire des binaires ${VERSION} par EL_PG${VERSION}_BINDIR." >&2
    exit 1
    ;;
esac

./.venv.erplibre/bin/python ./script/database/migration_cluster.py bindir
