#!/usr/bin/env bash
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
#
# Dépendances système ERPLibre pour Arch Linux (pacman). Réécrit pour les
# images cloud Arch : l'ancien script utilisait « yay » (helper AUR ABSENT
# d'une image cloud et qui refuse de tourner en root) et n'installait jamais
# « base-devel » -> pas de compilateur C -> échec de la compilation de Python
# par pyenv. On passe tout par pacman (dépôts officiels) ; l'AUR (wkhtmltopdf)
# est best-effort et ne bloque pas.

. ./env_var.sh

EL_USER=${USER}

# pacman résilient : --needed saute ce qui est déjà là, --noconfirm en non
# interactif.
PAC="sudo pacman -S --needed --noconfirm"
# Mise à jour COMPLÈTE obligatoire : Arch est en rolling release et NE SUPPORTE
# PAS les mises à jour partielles. Sur une image cloud dont la glibc est
# ancienne, un « pacman -S <paquet récent> » lie le binaire à une glibc plus
# récente que celle installée -> « /usr/bin/postgres: GLIBC_2.44 not found ».
# « -Syu » met à jour glibc (et tout le système) pour rester cohérent.
sudo pacman -Syu --noconfirm || true

#--------------------------------------------------
# Outils de compilation — CRITIQUE (build Python via pyenv, extensions Python)
# base-devel fournit gcc, make, patch, pkgconf, fakeroot, etc.
#--------------------------------------------------
echo -e "\n---- Groupe base-devel (compilateur C, make…) ----"
${PAC} base-devel
retVal=$?
if [[ $retVal -ne 0 ]]; then
  echo "pacman base-devel installation error."
  exit 1
fi

#--------------------------------------------------
# Dépendances de build pyenv (compilation de CPython) + outils de base
#--------------------------------------------------
echo -e "\n---- Dépendances pyenv (compilation Python) + outils ----"
${PAC} git wget curl openssl zlib xz tk bzip2 readline sqlite libffi
retVal=$?
if [[ $retVal -ne 0 ]]; then
  echo "pacman pyenv dependencies installation error."
  exit 1
fi

#--------------------------------------------------
# PostgreSQL (+ PostGIS) — Arch n'initialise pas le cluster automatiquement
#--------------------------------------------------
echo -e "\n---- Install PostgreSQL Server ----"
${PAC} postgresql
retVal=$?
if [[ $retVal -ne 0 ]]; then
  echo "pacman postgresql installation error."
  exit 1
fi
# Initialisation du cluster (chemin Arch : /var/lib/postgres/data).
if [ ! -f /var/lib/postgres/data/PG_VERSION ]; then
  echo -e "\n---- Initialisation du cluster PostgreSQL ----"
  sudo -u postgres initdb --locale=C.UTF-8 --encoding=UTF8 \
    -D /var/lib/postgres/data || true
fi
sudo systemctl enable --now postgresql 2>/dev/null || true
# PostGIS : optionnel (géospatial), ne bloque pas.
${PAC} postgis || echo "PostGIS non installé (optionnel)."

echo -e "\n---- Creating the ERPLibre PostgreSQL User ----"
sudo su - postgres -c "createuser -s ${EL_USER}" 2>/dev/null || true

#--------------------------------------------------
# Dépendances Odoo / ERPLibre (extensions Python, bindings)
#--------------------------------------------------
echo -e "\n---- Installing arch dependency ----"
# best-effort paquet par paquet : pacman refuse TOUTE la transaction si UN
# seul nom est inconnu (pas de --skip-unavailable). Ces deps ne sont pas
# critiques pour le build Python -> on ne bloque pas sur un nom absent.
for _pkg in libxslt libzip libldap libsasl cmake parallel swig portaudio \
  cups xmlsec freetds libev mariadb-libs shfmt; do
  ${PAC} "${_pkg}" || echo "  ${_pkg} : non installé (optionnel), on continue."
done
# libldap_r : Odoo/python-ldap cherche parfois libldap_r.so (supprimé des
# versions récentes d'OpenLDAP) -> lien vers libldap.so.
sudo ln -fs /usr/lib/libldap.so /usr/lib/libldap_r.so 2>/dev/null || true

#--------------------------------------------------
# Node.js + npm (rtlcss, less)
#--------------------------------------------------
echo -e "\n---- Installing nodeJS NPM and rtlcss ----"
${PAC} nodejs npm
retVal=$?
if [[ $retVal -ne 0 ]]; then
  echo "pacman nodejs installation error."
  exit 1
fi
sudo npm install -g rtlcss less || echo "npm rtlcss/less: erreur (optionnel)."

echo -e "\n---- Test tool ----"
npm install || echo "npm install (prettier/plugin-xml): erreur (optionnel)."

# Pour erplibre_devops.
${PAC} sshpass || echo "sshpass non installé (optionnel)."

#--------------------------------------------------
# nginx (optionnel)
#--------------------------------------------------
if [ "${EL_INSTALL_NGINX}" = "True" ]; then
  echo -e "\n---- Installing nginx ----"
  ${PAC} nginx || echo "nginx: erreur (optionnel)."
fi

#--------------------------------------------------
# wkhtmltopdf (optionnel) — uniquement dans l'AUR sur Arch (pas de paquet
# officiel). Sur une image cloud sans helper AUR, on saute proprement.
#--------------------------------------------------
if [ "${EL_INSTALL_WKHTMLTOPDF}" = "True" ]; then
  if ! command -v wkhtmltopdf >/dev/null 2>&1; then
    echo "wkhtmltopdf : disponible seulement via l'AUR sur Arch, ignoré"
    echo "  (installez-le manuellement avec un helper AUR si nécessaire)."
  else
    echo -e "\n---- Already installed wkhtml ----"
  fi
fi

echo -e "\n---- Arch Linux dependency installation done ----"
