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

# « --non-interactive » vaut le -y des autres gestionnaires. Sans
# « --auto-agree-with-licenses », zypper s'arrête sur une licence à accepter et
# attend une réponse que personne ne donnera dans une installation détachée.
ZYP="sudo zypper --non-interactive --auto-agree-with-licenses"
# Certains paquets n'existent pas sous le même nom d'une version à l'autre.
# « --ignore-unknown » saute l'inconnu au lieu de faire échouer tout le lot,
# comme « --skip-unavailable » côté dnf.
ZYP_SOFT="${ZYP} install --ignore-unknown"

echo -e "\n---- Rafraichissement des depots ----"
# Tumbleweed est ROLLING : installer sans rafraîchir mène à des paquets
# introuvables (l'index local pointe des versions déjà retirées du miroir).
sudo zypper --non-interactive refresh || true

#--------------------------------------------------
# Outils de compilation (build Python via pyenv, extensions Python)
#--------------------------------------------------
echo -e "\n---- Motif outils de developpement ----"
# Chez SUSE ce sont des « patterns », l'équivalent des groupes dnf. Repli
# explicite si le motif n'existe pas sous ce nom.
${ZYP} install -t pattern devel_basis \
  || ${ZYP_SOFT} gcc gcc-c++ make automake patch

#--------------------------------------------------
# PostgreSQL
#--------------------------------------------------
echo -e "\n---- Install PostgreSQL Server ----"
${ZYP} install postgresql-server postgresql-contrib postgresql-server-devel
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
${ZYP} install \
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
  if ${ZYP} install "${pkg}" "${pkg/nodejs/npm}" 2> /dev/null; then
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
