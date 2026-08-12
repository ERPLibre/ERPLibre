#!/usr/bin/env bash

. ./env_var.sh
. ./script/install/lib_qpdf.sh

EL_USER=${USER}
#EL_INSTALL_WKHTMLTOPDF="True"

# apt-get qui ATTEND le verrou (jusqu'à 10 min) : sur une image cloud fraîche,
# cloud-init / unattended-upgrades tiennent souvent le verrou apt au 1er boot
# (« Could not get lock » -> échec de l'install). DPkg::Lock::Timeout patiente.
APT_GET="sudo apt-get -o DPkg::Lock::Timeout=600"

##
###  WKHTMLTOPDF download links
## === Ubuntu Focal x64 === (for other distributions please replace these two links,
## in order to have correct version of wkhtmltopdf installed, for a danger note refer to
## https://github.com/odoo/odoo/wiki/Wkhtmltopdf ):
# Ubuntu 20.04
UBUNTU_VERSION=$(lsb_release -rs)
DEBIAN_VERSION=$(lsb_release -cs)
OS=$(lsb_release -si)

# Ubuntu 18.04, 20.04 et 22.04 ne sont plus supportées, sur AUCUNE
# architecture. Le mur le plus net est pikepdf, qui réclame qpdf >= 12.2,
# lui-même en C++20 : focal livre GCC 9 et ne publie même pas de g++-10 pour
# s390x. S'y ajoutaient Python 3.8 à l'amorçage, node 10, cargo 0.67 et
# OpenSSL 1.1.1 — chacun avait son contournement, l'accumulation non.
#
# Le refus est ICI, avant tout le reste : ce script tourne aussi sur une
# machine existante, pas seulement sur une VM fraîchement déployée.
if [[ "${OS}" == "Ubuntu" ]]; then
  case "${UBUNTU_VERSION}" in
    18.04 | 20.04 | 22.04)
      echo "Ubuntu ${UBUNTU_VERSION} n'est plus supporte par ERPLibre :"
      echo "  sa chaine d'outils est trop ancienne (pikepdf exige qpdf 12.2,"
      echo "  compile en C++20, quand cette version livre GCC 9)."
      echo "  Utilisez Ubuntu 24.04, 25.10 ou 26.04."
      exit 1
      ;;
  esac
fi

if [[ "${OS}" == "Ubuntu" ]]; then
  # wkhtmltopdf ne publie pas de build par version d'Ubuntu ; le .deb
  # « jammy » est le plus récent et fonctionne de 24.04 à 26.04 et au-delà.
  WKHTMLTOX_X64=https://github.com/wkhtmltopdf/packaging/releases/download/0.12.6.1-3/wkhtmltox_0.12.6.1-3.jammy_amd64.deb
elif [[ "${OS}" == "Linuxmint" ]]; then
  # Sans « else », toute Mint autre que 22.3 laissait WKHTMLTOX_X64 VIDE, et
  # gdebi etait appele sans fichier. Mint 22.x repose sur noble : meme .deb.
  WKHTMLTOX_X64=https://github.com/wkhtmltopdf/packaging/releases/download/0.12.6.1-3/wkhtmltox_0.12.6.1-3.jammy_amd64.deb
elif [[ "${OS}" == "Debian" ]]; then
  if [ "bullseye" == "${DEBIAN_VERSION}" ]; then
    WKHTMLTOX_X64=https://github.com/wkhtmltopdf/packaging/releases/download/0.12.6.1-3/wkhtmltox_0.12.6.1-3.bullseye_amd64.deb
  else
    # bookworm (12), trixie (13) et au-delà : wkhtmltopdf ne publie pas de
    # build au-delà de « bookworm » -> on prend bookworm (le plus récent).
    # Le build « bullseye » (Debian 11) échouait à s'installer sur trixie
    # (gdebi : dépendances incompatibles).
    WKHTMLTOX_X64=https://github.com/wkhtmltopdf/packaging/releases/download/0.12.6.1-3/wkhtmltox_0.12.6.1-3.bookworm_amd64.deb
  fi
