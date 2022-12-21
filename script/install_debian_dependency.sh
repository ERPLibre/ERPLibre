#!/usr/bin/env bash

. ./env_var.sh

EL_USER=${USER}
#EL_INSTALL_WKHTMLTOPDF="True"

##
###  WKHTMLTOPDF download links
## === Ubuntu Focal x64 === (for other distributions please replace these two links,
## in order to have correct version of wkhtmltopdf installed, for a danger note refer to
## https://github.com/odoo/odoo/wiki/Wkhtmltopdf ):
# Ubuntu 20.04
UBUNTU_VERSION=$(lsb_release -rs)
OS=$(lsb_release -si)
if [ "20.04" == "${UBUNTU_VERSION}" ]; then
  WKHTMLTOX_X64=https://github.com/wkhtmltopdf/packaging/releases/download/0.12.6-1/wkhtmltox_0.12.6-1.focal_amd64.deb
elif [ "22.04" == "${UBUNTU_VERSION}" ]; then
  WKHTMLTOX_X64=https://github.com/wkhtmltopdf/packaging/releases/download/0.12.6.1-2/wkhtmltox_0.12.6.1-2.jammy_amd64.deb
elif [ "18.04" == "${UBUNTU_VERSION}" ]; then
  WKHTMLTOX_X64=https://github.com/wkhtmltopdf/packaging/releases/download/0.12.6-1/wkhtmltox_0.12.6-1.bionic_amd64.deb
elif [[ "${OS}" == "Debian" ]]; then
  WKHTMLTOX_X64=https://github.com/wkhtmltopdf/packaging/releases/download/0.12.6.1-2/wkhtmltox_0.12.6.1-2.bullseye_amd64.deb
else
  echo "Your version of Ubuntu is not supported, only support 18.04, 20.04 and 22.04"
  exit 1
fi

#--------------------------------------------------
# Update Server
#--------------------------------------------------
echo -e "\n---- Update Server ----"

if [ "18.04" == "${UBUNTU_VERSION}" ]; then
  # add-apt-repository can install add-apt-repository Ubuntu 18.x
  sudo apt-get install software-properties-common curl -y
  # universe package is for Ubuntu 18.x
  sudo add-apt-repository universe
  # libpng12-0 dependency for wkhtmltopdf
  sudo add-apt-repository "deb http://mirrors.kernel.org/ubuntu/ xenial main"
  sudo apt-get update
  sudo apt-get upgrade -y
fi

#--------------------------------------------------
# Install PostgreSQL Server
#--------------------------------------------------
echo -e "\n---- Install PostgreSQL Server ----"
sudo apt-get install postgresql libpq-dev postgis -y
retVal=$?
if [[ $retVal -ne 0 ]]; then
  echo "apt-get install postgresql installation error."
  exit 1
fi

echo -e "\n---- Creating the ERPLibre PostgreSQL User  ----"
sudo su - postgres -c "createuser -s ${EL_USER}" 2>/dev/null || true

#--------------------------------------------------
# Install Dependencies
#--------------------------------------------------
echo -e "\n--- Installing debian dependency --"
sudo apt-get install git build-essential wget libxslt-dev libzip-dev libldap2-dev libsasl2-dev gdebi-core libffi-dev libbz2-dev parallel -y
retVal=$?
if [[ $retVal -ne 0 ]]; then
  echo "apt-get debian tool installation error."
  exit 1
fi
sudo apt-get install libmariadbd-dev -y
retVal=$?
if [[ $retVal -ne 0 ]]; then
  echo "apt-get libmariadb installation error."
  exit 1
fi
if [ "18.04" == "${UBUNTU_VERSION}" ]; then
  sudo apt-get install libpng12-0 -y
  retVal=$?
  if [[ $retVal -ne 0 ]]; then
    echo "apt-get libpng installation error."
    exit 1
  fi
fi
# Dependencies for pyenv
sudo apt-get install make libssl-dev zlib1g-dev libreadline-dev libsqlite3-dev curl llvm libncurses5-dev libncursesw5-dev xz-utils tk-dev liblzma-dev -y
retVal=$?
if [[ $retVal -ne 0 ]]; then
  echo "apt-get pyenv dependencies installation error."
  exit 1
fi

echo -e "\n---- Installing nodeJS NPM and rtlcss for LTR support ----"
if [ "18.04" == "${UBUNTU_VERSION}" ]; then
  sudo apt remove nodeJS npm
  curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.2/install.sh | bash
  chmod +x ~/.nvm/nvm.sh
  . $NVM_DIR/nvm.sh && nvm install 16.15.1
  retVal=$?
  if [[ $retVal -ne 0 ]]; then
    echo "nvm installation error."
    exit 1
  fi
  source ~/.bashrc
  npm install npm@latest -g
  retVal=$?
  if [[ $retVal -ne 0 ]]; then
    echo "npm install npm lastest installation error."
    exit 1
  fi
  npm install -g rtlcss
  retVal=$?
  if [[ $retVal -ne 0 ]]; then
    echo "npm install rtlcss installation error."
    exit 1
  fi
  npm install -g less
  retVal=$?
  if [[ $retVal -ne 0 ]]; then
    echo "npm install less installation error."
    exit 1
  fi
else
  curl -fsSL https://deb.nodesource.com/setup_current.x | sudo -E bash -
  sudo apt-get install -y nodejs
  retVal=$?
  if [[ $retVal -ne 0 ]]; then
    echo "apt-get nodejs installation error."
    exit 1
  fi
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
fi

echo -e "\n---- Test tool ----"
sudo npm install -g prettier
retVal=$?
if [[ $retVal -ne 0 ]]; then
  echo "npm install prettier installation error."
  exit 1
fi
sudo npm install -g prettier @prettier/plugin-xml
retVal=$?
if [[ $retVal -ne 0 ]]; then
  echo "npm install prettier plugin-xml installation error."
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
if [ ${EL_INSTALL_WKHTMLTOPDF} = "True" ]; then
  echo -e "\n---- Installing wkhtml ----"
  INSTALLED=$(dpkg -s wkhtmltox | grep installed)
  if [ "" == "${INSTALLED}" ]; then
    echo -e "\n---- Install wkhtml and place shortcuts on correct place ----"
    _url=${WKHTMLTOX_X64}
    sudo wget ${_url}
    sudo gdebi --n $(basename ${_url})
    retVal=$?
    if [[ $retVal -ne 0 ]]; then
      echo "gdebi install wkhtmltopdf installation error."
      exit 1
    fi
    sudo ln -fs /usr/local/bin/wkhtmltopdf /usr/bin
    sudo ln -fs /usr/local/bin/wkhtmltoimage /usr/bin
  else
    echo -e "\n---- Already installed wkhtml ----"
  fi
else
  echo "Wkhtmltopdf isn't installed due to the choice of the user!"
fi
