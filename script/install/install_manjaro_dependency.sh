#!/usr/bin/env bash

. ./env_var.sh

EL_USER=${USER}
#EL_INSTALL_WKHTMLTOPDF="True"

##
###  WKHTMLTOPDF download links
## https://github.com/odoo/odoo/wiki/Wkhtmltopdf ):
WKHTMLTOX_X64=https://github.com/wkhtmltopdf/packaging/releases/download/0.12.6-3/wkhtmltox-0.12.6-3.archlinux-x86_64.pkg.tar.xz

#--------------------------------------------------
# Install PostgreSQL Server
#--------------------------------------------------
echo -e "\n---- Install PostgreSQL Server ----"
sudo pacman -S postgresql postgresql-libs postgis
retVal=$?
if [[ $retVal -ne 0 ]]; then
  echo "pacman install postgresql installation error."
  exit 1
fi

echo -e "\n---- Creating the ERPLibre PostgreSQL User  ----"
sudo su - postgres -c "createuser -s ${EL_USER}" 2>/dev/null || true

#--------------------------------------------------
# Install Dependencies
#--------------------------------------------------
echo -e "\n--- Installing debian dependency --"
sudo apt-get install git build-essential libxslt-dev libzip-dev libldap2-dev libsasl2-dev libffi-dev libbz2-dev parallel pysassc -y
retVal=$?
if [[ $retVal -ne 0 ]]; then
  echo "pacman tool installation error."
  exit 1
fi
sudo pacman -S mariadb-libs
retVal=$?
if [[ $retVal -ne 0 ]]; then
  echo "pacman -S mariadb-libs installation error."
  exit 1
fi
# Dependencies for pyenv
sudo apt-get install make libssl-dev zlib1g-dev libreadline-dev libsqlite3-dev curl llvm libncurses5-dev libncursesw5-dev xz-utils tk-dev liblzma-dev -y
retVal=$?
if [[ $retVal -ne 0 ]]; then
  echo "apt-get pyenv dependencies installation error."
  exit 1
fi

echo -e "\n---- Installing nodeJS NPM and rtlcss for LTR support ----"
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
