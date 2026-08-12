#!/usr/bin/env bash
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
#
# Dépendances système ERPLibre pour la famille SUSE (zypper). Équivalent SUSE
# de install_debian_dependency.sh et install_fedora_dependency.sh.
#
# Visé : openSUSE Leap 16 (le défaut, numéroté et stable) et Tumbleweed (la
# rolling, gardée comme banc d'essai). Les deux livrent un qpdf au-dessus du
# seuil de pikepdf 10 — la compilation de qpdf, une demi-heure sous émulation
# s390x, ne s'y déclenche pas.
#
# Ce qui les sépare dans ce script tient en deux points, tous deux marqués par
# SUSE_ROLLING : le chemin des dépôts, et « dup » contre « up ».

. ./env_var.sh
. ./script/install/lib_qpdf.sh
. ./script/install/lib_lowmem.sh

EL_USER=${USER}

# « --non-interactive » est une option GLOBALE de zypper, elle précède la
# sous-commande. Les deux autres appartiennent à « install » et doivent la
# SUIVRE : placées avant, zypper répond « The flag
# --auto-agree-with-licenses is not known » et s'arrête.
#
# On demande à zypper quelles options il accepte, plutôt que de le supposer :
# la famille SUSE n'est pas testée ici, et un drapeau inconnu fait échouer la
# commande entière au lieu du seul paquet visé.
#   --auto-agree-with-licenses : sinon zypper attend l'acceptation d'une
#     licence, réponse que personne ne donnera dans une installation détachée.
#   --ignore-unknown : saute un nom de paquet absent au lieu de refuser tout
#     le lot, l'équivalent de « --skip-unavailable » côté dnf.
ZYP="sudo zypper --non-interactive"
ZYP_HELP="$(zypper install --help 2>&1 || true)"
ZYP_LIC=""
ZYP_IGN=""
case "${ZYP_HELP}" in
  *--auto-agree-with-licenses*) ZYP_LIC="--auto-agree-with-licenses" ;;
esac
case "${ZYP_HELP}" in
  *--ignore-unknown*) ZYP_IGN="--ignore-unknown" ;;
esac
echo "zypper : options retenues = ${ZYP_LIC} ${ZYP_IGN}"
# Lot obligatoire : un paquet manquant doit se voir.
ZYP_IN="${ZYP} install ${ZYP_LIC}"
# Lot best-effort : un nom absent est sauté.
ZYP_SOFT="${ZYP_IN} ${ZYP_IGN}"

# openSUSE remplace des paquets par des variantes « compat » qui les FOURNISSENT
# sans en porter le nom : sur Tumbleweed, zlib-ng-compat-devel fournit
# zlib-devel et se trouve posé d'office. Demander « zlib-devel » par son nom
# force alors un échange, zypper soulève un conflit — et --non-interactive n'a
# aucune solution par défaut : il énumère les choix, puis ABANDONNE le lot
# entier. C'est ce qui a arrêté l'installation sur amd64, en emportant les huit
# autres dépendances de pyenv qui, elles, ne posaient aucun problème.
# « --ignore-unknown » ne couvre que les noms absents, jamais les conflits.
#
# On ne demande donc que ce que rien ne fournit déjà. rpm interroge les
# « Provides », pas seulement les noms : c'est la seule autorité sur la
# question. Effet de bord bienvenu, une relance ne redemande plus rien.
zyp_filter() {
  local p
  for p in "$@"; do
    rpm -q --whatprovides "${p}" > /dev/null 2>&1 || printf '%s\n' "${p}"
  done
}

# Un telechargement tronque par le miroir fait echouer le LOT ENTIER, et
# zypper ne reessaie pas. Vecu : « libLLVM22 ... OpenSSL SSL_read: unexpected
# eof while reading » a emporte « rust cargo », et l'absence de cargo n'est
# apparue qu'une heure plus tard, dans la compilation de bcrypt. Une seconde
# tentative suffit dans la quasi-totalite des cas.
zyp_retry() {
  local cmd=("$@")
  "${cmd[@]}" && return 0
  echo "  zypper a echoue (reseau ?), seconde tentative..." >&2
  "${cmd[@]}"
}

