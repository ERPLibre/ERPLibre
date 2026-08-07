#!/usr/bin/env bash

. ./env_var.sh

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
if [[ "${OS}" == "Ubuntu" ]]; then
  if [ "20.04" == "${UBUNTU_VERSION}" ]; then
    WKHTMLTOX_X64=https://github.com/wkhtmltopdf/packaging/releases/download/0.12.6-1/wkhtmltox_0.12.6-1.focal_amd64.deb
  elif [ "18.04" == "${UBUNTU_VERSION}" ]; then
    WKHTMLTOX_X64=https://github.com/wkhtmltopdf/packaging/releases/download/0.12.6-1/wkhtmltox_0.12.6-1.bionic_amd64.deb
  else
    # 22.04+ (jusqu'à 26.04 et au-delà) : wkhtmltopdf ne publie pas de build
    # par version ; le .deb « jammy » est le plus récent et fonctionne. Un
    # « else » (au lieu d'énumérer les versions) évite une URL VIDE sur une
    # version récente (26.04) -> gdebi appelé sans fichier -> échec.
    WKHTMLTOX_X64=https://github.com/wkhtmltopdf/packaging/releases/download/0.12.6.1-3/wkhtmltox_0.12.6.1-3.jammy_amd64.deb
  fi
elif [[ "${OS}" == "Linuxmint" ]]; then
  if [ "22.3" == "${UBUNTU_VERSION}" ]; then
    WKHTMLTOX_X64=https://github.com/wkhtmltopdf/packaging/releases/download/0.12.6.1-3/wkhtmltox_0.12.6.1-3.jammy_amd64.deb
  fi
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
  echo "Your version of Ubuntu is not supported, only support 18.04, 20.04 and 22.04"
  WKHTMLTOX_X64=https://github.com/wkhtmltopdf/packaging/releases/download/0.12.6.1-3/wkhtmltox_0.12.6.1-3.jammy_amd64.deb
else
  echo "Your version of Ubuntu is not supported, only support 18.04, 20.04 and 22.04"
  exit 1
fi

#--------------------------------------------------
# Mainframe 390x
#--------------------------------------------------
if [ "$(uname -m)" = "s390x" ]; then
  echo "Arch s390x detected"
  sudo apt install rust-all libqpdf-dev libgeos-dev libproj-dev proj-bin proj-data libgeographiclib-dev freetds-dev freetds-bin libkrb5-dev libssl-dev pkg-config build-essential npm -y
fi

#--------------------------------------------------
# Update Server
#--------------------------------------------------
echo -e "\n---- Update Server ----"

if [ "18.04" == "${UBUNTU_VERSION}" ]; then
  # add-apt-repository can install add-apt-repository Ubuntu 18.x
  ${APT_GET} install software-properties-common curl -y
  # universe package is for Ubuntu 18.x
  sudo add-apt-repository universe
  # libpng12-0 dependency for wkhtmltopdf
  sudo add-apt-repository "deb http://mirrors.kernel.org/ubuntu/ xenial main"
  ${APT_GET} update
  ${APT_GET} upgrade -y
fi

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
if [ "18.04" == "${UBUNTU_VERSION}" ]; then
  ${APT_GET} install libpng12-0 -y
  retVal=$?
  if [[ $retVal -ne 0 ]]; then
    echo "apt-get libpng installation error."
    exit 1
  fi
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

if [ "18.04" == "${UBUNTU_VERSION}" ]; then
  sudo apt remove nodeJS npm
  NODE_MAJOR=16
else
  # Node 22+ required by @capacitor/cli v8.x (mobile app dependency)
  NODE_MAJOR=22
fi

echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_$NODE_MAJOR.x nodistro main" | sudo tee /etc/apt/sources.list.d/nodesource.list
${APT_GET} update
${APT_GET} install nodejs -y

sudo npm install npm@latest -g
retVal=$?
if [[ $retVal -ne 0 ]]; then
  echo "npm install npm lastest installation error."
  exit 1
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