elif [[ "${OS}" == *"Ubuntu"* ]]; then
  echo "Your version of Ubuntu is not supported, only support 24.04, 25.10 and 26.04"
  WKHTMLTOX_X64=https://github.com/wkhtmltopdf/packaging/releases/download/0.12.6.1-3/wkhtmltox_0.12.6.1-3.jammy_amd64.deb
else
  echo "Your version of Ubuntu is not supported, only support 24.04, 25.10 and 26.04"
  exit 1
fi

#--------------------------------------------------
# Mainframe 390x
#--------------------------------------------------
if [ "$(uname -m)" = "s390x" ]; then
  echo "Arch s390x detected"
  # Sur une VM fraîche, l'index apt peut être vide : « apt install » échouerait
  # alors sur TOUT le lot, et l'absence d'un seul paquet ne se voit que bien
  # plus loin, sous la forme d'une commande introuvable.
  ${APT_GET} update
  # « ${APT_GET} » et non « sudo apt » : au 1er boot d'une image cloud,
  # cloud-init tient le verrou apt, et un « apt install » nu échoue AUSSITÔT.
  # Ces trois lots étaient les seuls du script à contourner le wrapper, et
  # aucun ne vérifiait son résultat : libqpdf-dev manquait sans un mot, et
  # l'échec ne se voyait qu'une heure plus tard, à la compilation de pikepdf.
  # Un nom de paquet CHANGE d'une version d'Ubuntu à l'autre : GeographicLib
  # s'appelle « libgeographic-dev » sur 20.04 et 22.04, « libgeographiclib-dev »
  # depuis 24.04. Le nom récent existe pourtant dans la base apt des anciennes,
  # SANS version installable — apt refuse alors le lot ENTIER, emportant les
  # quatorze autres paquets. On demande donc à apt lui-même quel nom est
  # réellement installable, seule autorité sur la question.
  apt_pick() {
    for candidate in "$@"; do
      if apt-get install -s -qq "${candidate}" > /dev/null 2>&1; then
        echo "${candidate}"
        return 0
      fi
    done
    echo "$1"
  }
  # Vrai si dpkg considère le paquet installé et configuré.
  apt_is_installed() {
    [ "$(dpkg-query -W -f='${db:Status-Status}' "$1" 2>/dev/null)" = "installed" ]
  }
  # Le lot d'abord, pour la vitesse. S'il échoue, on reprend paquet par paquet
  # afin de NOMMER le fautif : sinon un seul nom obsolète masque les autres et
  # le message ne dit pas lequel corriger.
  apt_install_batch() {
    if ${APT_GET} install "$@" -y; then
      return 0
    fi
    # Un dépaquetage raté laisse dpkg à moitié configuré, et TOUT apt suivant
    # rend « Unmet dependencies » — y compris pour des paquets déjà installés.
    # Sans cette réparation, la boucle ci-dessous accusait les quinze paquets
    # à cause d'un seul, et l'installation s'arrêtait sur un paquet présent.
    echo "Lot apt en echec : tentative de reparation dpkg..."
    sudo dpkg --configure -a || true
    ${APT_GET} --fix-broken install -y || true
    if ${APT_GET} install "$@" -y; then
      echo "Reparation reussie."
      return 0
    fi
    echo "Reprise paquet par paquet pour identifier le fautif..."
    df -h / | sed 's/^/  disque: /'
    APT_FAILED=""
    for one in "$@"; do
      ${APT_GET} install "${one}" -y && continue
      # L'échec peut n'être qu'un contrecoup de l'état global : on ne l'impute
      # au paquet que si dpkg confirme qu'il n'est PAS installé.
      apt_is_installed "${one}" || APT_FAILED="${APT_FAILED} ${one}"
    done
    [ -z "${APT_FAILED}" ]
  }
  APT_FAILED=""
  GEO_DEV="$(apt_pick libgeographiclib-dev libgeographic-dev)"
  # manifold3d (via to-3mf) et pymupdf n'ont pas de roue s390x : ils se
  # compilent, d'où tbb, cmake et ninja. Un seul lot, une seule reprise.
  apt_install_batch rust-all libqpdf-dev libgeos-dev libproj-dev proj-bin \
    proj-data "${GEO_DEV}" freetds-dev freetds-bin libkrb5-dev libssl-dev \
    pkg-config build-essential zlib1g-dev libjpeg-dev libtbb-dev cmake \
    ninja-build
  if [[ -n "${APT_FAILED}" ]]; then
    # Seul un paquet dont dépend la SUITE immédiate est bloquant. Les autres
    # servent des modules Odoo optionnels : les rendre fatals immobiliserait
    # toute l'installation pour un module que personne n'utilise ici.
    echo "Paquets s390x non installables :${APT_FAILED}"
    for essential in build-essential pkg-config libssl-dev zlib1g-dev \
      libjpeg-dev cmake; do
      case " ${APT_FAILED} " in
        *" ${essential} "*)
          echo "apt-get s390x : '${essential}' est indispensable, arret."
          exit 1
          ;;
      esac
    done
    echo "Aucun n'est indispensable a la compilation : on continue."
  fi
  # pymupdf non plus n'a pas de roue s390x : il compile MuPDF, dont le
  # générateur de liaisons charge « libclang.so » par son nom nu, via ctypes.
  # La roue PyPI libclang, qui embarque cette bibliothèque, n'existe pas ici.
  # Le paquet de la distribution la fournit bien dans le chemin de l'éditeur de
  # liens, mais sous un nom versionné : il ne manque que le lien non versionné.
  ${APT_GET} install libclang-dev -y
  CLANG_LIB_DIR="/usr/lib/s390x-linux-gnu"
  if [ ! -e "${CLANG_LIB_DIR}/libclang.so" ]; then
    CLANG_SO="$(ls -1 ${CLANG_LIB_DIR}/libclang-[0-9]*.so 2>/dev/null | sort -V | tail -1)"
    if [ -n "${CLANG_SO}" ]; then
      sudo ln -s "${CLANG_SO}" "${CLANG_LIB_DIR}/libclang.so"
      sudo ldconfig
      echo "libclang.so -> ${CLANG_SO}"
    else
      echo "Attention : libclang introuvable, la compilation de pymupdf va echouer."
    fi
  fi
  # pikepdf se lie a qpdf, dont il exige 12.2.0 au minimum. Ubuntu 24.04 en
  # livre 11.9.0 ; 25.10 et 26.04 passent, d'ou le partage observe. Le detail
  # -- seuil, version batie, chemin d'installation -- est dans lib_qpdf.sh,
  # partage avec les scripts dnf et zypper qui butaient sur le meme mur.
  el_qpdf_ensure
  # cryptography ne publie aucune roue s390x : elle se compile, et son
  # Cargo.lock est en version 4, que seul cargo >= 1.78 sait lire. Ubuntu 24.04
  # livre 1.75 et s'arrête sur « lock file version 4 requires
  # -Znext-lockfile-bump » ; 25.10 et au-delà passent. On complète alors par
  # rustup, en exposant la chaîne hors du shell de connexion : les étapes
  # suivantes sont des processus distincts, qui ne liront ni ~/.bashrc ni
  # ~/.cargo/env.
  CARGO_MIN_MINOR=78
  cargo_ver="$(cargo --version 2>/dev/null | awk '{print $2}')"
  cargo_major="${cargo_ver%%.*}"
  cargo_rest="${cargo_ver#*.}"
  cargo_minor="${cargo_rest%%.*}"
  cargo_ok=0
  if [[ "${cargo_major}" =~ ^[0-9]+$ && "${cargo_minor}" =~ ^[0-9]+$ ]]; then
    if [[ ${cargo_major} -gt 1 ]] ||
      [[ ${cargo_major} -eq 1 && ${cargo_minor} -ge ${CARGO_MIN_MINOR} ]]; then
      cargo_ok=1
    fi
  fi
  if [ "${cargo_ok}" -ne 1 ]; then
    echo "cargo trop ancien ($(cargo --version 2>/dev/null || echo absent)) pour cryptography : installation via rustup."
    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \
      | sh -s -- -y --profile minimal --default-toolchain stable
    for bin in cargo rustc; do
      if [ -x "${HOME}/.cargo/bin/${bin}" ]; then
        sudo ln -sf "${HOME}/.cargo/bin/${bin}" "/usr/local/bin/${bin}"
      fi
    done
    echo "cargo retenu : $(PATH=/usr/local/bin:$PATH cargo --version 2>/dev/null || echo absent)"
  fi