zyp_in() {
  local todo
  mapfile -t todo < <(zyp_filter "$@")
  if [ "${#todo[@]}" -eq 0 ]; then
    echo "  deja fourni : $*"
    return 0
  fi
  zyp_retry ${ZYP_IN} "${todo[@]}"
}

zyp_soft() {
  local todo
  mapfile -t todo < <(zyp_filter "$@")
  if [ "${#todo[@]}" -eq 0 ]; then
    echo "  deja fourni : $*"
    return 0
  fi
  zyp_retry ${ZYP_SOFT} "${todo[@]}"
}

#--------------------------------------------------
# Miroir des dépôts
#--------------------------------------------------
# Le redirecteur officiel d'openSUSE n'est PAS géographique : mesuré depuis
# Montréal sur les métadonnées oss s390x (15 Mo), download.opensuse.org met
# 23,8 s — il sert depuis l'Europe — contre 2,7 s pour mirrors.rit.edu.
#
# Chaque miroir est SONDÉ sur le chemin de l'architecture courante : tous ne
# répliquent pas les architectures secondaires, et rit.edu sert justement
# zsystems mais pas x86_64. Aucun sondage concluant : on garde les dépôts de
# l'image, donc le comportement d'avant.
# Plusieurs miroirs, sondés dans l'ordre sur le chemin exact du produit et
# de l'architecture : aucun ne réplique tout. Relevé le 2026-08-12 —
# csclub sert Leap mais pas Tumbleweed, leaseweb sert Tumbleweed x86_64
# mais pas les ports zsystems, et rit.edu — seule entrée jusqu'ici — était
# injoignable ce jour-là, ce qui renvoyait tout le monde en Europe.
ZYP_MIRRORS="https://mirror.csclub.uwaterloo.ca/opensuse https://mirrors.rit.edu/opensuse https://mirror.us.leaseweb.net/opensuse"
# Leap et Tumbleweed sont deux PRODUITS, pas deux versions du même : arbres de
# dépôts différents, et surtout une mise à jour de nature différente (plus bas).
SUSE_ID="$([ -r /etc/os-release ] && . /etc/os-release && echo "${ID}")"
SUSE_VER="$([ -r /etc/os-release ] && . /etc/os-release && echo "${VERSION_ID}")"
case "${SUSE_ID}" in
  *tumbleweed*) SUSE_ROLLING=1 ;;
  *) SUSE_ROLLING=0 ;;
esac
if [ "${SUSE_ROLLING}" = 1 ]; then
  # Tumbleweed isole les architectures secondaires sous /ports/.
  zp=tumbleweed
  [ "$(uname -m)" = s390x ] && zp=ports/zsystems/tumbleweed
else
  # Leap 16 unifie tout : un seul arbre, avec s390x dedans. Les chemins
  # /ports/ équivalents rendent 404 — relevé, pas déduit.
  zp="distribution/leap/${SUSE_VER}"
