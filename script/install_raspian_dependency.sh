#!/usr/bin/env bash

. ./env_var.sh

EL_USER=${USER}
#EL_INSTALL_WKHTMLTOPDF="True"

##
###  WKHTMLTOPDF download links
## === Raspian ARM === (for other distributions please replace these two links,
## in order to have correct version of wkhtmltopdf installed, for a danger note refer to
## https://github.com/odoo/odoo/wiki/Wkhtmltopdf ):
# Raspian
# check if 64 or 32 bit
 if [ `getconf LONG_BIT` = "64" ]
 then
     echo "I'm 64-bit"
     WKHTMLTOX_ARM=https://github.com/wkhtmltopdf/packaging/releases/download/0.12.6-1/wkhtmltox_0.12.6-1.buster_arm64.deb
 else
     echo "I'm 32-bit"
     WKHTMLTOX_ARM=https://github.com/wkhtmltopdf/packaging/releases/download/0.12.6-1/wkhtmltox_0.12.6-1.raspberrypi.buster_armhf.deb
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
sudo apt-get install postgresql libpq-dev -y

echo -e "\n---- Creating the ERPLibre PostgreSQL User  ----"
sudo su - postgres -c "createuser -s ${EL_USER}" 2> /dev/null || true

#--------------------------------------------------
# Install Dependencies
#--------------------------------------------------
echo -e "\n--- Installing debian dependency --"
sudo apt-get install git build-essential wget libxslt-dev libzip-dev libldap2-dev libsasl2-dev libpng12-0 gdebi-core libffi-dev libbz2-dev -y
sudo apt-get install libmariadbd-dev -y
sudo apt-get install gdebi-core

#Valider si la prochaine ligne est nécessaire, possiblement retirer les lignes 2 et 3, ou les 3
sudo apt-get remove python-pymssql
sudo apt-get install python-pip freetds-dev python3-dev python-dev
#sudo pip install pymssql==2.1.5

sudo apt-get install python3-distutils
sudo apt-get install python-dev python-setuptools
sudo apt-get install proj-bin -y
sudo apt-get install libopenjp2-7
sudo apt -y install rustc

#TODO verify need for this addition after test
echo -e "\n---- Installing dependencies for pyenv ----"
sudo apt-get install make build-essential libssl-dev zlib1g-dev \
  libbz2-dev libreadline-dev libsqlite3-dev wget curl llvm \
  libncursesw5-dev xz-utils tk-dev libxml2-dev libxmlsec1-dev libffi-dev liblzma-dev

#TODO verify need for this addition after test
echo -e "\n---- for pillow ----"
sudo apt-get install libjpeg-dev zlib1g-dev

#TODO verify need for this addition after test
echo -e "\n---- for pymssql ----"
sudo apt-get --assume-yes update
sudo apt-get --assume-yes install install freetds-dev freetds-bin
sudo apt-get --assume-yes install python-dev python-pip

echo -e "\n---- Installing nodeJS NPM and rtlcss for LTR support ----"
sudo apt-get install nodejs npm -y
sudo npm install -g rtlcss
sudo npm install -g less

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
      _url=${WKHTMLTOX_ARM}
      sudo wget ${_url}
      sudo gdebi --n `basename ${_url}`
      sudo ln -s /usr/local/bin/wkhtmltopdf /usr/bin
      sudo ln -s /usr/local/bin/wkhtmltoimage /usr/bin
  else echo -e "\n---- Already installed wkhtml ----"
  fi
else
  echo "Wkhtmltopdf isn't installed due to the choice of the user!"
fi