fi

#--------------------------------------------------
# Update Server
#--------------------------------------------------
echo -e "\n---- Update Server ----"


#--------------------------------------------------
# Install PostgreSQL Server
#--------------------------------------------------
echo -e "\n---- Install PostgreSQL Server ----"
${APT_GET} install postgresql postgresql-contrib libpq-dev -y
retVal=$?
if [[ $retVal -ne 0 ]]; then
  echo "apt-get install postgresql installation error."
  exit 1
fi
# PostGIS : optionnel (géospatial). Le nom du paquet « postgis » n'existe pas
# sur toutes les versions (Ubuntu 24.04) -> best-effort, ne bloque pas.
${APT_GET} install postgis -y \
  || ${APT_GET} install postgresql-postgis -y \
  || echo "PostGIS non installé (optionnel)."

echo -e "\n---- Creating the ERPLibre PostgreSQL User  ----"
sudo su - postgres -c "createuser -s ${EL_USER}" 2>/dev/null || true

#--------------------------------------------------
# Install Dependencies
#--------------------------------------------------
echo -e "\n--- Installing debian dependency --"
${APT_GET} install git build-essential wget libxslt-dev libzip-dev libldap2-dev libsasl2-dev gdebi-core libffi-dev libbz2-dev parallel pysassc swig cmake portaudio19-dev libcups2-dev xmlsec1 -y
retVal=$?
if [[ $retVal -ne 0 ]]; then
  echo "apt-get debian tool installation error."
  exit 1
