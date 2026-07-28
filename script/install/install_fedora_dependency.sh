#!/usr/bin/env bash
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
#
# Dépendances système ERPLibre pour Fedora (dnf). Équivalent Fedora de
# install_debian_dependency.sh. « --skip-unavailable » tolère un nom de paquet
# absent (dnf5) au lieu d'échouer sur tout le lot.

. ./env_var.sh

EL_USER=${USER}

# dnf résilient : rafraîchit le cache (évite « checksum doesn't match » /
# signature après un cache périmé) et saute les paquets introuvables.
DNF="sudo dnf install -y --refresh --skip-unavailable"

#--------------------------------------------------
# Outils de compilation (build Python via pyenv, extensions Python)
#--------------------------------------------------
echo -e "\n---- Groupe outils de développement ----"
# Groupes par ID (le nom affiché « C Development Tools... » n'est pas matché).
sudo dnf group install -y --skip-unavailable development-tools c-development \
  || sudo dnf install -y gcc gcc-c++ make automake patch

#--------------------------------------------------
# PostgreSQL
#--------------------------------------------------
echo -e "\n---- Install PostgreSQL Server ----"
${DNF} postgresql-server postgresql-contrib libpq-devel
retVal=$?
if [[ $retVal -ne 0 ]]; then
  echo "dnf install postgresql installation error."
  exit 1
fi
# Initialisation du cluster (Fedora ne le fait pas automatiquement).
if [ ! -f /var/lib/pgsql/data/PG_VERSION ]; then
  echo -e "\n---- Initialisation du cluster PostgreSQL ----"
  # Nettoie un init partiel et FORCE une locale valide : les images cloud
  # Fedora n'ont pas de LANG défini -> « initdb: invalid locale settings ».
  sudo rm -rf /var/lib/pgsql/data
  sudo PGSETUP_INITDB_OPTIONS="--locale=C.UTF-8 --encoding=UTF8" \
    postgresql-setup --initdb || true
fi
sudo systemctl enable --now postgresql 2>/dev/null || true
# PostGIS : optionnel (géospatial), ne bloque pas.
${DNF} postgis || echo "PostGIS non installé (optionnel)."

echo -e "\n---- Creating the ERPLibre PostgreSQL User ----"
sudo su - postgres -c "createuser -s ${EL_USER}" 2>/dev/null || true

#--------------------------------------------------
# Dépendances de build (extensions Python, Odoo)
#--------------------------------------------------
echo -e "\n--- Installing fedora dependency --"
${DNF} \
  git wget libxslt-devel libzip-devel openldap-devel cyrus-sasl-devel \
  libffi-devel bzip2-devel parallel swig cmake portaudio-devel \
  cups-devel xmlsec1 xmlsec1-openssl mariadb-connector-c-devel freetds-devel
retVal=$?
if [[ $retVal -ne 0 ]]; then
  echo "dnf fedora tool installation error."
  exit 1
fi

# Dépendances de build pour pyenv (compilation de CPython) — CRITIQUE.
echo -e "\n---- Dépendances pyenv (compilation Python) ----"
${DNF} \
  make gcc zlib-devel bzip2 bzip2-devel readline-devel sqlite sqlite-devel \
  openssl-devel tk-devel libffi-devel xz-devel patch findutils
retVal=$?
if [[ $retVal -ne 0 ]]; then
  echo "dnf pyenv dependencies installation error."
  exit 1
fi

# Dépendances selenium / bindings.
${DNF} \
  cairo-devel python3-devel pkgconf-pkg-config gobject-introspection-devel \
  libXt-devel || echo "Dépendances selenium partielles (optionnel)."

#--------------------------------------------------
# Node.js + npm (rtlcss, less)
#--------------------------------------------------
echo -e "\n---- Installing nodeJS NPM and rtlcss ----"
${DNF} nodejs npm
retVal=$?
if [[ $retVal -ne 0 ]]; then
  echo "dnf nodejs installation error."
  exit 1
fi
sudo npm install -g rtlcss less || echo "npm rtlcss/less: erreur (optionnel)."

echo -e "\n---- Test tool ----"
npm install || echo "npm install (prettier/plugin-xml): erreur (optionnel)."
sudo ln -fs /usr/local/bin/lessc /usr/bin/lessc 2>/dev/null || true

#--------------------------------------------------
# nginx (optionnel)
#--------------------------------------------------
if [ "${EL_INSTALL_NGINX}" = "True" ]; then
  echo -e "\n---- Installing nginx ----"
  ${DNF} nginx || echo "nginx: erreur (optionnel)."
fi

#--------------------------------------------------
# wkhtmltopdf (optionnel) — paquet RPM officiel wkhtmltopdf
#--------------------------------------------------
if [ "${EL_INSTALL_WKHTMLTOPDF}" = "True" ]; then
  if ! command -v wkhtmltopdf >/dev/null 2>&1; then
    echo -e "\n---- Installing wkhtml (best-effort) ----"
    # wkhtmltopdf ne publie plus de build « fedora-* » ; le RPM AlmaLinux 9
    # (EL9) est compatible Fedora (testé sur F42 : dnf résout les deps).
    # Repli AlmaLinux 8 au besoin.
    _base="https://github.com/wkhtmltopdf/packaging/releases/download/0.12.6.1-3"
    sudo dnf install -y "${_base}/wkhtmltox-0.12.6.1-3.almalinux9.x86_64.rpm" \
      || sudo dnf install -y "${_base}/wkhtmltox-0.12.6.1-3.almalinux8.x86_64.rpm" \
      || echo "wkhtmltopdf non installé (optionnel)."
  else
    echo -e "\n---- Already installed wkhtml ----"
  fi
fi

echo -e "\n---- Fedora dependency installation done ----"