fi
for zm in ${ZYP_MIRRORS}; do
  if curl -fsS --max-time 20 -o /dev/null \
    "${zm}/${zp}/repo/oss/repodata/repomd.xml"; then
    sudo sed -i "s|https\?://download\.opensuse\.org|${zm}|g" \
      /etc/zypp/repos.d/*.repo 2> /dev/null || true
    echo "miroir openSUSE : ${zm}"
    break
  fi
done

echo -e "\n---- Rafraichissement des depots ----"
# Tumbleweed est ROLLING : installer sans rafraîchir mène à des paquets
# introuvables (l'index local pointe des versions déjà retirées du miroir).
sudo zypper --non-interactive refresh || true

# Mise à jour COMPLÈTE, obligatoire pour la même raison qu'Arch : une rolling
# release ne supporte PAS les mises à jour partielles. L'image cloud est un
# instantané figé dont les dépôts ont avancé — vécu sur s390x, git 2.54
# réclamait un perl-Git bâti contre un perl-base plus ancien que celui de
# l'image. zypper proposait alors trois solutions et ATTENDAIT un choix ;
# « --non-interactive » prend le défaut, « c » = annuler, et tout s'arrêtait.
if [ "${SUSE_ROLLING}" = 1 ]; then
  echo -e "\n---- Mise a jour complete (dup) ----"
  ${ZYP} dup ${ZYP_LIC} --allow-vendor-change || true
else
  # Sur Leap, « dup » sert à CHANGER de version, pas à mettre à jour : l'y
  # appeler alignerait la machine sur ce que les dépôts contiennent, ce qui
  # n'est pas ce qu'on veut d'une distribution justement choisie pour ne pas
  # bouger. « up » suffit, l'image et ses dépôts étant de la même version.
  echo -e "\n---- Mise a jour (up) ----"
  ${ZYP} up ${ZYP_LIC} || true
fi

#--------------------------------------------------
# Outils de compilation (build Python via pyenv, extensions Python)
#--------------------------------------------------
echo -e "\n---- Outils de developpement ----"
# Les compilateurs sont installés EXPLICITEMENT, jamais par le seul motif :
# un « pattern » absent ou incomplet laisserait le système sans g++, et
# l'échec n'apparaîtrait qu'à la compilation de numpy — la leçon d'EL, où le
# groupe « development-tools » n'existe pas et où le repli ne partait jamais.
# Les noms non versionnés existent bien dans Tumbleweed (relevé dans le
# primary.xml du dépôt oss) : « gcc » y est un méta-paquet qui tire gcc15.
zyp_in gcc gcc-c++ make automake patch
retVal=$?
if [[ ${retVal} -ne 0 ]]; then
  echo "zypper install compilers error."
  exit 1
fi
# Le motif ensuite, en complément et sans jamais bloquer.
${ZYP_IN} -t pattern devel_basis > /dev/null 2>&1 || true

# Python appelle son compilateur par le nom gravé dans sysconfig, souvent
# « cc ». Sur openSUSE ce lien n'est garanti par aucune déclaration de
# paquet — vécu sur amd64 : « cc -pthread … error: [Errno 2] No such file or
# directory » à la compilation de python-ldap, alors que gcc était installé.
if ! command -v cc > /dev/null 2>&1 && command -v gcc > /dev/null 2>&1; then
  sudo ln -sf "$(command -v gcc)" /usr/local/bin/cc
  echo "cc -> $(command -v gcc)"
fi

#--------------------------------------------------
# PostgreSQL
#--------------------------------------------------
echo -e "\n---- Install PostgreSQL Server ----"
zyp_in postgresql-server postgresql-contrib postgresql-server-devel
retVal=$?
if [[ ${retVal} -ne 0 ]]; then
  echo "zypper install postgresql installation error."
  exit 1
fi
# openSUSE n'initialise pas le cluster : le service le fait au 1er démarrage,
# mais seulement si le répertoire de données est vide.
sudo systemctl enable --now postgresql 2> /dev/null || true
# PostGIS : absent des dépôts Tumbleweed s390x. Optionnel, ne bloque pas.
zyp_soft postgis || echo "PostGIS non installe (optionnel)."

echo -e "\n---- Creating the ERPLibre PostgreSQL User ----"
sudo su - postgres -c "createuser -s ${EL_USER}" 2> /dev/null || true

#--------------------------------------------------
# Dépendances de build (extensions Python, Odoo)
#--------------------------------------------------
echo -e "\n--- Installing suse dependency --"
# git-daemon : comme sur Fedora, « git daemon » n'est pas dans le paquet git de
# base. ERPLibre sert son manifeste par git://127.0.0.1:9418/ pendant
# « repo sync » — sans lui, « Connection refused » et synchro impossible.
# Rust n'est nécessaire QUE là où les roues manquent : bcrypt et cryptography
# portent une extension Rust, et sur amd64 leurs roues masquent le besoin. Sur
# s390x tout compile, et bcrypt s'arrête sur « error: can't find Rust
# compiler ». Tumbleweed livre 1.94, bien au-dessus du 1.78 qu'exige le
# Cargo.lock v4 de cryptography. On évite ainsi ~200 Mo inutiles sur amd64.
if [ "$(uname -m)" = "s390x" ]; then
  # La mémoire est la ressource qui manque en premier ici : cc1plus
  # demande jusqu'à 2,5 Gio pour un seul fichier de matplotlib, et le
  # tueur du noyau abrège sans jamais nommer la mémoire (« Killed signal
  # terminated program cc1plus »). On complète par du swap avant d'en
  # arriver là.
  el_swap_ensure
  zyp_soft rust cargo
  if ! command -v cargo > /dev/null 2>&1; then
    # FATAL, et non plus un simple avertissement : sur s390x, bcrypt et
    # cryptography n'ont aucune roue et portent une extension Rust. Sans
    # cargo l'installation est perdue d'avance — mais elle ne le montrait
    # qu'une heure plus tard, au fond d'une trace pip. Mieux vaut s'arreter
    # ici, ou la cause est encore lisible.
    echo "cargo introuvable apres deux tentatives." >&2
    echo "  bcrypt et cryptography ne peuvent pas se compiler sans lui." >&2
    echo "  Verifiez le miroir zypper, puis relancez." >&2
    exit 1
  fi
  # Sans roue s390x, TOUT se compile contre les en-têtes de la distribution.
  # Cette liste reprend donc celles d'apt et de dnf, aux noms d'openSUSE près
  # — relevés dans l'index oss de zsystems, jamais devinés. La tenir alignée
  # ici plutôt que d'attendre : trois fois de suite, le même manque a été
  # découvert d'abord par Debian, puis retrouvé une distribution à la fois.
  #   tbb-devel   manifold3d refuse de configurer sans lui, et le dit dans un
  #               message de CMake, pas de compilateur : « Parallel mode
  #               enabled, but tbb was not found ».
  #   clang-devel pymupdf charge libclang.so par ctypes (lien juste après).
  #   cmake, pkgconf-pkg-config : nécessaires à el_qpdf_ensure, et ils
  #               n'arrivent que plus bas dans le script.
  #
  # « pkgconf-pkg-config » et non « pkg-config » : aucun RPM ne porte ce
  # dernier nom dans Tumbleweed, il n'existe plus que comme capacité fournie
  # par le premier. La capacité résout aujourd'hui, le nom réel ne dépend
  # de rien.
  #
  # GeographicLib est absent : openSUSE n'empaquette que le binding Python,
  # pas la bibliothèque C++. Rien à poser, contrairement à apt et dnf.
  zyp_soft qpdf-devel libjpeg8-devel cmake pkgconf-pkg-config \
    tbb-devel geos-devel proj-devel krb5-devel ninja clang-devel llvm-devel
  # Tumbleweed livre qpdf 12.3.2 : l'appel ne fait que le constater. Il est là
  # pour que les trois familles suivent la même règle.
  el_qpdf_ensure
  # pymupdf charge « libclang.so » par son nom nu, via ctypes ; le paquet ne
  # livre qu'un nom versionné. Il ne manque que le lien — même correctif que
  # côté apt et dnf.
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

zyp_soft \
  git git-daemon wget libxslt-devel libzip-devel openldap2-devel \
  cyrus-sasl-devel libffi-devel libbz2-devel gnu_parallel swig cmake \
  portaudio-devel cups-devel xmlsec1 xmlsec1-openssl-devel \
  libmariadb-devel freetds-devel
retVal=$?
if [[ ${retVal} -ne 0 ]]; then
  echo "zypper suse tool installation error."
  exit 1
fi

# Dépendances de build pour pyenv (compilation de CPython) — CRITIQUE.
# Python de la DISTRIBUTION d'abord : Tumbleweed livre python312 en 3.12.13,
# qui satisfait « >=3.12.10,<3.13 ». lib_python_provider.sh le prefere alors a
# toute compilation — decisif sur s390x, ou gcc 15.2 s'arrete sur une erreur
# interne en batissant Parser/parser.c de CPython 3.12.10.
# Le nom suit la version demandee : python312 pour 3.12.x.
PY_WANT="$(cat .python-odoo-version 2>/dev/null | xargs)"
PY_PKG="python$(echo "${PY_WANT}" | awk -F. '{print $1 $2}')"
if [ -n "${PY_WANT}" ]; then
  echo -e "\n---- Python ${PY_WANT} depuis la distribution (${PY_PKG}) ----"
  zyp_soft "${PY_PKG}" "${PY_PKG}-devel" "${PY_PKG}-pip"
fi

echo -e "\n---- Dependances pyenv (compilation Python) ----"
zyp_in \
  make gcc zlib-devel libbz2-devel readline-devel sqlite3-devel \
  libopenssl-devel tk-devel libffi-devel xz-devel patch findutils
retVal=$?
if [[ ${retVal} -ne 0 ]]; then
  echo "zypper pyenv dependencies installation error."
  exit 1
fi

# Dépendances selenium / bindings.
zyp_soft \
  cairo-devel python3-devel pkgconf-pkg-config gobject-introspection-devel \
  libXt-devel || echo "Dependances selenium partielles (optionnel)."

#--------------------------------------------------
# Node.js + npm (rtlcss, less)
#--------------------------------------------------
echo -e "\n---- Installing nodeJS NPM and rtlcss ----"
# openSUSE versionne les paquets node (nodejs22, nodejs24…) et ne fournit pas
# toujours de méta-paquet « nodejs ». On prend le plus récent disponible.
NODE_OK=0
for pkg in nodejs24 nodejs22 nodejs20 nodejs; do
  if ${ZYP_IN} "${pkg}" "${pkg/nodejs/npm}" 2> /dev/null; then
    NODE_OK=1
    echo "node fourni par ${pkg}"
    break
  fi
done
if [[ ${NODE_OK} -ne 1 ]] || ! command -v npm > /dev/null 2>&1; then
  echo "zypper nodejs installation error."
  exit 1
fi
sudo npm install -g rtlcss less || echo "npm rtlcss/less: erreur (optionnel)."

echo -e "\n---- Test tool ----"
npm install || echo "npm install (prettier/plugin-xml): erreur (optionnel)."
sudo ln -fs /usr/local/bin/lessc /usr/bin/lessc 2> /dev/null || true

#--------------------------------------------------
# nginx (optionnel)
#--------------------------------------------------
if [ "${EL_INSTALL_NGINX}" = "True" ]; then
  echo -e "\n---- Installing nginx ----"
  zyp_soft nginx || echo "nginx: erreur (optionnel)."
fi

#--------------------------------------------------
# wkhtmltopdf (optionnel)
#--------------------------------------------------
if [ "${EL_INSTALL_WKHTMLTOPDF}" = "True" ]; then
  if ! command -v wkhtmltopdf > /dev/null 2>&1; then
    echo -e "\n---- Installing wkhtml (best-effort) ----"
    # wkhtmltopdf ne publie AUCUN paquet openSUSE. Le dépôt de la distribution
    # fournit « wkhtmltopdf » quand il existe pour l'architecture ; sinon on
    # renonce, Odoo sait imprimer sans lui (rendu dégradé des PDF).
    zyp_soft wkhtmltopdf || echo "wkhtmltopdf non installe (optionnel)."
  else
    echo -e "\n---- Already installed wkhtml ----"
  fi
fi

echo -e "\n---- SUSE dependency installation done ----"
