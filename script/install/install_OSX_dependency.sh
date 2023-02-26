#!/usr/bin/env bash
################################################################################
# Script for installing ERPLibre on OSX
# Author: Alexandre Ferreira Benevides
#-------------------------------------------------------------------------------
# This script will install dependency for ERPLibre on your OSX server.
#-------------------------------------------------------------------------------
################################################################################

EL_USER=${USER}

#--------------------------------------------------
# Install PostgreSQL Server
#--------------------------------------------------
echo  "\n---- Install PostgreSQL Server ----"
brew install postgresql@15
brew install postgis
brew services start postgresql@15

echo  "\n---- Creating the ERPLibre PostgreSQL User  ----"
sudo su - postgres -c "createuser -s ${EL_USER}" 2> /dev/null || true
sudo su - postgres -c "CREATE EXTENSION postgis;\nCREATE EXTENSION postgis_topology;" 2> /dev/null || true

#--------------------------------------------------
# Install Dependencies
#--------------------------------------------------
echo  "\n--- Installing Python 3 + pip3 --"
brew install git python@3.7 wget parallel mariadb
brew link git
brew link wget
echo  "\n---- Installing nodeJS NPM and rtlcss for LTR support ----"
brew install nodejs npm openssl
sudo npm install -g rtlcss
sudo npm install -g less
sudo npm install -g prettier
sudo npm install -g prettier @prettier/plugin-xml
#yes n|pyenv install 3.7.16
#pyenv local 3.7.16

echo 'export PATH="/usr/local/opt/openssl@1.1/bin:$PATH"' >> ~/.zshrc

echo -e "\n---- Installing poetry for reliable python package ----"
#curl -sSL https://raw.githubusercontent.com/python-poetry/poetry/master/install-poetry.py | python3.7
#curl -L https://raw.githubusercontent.com/pyenv/pyenv-installer/master/bin/pyenv-installer | bash
#--------------------------------------------------
# Install Wkhtmltopdf if needed
#--------------------------------------------------
echo  "\n---- Installing Wkhtmltopdf if needed ----"
if [ ! -f "wkhtmltox-0.12.6-2.macos-cocoa.pkg" ]; then
  sudo wget https://github.com/wkhtmltopdf/packaging/releases/download/0.12.6-2/wkhtmltox-0.12.6-2.macos-cocoa.pkg
  sudo sudo installer -pkg wkhtmltox-0.12.6-2.macos-cocoa.pkg -target /
else echo "Wkhtmltopdf already installed"
fi
