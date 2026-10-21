#!/usr/bin/env bash
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
#
# Fragment SOURCÉ par install_erplibre.sh, sur s390x, AVANT la création du
# venv d'outillage.
#
# Sur s390x, PyPI n'a pas de wheel pour lxml, cryptography ni pillow : pip
# les compile, et chacun exige ses en-têtes ou rustc. Vérifié
# AVANT le venv, dont pyenv peut compiler l'interpréteur pendant des minutes
# pour que pip échoue ensuite sur le premier en-tête absent.

# Gestionnaire de paquets de l'hôte : les noms des paquets en dépendent.
if command -v apt-get > /dev/null 2>&1; then
  gestionnaire="apt-get"
elif command -v dnf > /dev/null 2>&1; then
  gestionnaire="dnf"
elif command -v zypper > /dev/null 2>&1; then
  gestionnaire="zypper"
else
  gestionnaire=""
fi

manquants=""
cc_bin="$(command -v cc || command -v gcc)"
# Chaque ligne : le prérequis, puis son paquet sous apt, dnf et zypper (une
# virgule sépare plusieurs paquets). Le prérequis est un en-tête, sauf
# « cmd: » pour une commande et « cc » pour le compilateur. libxml2 range ses
# en-têtes sous /usr/include/libxml2, hors du chemin par défaut du
# compilateur ; libxslt les inclut à son tour.
while read -r prerequis apt dnf zypper; do
  case "${prerequis}" in
    cc) [[ -n "${cc_bin}" ]] && continue ;;
    cmd:*) command -v "${prerequis#cmd:}" > /dev/null 2>&1 && continue ;;
    *)
      [[ -n "${cc_bin}" ]] && printf '#include <%s>\n' "${prerequis}" \
        | "${cc_bin}" -E -x c -I/usr/include/libxml2 - > /dev/null 2>&1 \
        && continue
      ;;
  esac
  case "${gestionnaire}" in
    dnf) paquet="${dnf}" ;;
    zypper) paquet="${zypper}" ;;
    *) paquet="${apt}" ;;
  esac
  manquants="${manquants} ${paquet//,/ }"
done << 'EOF'
libxml/xmlversion.h libxml2-dev libxml2-devel libxml2-devel
libxslt/xslt.h libxslt1-dev libxslt-devel libxslt-devel
jpeglib.h libjpeg-dev libjpeg-turbo-devel libjpeg8-devel
openssl/ssl.h libssl-dev openssl-devel libopenssl-devel
cmd:cargo rustc,cargo rust,cargo rust,cargo
cmd:pkg-config pkg-config pkgconf-pkg-config pkgconf-pkg-config
cc build-essential gcc,gcc-c++,make gcc,gcc-c++,make
EOF
if [[ -n "${manquants}" ]]; then
  echo "Sur $(uname -m), pip compile lxml, cryptography et pillow ;"
  echo "  il manque de quoi le faire :${manquants}"
  echo "  « make install_os » pose tout ce qu'il faut, puis relancez :"
  echo "    ./script/install/install_erplibre.sh"
  if [[ -n "${gestionnaire}" ]]; then
    echo "  Ou seulement ces paquets : sudo ${gestionnaire} install -y${manquants}"
  fi
  exit 1
fi