fi
# shfmt : ABSENT des dépôts Ubuntu < 22.04. Il était dans le lot critique
# ci-dessus -> un seul paquet introuvable faisait échouer TOUT l'apt-get
# (donc pas de build-essential/gcc -> pyenv ne pouvait plus compiler Python).
# C'est un simple formateur shell (dev), non requis pour exécuter ERPLibre :
# on l'installe SÉPARÉMENT et en best-effort (jamais fatal).
${APT_GET} install shfmt -y \
  || echo "shfmt indisponible dans les dépôts (Ubuntu < 22.04 ?) — ignoré."
${APT_GET} install libmariadbd-dev freetds-dev -y
retVal=$?
if [[ $retVal -ne 0 ]]; then
  echo "apt-get libmariadb installation error."
  exit 1
fi
# Dependencies for pyenv
${APT_GET} install make libssl-dev zlib1g-dev libreadline-dev libsqlite3-dev curl llvm libncurses5-dev libncursesw5-dev xz-utils tk-dev liblzma-dev -y
retVal=$?
if [[ $retVal -ne 0 ]]; then
  echo "apt-get pyenv dependencies installation error."
  exit 1
fi
# Dependencies for selenium
${APT_GET} install libcairo2-dev python3-dev pkg-config libxt-dev libgirepository1.0-dev -y
retVal=$?
if [[ $retVal -ne 0 ]]; then
  echo "apt-get selenium dependencies installation error."
  exit 1
fi

echo -e "\n---- Installing nodeJS NPM and rtlcss for LTR support ----"
${APT_GET} update
${APT_GET} install -y ca-certificates curl gnupg
sudo mkdir -p /etc/apt/keyrings
curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | sudo gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg

# Node 22+ required by @capacitor/cli v8.x (mobile app dependency)
NODE_MAJOR=22

