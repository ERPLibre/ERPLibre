#!/usr/bin/env bash
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
#
# Dépendances système ERPLibre pour NixOS.
#
# Les quatre autres scripts de distribution POSENT des paquets. Celui-ci n'en
# pose aucun : il dépose une déclaration et demande au système de s'y
# conformer. C'est la seule façon dont une dépendance dure sur NixOS — ce qui
# est installé à la main vit hors de la configuration et disparaît à la
# reconstruction suivante.
#
# Idempotent : relancé, il réécrit le module, n'ajoute pas deux fois l'import,
# et « nixos-rebuild switch » ne fait rien s'il n'y a rien à changer.
set -e

. ./env_var.sh

EL_USER=${USER}
# Le répertoire du service, pris du checkout QUI POSE le module : « make
# install_os » tourne à la racine du dépôt, et c'est ce dépôt-là que le
# service doit lancer. Deviner « /home/$USER/git/erplibre » se tromperait sur
# une installation de production, qui vit sous /opt.
EL_DIR=${EL_DIR:-${PWD}}
# Les réglages régionaux que le DÉPLOIEMENT a demandés, lus là où cloud-init
# garde ce qu'il a reçu. Vides quand rien ne les a demandés — une NixOS que
# l'on avait déjà —, et le module laisse alors les réglages en place.
EL_CLOUD_CFG=/var/lib/cloud/instance/cloud-config.txt
lire_seed() {
  sudo grep -m1 -E "^${1}: " "${EL_CLOUD_CFG}" 2>/dev/null |
    cut -d" " -f2- | tr -d "\r" || true
}
# Le faisceau que cloud-init a bâti, s'il l'a fait : vide sur une machine
# sans cache, et le module n'y déclare alors aucune variable — y pointer
# couperait TLS partout.
EL_CA_BUNDLE=/var/lib/erplibre/ca-bundle.crt
[ -r "${EL_CA_BUNDLE}" ] || EL_CA_BUNDLE=""
EL_LOCALE=${EL_LOCALE:-$(lire_seed locale)}
EL_TZ=${EL_TZ:-$(lire_seed timezone)}
# « 3.12.10 » donne « python312 », le nom du paquet nixpkgs. Les deux versions
# du dépôt sont déclarées : celle d'Odoo et celle de l'outillage. Le second est
# VIDE quand elles coïncident, un même paquet nommé deux fois entrant en
# collision dans le profil.
el_nix_python_pkg() {
  local v
  v="$(xargs < "$1" 2> /dev/null)"
  [ -n "${v}" ] || return 0
  echo "python$(echo "${v}" | cut -d. -f1)$(echo "${v}" | cut -d. -f2)"
}
EL_PY_ODOO_PKG="$(el_nix_python_pkg .python-odoo-version)"
EL_PY_ODOO_PKG="${EL_PY_ODOO_PKG:-python312}"
EL_PY_TOOLS_PKG="$(el_nix_python_pkg conf/python-erplibre-version)"
[ "${EL_PY_TOOLS_PKG}" = "${EL_PY_ODOO_PKG}" ] && EL_PY_TOOLS_PKG=""

MODULE_SRC="conf/nixos/erplibre.nix"
MODULE_DST="/etc/nixos/erplibre.nix"
CONFIG="/etc/nixos/configuration.nix"

if [ ! -f /etc/os-release ] || ! grep -q '^ID=nixos' /etc/os-release; then
  echo "Ce script ne vaut que pour NixOS."
  exit 1
fi

if [ ! -f "${MODULE_SRC}" ]; then
  echo "Module absent : ${MODULE_SRC} (lancer depuis la racine du dépôt)."
  exit 1
fi

