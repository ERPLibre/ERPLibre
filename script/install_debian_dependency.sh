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
if [ "20.04" == "${UBUNTU_VERSION}" ]; then
  WKHTMLTOX_X64=https://github.com/wkhtmltopdf/packaging/releases/download/0.12.6-1/wkhtmltox_0.12.6-1.focal_amd64.deb
elif [ "18.04" == "${UBUNTU_VERSION}" ]; then
  WKHTMLTOX_X64=https://github.com/wkhtmltopdf/packaging/releases/download/0.12.6-1/wkhtmltox_0.12.6-1.bionic_amd64.deb
else
  WKHTMLTOX_X64=https://github.com/wkhtmltopdf/packaging/releases/download/0.12.6-1/wkhtmltox_0.12.6-1.buster_amd64.deb
fi

#--------------------------------------------------
# Update Server
#--------------------------------------------------
echo -e "\n---- Update Server ----"

# add-apt-repository can install add-apt-repository Ubuntu 18.x
sudo apt-get install software-properties-common curl -y
# universe package is for Ubuntu 18.x
sudo add-apt-repository universe
# libpng12-0 dependency for wkhtmltopdf
sudo add-apt-repository "deb http://mirrors.kernel.org/ubuntu/ xenial main"
sudo apt-get update
sudo apt-get upgrade -y

#--------------------------------------------------
# Install PostgreSQL Server
#--------------------------------------------------
echo -e "\n---- Install PostgreSQL Server ----"
sudo apt-get install postgresql libpq-dev postgis -y

echo -e "\n---- Creating the ERPLibre PostgreSQL User  ----"
sudo su - postgres -c "createuser -s ${EL_USER}" 2> /dev/null || true

#--------------------------------------------------
# Install Dependencies
#--------------------------------------------------
echo -e "\n--- Installing debian dependency --"
sudo apt-get install git build-essential wget libxslt-dev libzip-dev libldap2-dev libsasl2-dev libpng12-0 gdebi-core libffi-dev libbz2-dev -y
sudo apt-get install libmariadbd-dev -y
# Dependencies for pyenv
sudo apt-get install make libssl-dev zlib1g-dev libreadline-dev libsqlite3-dev curl llvm libncurses5-dev libncursesw5-dev xz-utils tk-dev liblzma-dev -y

echo -e "\n---- Installing nodeJS NPM and rtlcss for LTR support ----"
curl -fsSL https://deb.nodesource.com/setup_current.x | sudo -E bash -
sudo apt-get install -y nodejs
sudo npm install npm@latest -g
sudo npm install -g rtlcss
sudo npm install -g less

echo -e "\n---- Test tool ----"
sudo npm install -g prettier
sudo npm install -g prettier @prettier/plugin-xml

sudo ln -fs /usr/local/bin/lessc /usr/bin/lessc

if [ ${EL_INSTALL_NGINX} = "True" ]; then
  echo -e "\n---- Installing nginx ----"
  sudo apt install nginx -y
fi

#--------------------------------------------------
# Install Wkhtmltopdf if needed
#--------------------------------------------------
if [ ${EL_INSTALL_WKHTMLTOPDF} = "True" ]; then
  echo -e "\n---- Installing wkhtml ----"
  INSTALLED=$(dpkg -s wkhtmltox|grep installed)
  if [ "" == "${INSTALLED}" ]; then
      echo -e "\n---- Install wkhtml and place shortcuts on correct place ----"
      _url=${WKHTMLTOX_X64}
      sudo wget ${_url}
      sudo gdebi --n `basename ${_url}`
      sudo ln -s /usr/local/bin/wkhtmltopdf /usr/bin
      sudo ln -s /usr/local/bin/wkhtmltoimage /usr/bin
  else echo -e "\n---- Already installed wkhtml ----"
  fi
else
  echo "Wkhtmltopdf isn't installed due to the choice of the user!"
fi