# NodeSource ne publie que amd64, arm64 et armhf : vérifié, binary-s390x
# répond 404. Ajouter le dépôt sur une autre architecture n'apporte rien et
# fait échouer « apt update » sur un index introuvable. La distribution
# fournit alors nodejs elle-même — Ubuntu 26.04 s390x livre la 22.22.1, ce qui
# convient.
NODE_ARCH="$(dpkg --print-architecture)"
case "${NODE_ARCH}" in
  amd64 | arm64 | armhf)
    echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_$NODE_MAJOR.x nodistro main" | sudo tee /etc/apt/sources.list.d/nodesource.list
    ${APT_GET} update
    ;;
  *)
    echo "NodeSource ne publie pas pour ${NODE_ARCH} : nodejs vient de la distribution."
    sudo rm -f /etc/apt/sources.list.d/nodesource.list
    ${APT_GET} update
    # Le paquet « nodejs » de NodeSource embarque npm ; celui d'Ubuntu NON —
    # vérifié : /usr/bin/npm est absent du paquet sur jammy, noble et questing.
    # Sans cette ligne, tout ce qui suit tombe sur « npm: command not found ».
    NODE_PKG="nodejs npm"
    ;;
esac
${APT_GET} install ${NODE_PKG:-nodejs} -y

node_major() {
  node --version 2>/dev/null | sed -n 's/^v\([0-9]*\).*/\1/p'
}

# Le node de la distribution suffit sur les versions récentes, pas sur les
# anciennes : focal livre la 10, jammy la 12, alors que « less » exige node 18
# et « rtlcss » node 12. Là où NodeSource n'a rien à offrir, l'archive
# officielle de nodejs.org prend le relais — elle publie bien linux-s390x,
# vérifié dans son index. Rien n'est téléchargé si la distribution suffit.
NODE_MIN=18
node_have="$(node_major)"
if [[ -n "${NODE_PKG}" && ! (${node_have:-0} -ge ${NODE_MIN}) ]]; then
  echo "node $(node --version 2>/dev/null || echo absent) trop ancien (< ${NODE_MIN}) : archive officielle Node ${NODE_MAJOR}."
  case "${NODE_ARCH}" in
    # Node 22 publie linux-{x64,arm64,armv7l,ppc64le,s390x} — vérifié dans son
    # index. Pas de riscv64 : cette architecture garde le node de sa
    # distribution, et le message plus bas le dit.
    s390x) NODE_DIST_ARCH=s390x ;;
    ppc64el) NODE_DIST_ARCH=ppc64le ;;
    *) NODE_DIST_ARCH="" ;;
  esac
  NODE_VER="$(curl -fsSL --max-time 60 https://nodejs.org/dist/index.json |
    grep -o "\"version\":\"v${NODE_MAJOR}\.[0-9.]*\"" | head -1 | cut -d'"' -f4)"
  if [[ -z "${NODE_DIST_ARCH}" || -z "${NODE_VER}" ]]; then
    echo "Pas d'archive Node officielle pour ${NODE_ARCH} : on garde celle de la distribution."
  else
    NODE_TGZ="node-${NODE_VER}-linux-${NODE_DIST_ARCH}.tar.xz"
    NODE_TMP="$(mktemp -d)"
    if curl -fsSL --max-time 600 -o "${NODE_TMP}/${NODE_TGZ}" \
      "https://nodejs.org/dist/${NODE_VER}/${NODE_TGZ}" &&
      curl -fsSL --max-time 120 -o "${NODE_TMP}/SHASUMS256.txt" \
        "https://nodejs.org/dist/${NODE_VER}/SHASUMS256.txt" &&
      (cd "${NODE_TMP}" && grep " ${NODE_TGZ}\$" SHASUMS256.txt | sha256sum -c -); then
      # Un « npm install npm@latest -g » antérieur a pu déposer un npm
      # incompatible ici : l'archive écrase les fichiers mais ne supprime pas
      # ceux qu'elle n'a pas, ce qui laisserait un mélange des deux versions.
      sudo rm -rf /usr/local/lib/node_modules/npm
      sudo tar -xJf "${NODE_TMP}/${NODE_TGZ}" -C /usr/local --strip-components=1
      hash -r
      echo "node $(node --version) / npm $(npm --version) installés dans /usr/local."
    else
      echo "Telechargement de Node ${NODE_VER} impossible : on garde celle de la distribution."
    fi
    rm -rf "${NODE_TMP}"
  fi
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "npm est introuvable apres l'installation de nodejs (${NODE_ARCH})."
  exit 1
fi