echo -e "\n---- Module ERPLibre pour NixOS ----"
# Le nom du compte est substitué comme le user-data cloud-init l'est : le
# module déclare un rôle PostgreSQL, et un rôle porte un nom.
sed -e "s/@EL_USER@/${EL_USER}/g" -e "s#@EL_DIR@#${EL_DIR}#g" \
  -e "s/@EL_LOCALE@/${EL_LOCALE}/g" -e "s#@EL_TZ@#${EL_TZ}#g" \
  -e "s#@EL_CA_BUNDLE@#${EL_CA_BUNDLE}#g" \
  -e "s/@EL_PY_ODOO_PKG@/${EL_PY_ODOO_PKG}/g" \
  -e "s/@EL_PY_TOOLS_PKG@/${EL_PY_TOOLS_PKG}/g" \
  "${MODULE_SRC}" | sudo tee "${MODULE_DST}" > /dev/null
echo "  posé : ${MODULE_DST} (compte ${EL_USER}, dépôt ${EL_DIR})"
echo "  autorité du cache : ${EL_CA_BUNDLE:-aucune}"
echo "  Python : ${EL_PY_ODOO_PKG} (Odoo)${EL_PY_TOOLS_PKG:+, ${EL_PY_TOOLS_PKG} (outillage)}"
echo "  régional : locale « ${EL_LOCALE:-non demandée} »," \
  "fuseau « ${EL_TZ:-non demandé} »"

if [ ! -f "${CONFIG}" ]; then
  echo "Configuration introuvable : ${CONFIG}"
  exit 1
fi

# L'import, une fois. Sans lui le module est un fichier mort : NixOS ne lit
# que ce que la configuration importe.
if grep -q "erplibre.nix" "${CONFIG}"; then
  echo "  import déjà présent dans ${CONFIG}"
else
  sudo sed -i '0,/imports *= *\[/s//imports = [\n      .\/erplibre.nix/' "${CONFIG}"
  if grep -q "erplibre.nix" "${CONFIG}"; then
    echo "  import ajouté à ${CONFIG}"
  else
    echo "Aucun bloc « imports = [ » dans ${CONFIG} : ajoutez-y"
    echo "  ./erplibre.nix"
    exit 1
  fi
fi

echo -e "\n---- nixos-rebuild switch ----"
# La reconstruction télécharge et bâtit : elle est LONGUE au premier passage,
# et c'est elle qui pose PostgreSQL, node, le compilateur, nix-ld et envfs.
#
# Son code de retour n'est PAS le verdict. « switch-to-configuration » rend 4
# quand une unité n'a pas pu redémarrer, alors que le système est bel et bien
# activé : sur une VM cloud-init, cloud-config est un service à un coup, et
# toute reconstruction ultérieure le trouve mort. Prendre ce 4 pour un échec
# ferait échouer chaque redéploiement d'une machine déjà installée. C'est la
# vérification ci-dessous qui tranche, sur l'état du système.
if sudo nixos-rebuild switch; then
  echo "  reconstruction appliquée"
else
  echo "  ⚠ nixos-rebuild rend $? : une unité n'a pas redémarré."
  echo "    Le système peut être activé quand même — vérification ci-dessous."
fi

echo -e "\n---- Vérification ----"
manque=0
# La version voulue vient du dépôt, pas d'une valeur écrite ici : le module
# déclare python312 parce que .python-odoo-version dit 3.12.x, et les deux
# doivent se répondre. « 3.12.10 » -> « 3.12 », qui est ce que
# lib_python_provider.sh cherche en /usr/bin.
PY_WANT="$(cat .python-odoo-version 2> /dev/null | xargs)"
PY_MM="${PY_WANT%.*}"
for chemin in /bin/bash /usr/bin/env "/usr/bin/python${PY_MM}"; do
  if [ -e "${chemin}" ]; then
    echo "  ${chemin}"
  else
    echo "  MANQUE : ${chemin}"
    manque=1
  fi
done
if ! command -v psql > /dev/null 2>&1; then
  echo "  MANQUE : psql"
  manque=1
fi
if [ "${manque}" -ne 0 ]; then
  # Sans /bin/bash, la moindre cible make échoue avant sa première ligne :
  # continuer ferait échouer l'installation une heure plus tard, ailleurs.
  echo "Le système n'est pas conforme au module : voir services.envfs.enable."
  exit 1
fi
echo "  système conforme au module ERPLibre."
