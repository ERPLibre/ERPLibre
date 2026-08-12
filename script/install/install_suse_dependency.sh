#!/usr/bin/env bash
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
#
# Dépendances système ERPLibre pour la famille SUSE (zypper). Équivalent SUSE
# de install_debian_dependency.sh et install_fedora_dependency.sh.
#
# Visé : openSUSE Tumbleweed, la seule distribution du catalogue dont qpdf
# (12.3.2) dépasse déjà le seuil de pikepdf 10 — la compilation de qpdf, une
# demi-heure sous émulation s390x, ne s'y déclenche pas.

. ./env_var.sh

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
ZYP_MIRRORS="https://mirrors.rit.edu/opensuse"
zp=tumbleweed
[ "$(uname -m)" = s390x ] && zp=ports/zsystems/tumbleweed
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
echo -e "\n---- Mise a jour complete (dup) ----"
${ZYP} dup ${ZYP_LIC} --allow-vendor-change || true

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
${ZYP_IN} gcc gcc-c++ make automake patch
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
${ZYP_IN} postgresql-server postgresql-contrib postgresql-server-devel
retVal=$?
if [[ ${retVal} -ne 0 ]]; then
  echo "zypper install postgresql installation error."
  exit 1
fi
# openSUSE n'initialise pas le cluster : le service le fait au 1er démarrage,
# mais seulement si le répertoire de données est vide.
sudo systemctl enable --now postgresql 2> /dev/null || true
# PostGIS : absent des dépôts Tumbleweed s390x. Optionnel, ne bloque pas.
${ZYP_SOFT} postgis || echo "PostGIS non installe (optionnel)."

echo -e "\n---- Creating the ERPLibre PostgreSQL User ----"
sudo su - postgres -c "createuser -s ${EL_USER}" 2> /dev/null || true

#--------------------------------------------------
# Dépendances de build (extensions Python, Odoo)
#--------------------------------------------------
echo -e "\n--- Installing suse dependency --"
# git-daemon : comme sur Fedora, « git daemon » n'est pas dans le paquet git de
# base. ERPLibre sert son manifeste par git://127.0.0.1:9418/ pendant
# « repo sync » — sans lui, « Connection refused » et synchro impossible.
${ZYP_SOFT} \
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
echo -e "\n---- Dependances pyenv (compilation Python) ----"
${ZYP_IN} \
  make gcc zlib-devel libbz2-devel readline-devel sqlite3-devel \
  libopenssl-devel tk-devel libffi-devel xz-devel patch findutils
retVal=$?
if [[ ${retVal} -ne 0 ]]; then
  echo "zypper pyenv dependencies installation error."
  exit 1
fi

# Dépendances selenium / bindings.
${ZYP_SOFT} \
  cairo-devel python3-devel pkg-config gobject-introspection-devel \
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
  ${ZYP_SOFT} nginx || echo "nginx: erreur (optionnel)."
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
    ${ZYP_SOFT} wkhtmltopdf || echo "wkhtmltopdf non installe (optionnel)."
  else
    echo -e "\n---- Already installed wkhtml ----"
  fi
fi

echo -e "\n---- SUSE dependency installation done ----"