# « npm@latest » dépasse régulièrement le node en place : sur Ubuntu 26.04
# s390x, npm 12 exige node ^22.22.2 alors que l'archive livre la 22.22.1 — un
# correctif d'écart, et EBADENGINE. Pire sur un node ancien : npm 6 n'applique
# PAS « engines », il se contente d'avertir, installe npm 12 par-dessus et le
# rend inutilisable (« Cannot find module 'node:path' », absent avant node
# 14.18). Le npm livré AVEC node est compatible par construction ; cette mise à
# niveau n'est qu'un confort, on ne la tente que si node est assez récent.
if [[ "$(node_major)" =~ ^[0-9]+$ && $(node_major) -ge ${NODE_MAJOR} ]]; then
  sudo npm install npm@latest -g
  retVal=$?
  if [[ $retVal -ne 0 ]]; then
    echo "Avertissement : npm n'a pas pu être mis à niveau, on garde $(npm --version)."
  fi
else
  echo "npm $(npm --version) conservé : node $(node --version) est en deçà de ${NODE_MAJOR}."
fi
sudo npm install -g rtlcss
retVal=$?
if [[ $retVal -ne 0 ]]; then
  echo "npm install rtlcss installation error."
  exit 1
fi
sudo npm install -g less
retVal=$?
if [[ $retVal -ne 0 ]]; then
  echo "npm install less installation error."
  exit 1
fi

echo -e "\n---- Test tool ----"
npm install
retVal=$?
if [[ $retVal -ne 0 ]]; then
  echo "npm install prettier + plugin-xml installation error."
  exit 1
fi

sudo ln -fs /usr/local/bin/lessc /usr/bin/lessc

if [ ${EL_INSTALL_NGINX} = "True" ]; then
  echo -e "\n---- Installing nginx ----"
  sudo apt install nginx -y
  retVal=$?
  if [[ $retVal -ne 0 ]]; then
    echo "apt install nginx installation error."
    exit 1
  fi
fi

#--------------------------------------------------
# Install Wkhtmltopdf if needed
#--------------------------------------------------
if [ "$(uname -m)" != "x86_64" ]; then
  # WKHTMLTOX_X64 pointe vers un .deb amd64 : sur toute autre architecture
  # (s390x, arm64/aarch64…) gdebi échouerait. On saute proprement plutôt que
  # d'avorter tout l'install (wkhtmltopdf est optionnel).
  echo "wkhtmltopdf : pas de build pour $(uname -m), ignoré (optionnel)."
elif [ ${EL_INSTALL_WKHTMLTOPDF} = "True" ]; then
  echo -e "\n---- Installing wkhtml ----"
  INSTALLED=$(dpkg -s wkhtmltox | grep installed)
  if [ "" == "${INSTALLED}" ]; then
    echo -e "\n---- Install wkhtml and place shortcuts on correct place ----"
    _url=${WKHTMLTOX_X64}
    if [ -z "${_url}" ]; then
      # Aucune URL (version non mappée) : wkhtmltopdf est OPTIONNEL, on saute
      # proprement plutôt que d'appeler gdebi sans fichier (« Usage: gdebi »).
      echo "wkhtmltopdf : aucune URL pour cette version, ignoré (optionnel)."
    else
      sudo wget ${_url}
      sudo gdebi --n $(basename ${_url})
      retVal=$?
      if [[ $retVal -ne 0 ]]; then
        # wkhtmltopdf est OPTIONNEL (rapports PDF). NON bloquant : sur Debian
        # 13 (trixie) le .deb dépendait de libssl1.1 (absent) et « exit 1 »
        # faisait échouer TOUT install_os -> Odoo jamais installé. On avertit
        # et on continue (comme Arch qui poursuit sans wkhtmltopdf).
        echo "wkhtmltopdf : installation échouée, ignoré (optionnel — pas de PDF)."
      else
        sudo ln -fs /usr/local/bin/wkhtmltopdf /usr/bin
        sudo ln -fs /usr/local/bin/wkhtmltoimage /usr/bin
      fi
    fi
  else
    echo -e "\n---- Already installed wkhtml ----"
  fi
else
  echo "Wkhtmltopdf isn't installed due to the choice of the user!"
fi
