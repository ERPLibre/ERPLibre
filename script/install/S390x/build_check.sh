#!/usr/bin/env bash
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
#
# Fragment SOURCÉ par install_erplibre.sh, hors amd64 et arm64 (s390x en
# pratique), AVANT la création du venv d'outillage.
#
# Hors amd64 et arm64, PyPI n'a pas de roue pour lxml, cryptography ni
# pillow : pip les compile, et chacun exige ses en-têtes ou rustc. Vérifié
# AVANT le venv, dont pyenv peut compiler l'interpréteur pendant des minutes
# pour que pip échoue ensuite sur le premier en-tête absent.

manquants=""
cc_bin="$(command -v cc || command -v gcc)"
# libxml2 range ses en-têtes sous /usr/include/libxml2, hors du chemin
# par défaut du compilateur ; libxslt les inclut à son tour.
while read -r header paquet; do
  if [[ -z "${cc_bin}" ]] || ! printf '#include <%s>\n' "${header}" \
    | "${cc_bin}" -E -x c -I/usr/include/libxml2 - > /dev/null 2>&1; then
    manquants="${manquants} ${paquet}"
  fi
done << 'EOF'
libxml/xmlversion.h libxml2-dev
libxslt/xslt.h libxslt1-dev
jpeglib.h libjpeg-dev
openssl/ssl.h libssl-dev
EOF
command -v cargo > /dev/null 2>&1 || manquants="${manquants} rustc cargo"
command -v pkg-config > /dev/null 2>&1 || manquants="${manquants} pkg-config"
[[ -z "${cc_bin}" ]] && manquants="${manquants} build-essential"
if [[ -n "${manquants}" ]]; then
  echo "Sur $(uname -m), pip compile lxml, cryptography et pillow ;"
  echo "  il manque de quoi le faire. Sous Debian ou Ubuntu :"
  echo "    sudo apt-get install -y${manquants}"
  echo "  puis relancez : ./script/install/install_erplibre.sh"
  exit 1
fi
