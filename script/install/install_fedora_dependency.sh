#!/usr/bin/env bash
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
#
# Dépendances système ERPLibre pour la famille dnf : Fedora, mais aussi
# AlmaLinux, Rocky et RHEL, qu'install_dev.sh aiguille ici sur ID_LIKE=rhel.
# Équivalent de install_debian_dependency.sh.
#
# Attention : Fedora 41+ livre dnf5, EL9 et EL10 encore dnf4. Les deux ne
# comprennent pas les mêmes options — voir DNF_SKIP plus bas.

. ./env_var.sh

EL_USER=${USER}

# « Sauter un paquet introuvable au lieu d'échouer sur tout le lot » ne
# s'écrit PAS pareil selon la version de dnf : « --skip-unavailable » est une
# option de dnf5 (Fedora 41+), et dnf4 — encore livré par EL9 et EL10, donc
# par AlmaLinux et Rocky — la refuse net : « dnf install: error: unrecognized
# arguments ». Son équivalent y est « --setopt=strict=0 ». On demande donc à
# dnf lui-même ce qu'il comprend, plutôt que de deviner d'après la distro.
if dnf install --help 2>&1 | grep -q -- "--skip-unavailable"; then
  DNF_SKIP="--skip-unavailable"
else
  DNF_SKIP="--setopt=strict=0"
fi
echo "dnf : option de tolerance retenue = ${DNF_SKIP}"
# dnf résilient : rafraîchit le cache (évite « checksum doesn't match » /
# signature après un cache périmé) et saute les paquets introuvables.
DNF="sudo dnf install -y --refresh ${DNF_SKIP}"

#--------------------------------------------------
# Dérivés RHEL : dépôts supplémentaires
#--------------------------------------------------
# AlmaLinux, Rocky, CentOS Stream et RHEL passent par ce script (install_dev.sh
# les aiguille sur ID_LIKE=rhel). Contrairement à Fedora, leur jeu de dépôts
# par défaut est ÉTROIT : la plupart des paquets « -devel » vivent dans CRB
# (CodeReady Builder), et tout ce qui est communautaire dans EPEL. Sans ces
# deux dépôts, la tolérance aux paquets absents les saute EN SILENCE et
# l'échec n'apparaît qu'à la compilation, très loin d'ici.
if [ -r /etc/os-release ]; then
  # shellcheck disable=SC1091
  . /etc/os-release
fi
case "${ID}" in
  almalinux | rocky | rhel | centos)
    echo -e "\n---- Depots EPEL et CRB (famille RHEL) ----"
    sudo dnf install -y epel-release \
      || echo "epel-release indisponible : certains paquets manqueront."
    # /usr/bin/crb est l'outil fourni par epel-release, et ce que son propre
    # scriptlet recommande d'exécuter — plus fiable que de deviner le nom du
    # dépôt, qui vaut « crb » sur EL9/EL10 et « powertools » sur EL8.
    sudo /usr/bin/crb enable 2> /dev/null \
      || sudo dnf config-manager --set-enabled crb 2> /dev/null \
      || sudo dnf config-manager --set-enabled powertools 2> /dev/null \
      || sudo dnf config-manager --enable crb 2> /dev/null \
      || echo "CRB/PowerTools non active : certains -devel manqueront."
    # Un dépôt fraîchement activé dont les métadonnées ne descendent pas fait
    # échouer TOUS les dnf suivants. On le voit ici, avec son nom, plutôt que
    # trois sections plus loin sur un paquet sans rapport.
    sudo dnf makecache 2> /dev/null \
      || { sudo dnf clean all; sudo dnf makecache; } \
      || echo "Attention : metadonnees de depot incompletes."
    ;;
esac

#--------------------------------------------------
# Outils de compilation (build Python via pyenv, extensions Python)
#--------------------------------------------------
echo -e "\n---- Outils de developpement ----"
# Les GROUPES ne sont pas les mêmes d'une famille à l'autre : Fedora a
# « c-development », EL ne connaît que « development » — vérifié dans le
# comps.xml d'AlmaLinux 10, qui n'a même pas « development-tools ».
#
# Pire, la tolérance aux paquets absents les rend INOFFENSIFS : un
# « dnf group install » de deux groupes inconnus REND ZÉRO sans rien poser,
# donc le « || » de repli ne se déclenchait jamais. gcc arrivait par la
# section pyenv plus bas, gcc-c++ par personne, et numpy s'arrêtait sur
# « Unknown compiler(s): [['c++'], ['g++'], …] ».
#
# On installe donc les compilateurs EXPLICITEMENT, sans dépendre d'un groupe.
# Le groupe reste ensuite, en complément et en best-effort.
${DNF} gcc gcc-c++ make automake patch
retVal=$?
if [[ $retVal -ne 0 ]]; then
  echo "dnf install compilers error."
  exit 1
fi
sudo dnf group install -y ${DNF_SKIP} development c-development \
  > /dev/null 2>&1 || true

#--------------------------------------------------
# Mainframe s390x
#--------------------------------------------------
# Sur s390x, AUCUNE roue PyPI n'existe : numpy, pillow, lxml, pikepdf,
# psycopg2, cryptography… tout se compile contre les bibliothèques de la
# distribution. Ces en-têtes ne servent à rien sur amd64, où pip pose des
# roues, mais leur absence ici arrête l'installation très loin de sa cause —
# « The headers or library files could not be found for jpeg » pour pillow.
if [ "$(uname -m)" = "s390x" ]; then
  echo -e "\n---- Dependances de compilation s390x ----"
  # Best-effort : un nom qui change d'une version à l'autre ne doit pas
  # emporter le lot. Ce qui est vraiment indispensable est déjà installé
  # au-dessus (compilateurs) ou plus bas (pyenv, PostgreSQL).
  ${DNF} \
    libjpeg-turbo-devel zlib-devel qpdf-devel geos-devel proj-devel \
    krb5-devel tbb-devel ninja-build clang-devel llvm-devel \
    GeographicLib-devel
  # pymupdf charge « libclang.so » par son nom nu, via ctypes. Le paquet le
  # livre sous un nom versionné : il ne manque que le lien.
  for d in /usr/lib64 /usr/lib; do
    if [ -d "${d}" ] && [ ! -e "${d}/libclang.so" ]; then
      so="$(ls -1 "${d}"/libclang.so.* 2> /dev/null | sort -V | tail -1)"
      if [ -n "${so}" ]; then
        sudo ln -s "${so}" "${d}/libclang.so" && sudo ldconfig
        echo "libclang.so -> ${so}"
      fi
    fi
  done
fi

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
# git-daemon : sur Fedora la sous-commande « git daemon » N'EST PAS dans le
# paquet « git » de base (contrairement à Debian/Ubuntu/Arch). ERPLibre sert
# son manifeste via un « git daemon » local (git://127.0.0.1:9418/) pendant
# « repo sync » -> sans ce paquet : « git: 'daemon' is not a git command »
# puis « Connection refused » et l'échec de la synchro du manifeste.
${DNF} \
  git git-daemon wget libxslt-devel libzip-devel openldap-devel \
  cyrus-sasl-devel \
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
