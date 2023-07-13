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
if which psql >/dev/null 2>&1; then
  echo "postgresql is already installed, skipping"
else
  echo "Postgresql not installed, so we will install it"
  brew install postgresql@15
  brew install postgis
  brew services start postgresql@15
fi

echo  "\n---- Creating the ERPLibre PostgreSQL User  ----"
sudo su - postgres -c "createuser -s ${EL_USER}" 2> /dev/null || true
sudo su - postgres -c "CREATE EXTENSION postgis;\nCREATE EXTENSION postgis_topology;" 2> /dev/null || true

#--------------------------------------------------
# Install Dependencies
#--------------------------------------------------
echo  "\n--- Installing Python 3 + pip3 --"
#TODO is python@3.7 line here still usefull?? Should we get rid of it?
brew install git python@3.7 wget parallel mariadb
brew link git
brew link wget

echo  "\n--- Installing extra --"
brew install parallel
brew install swig
echo  "\n---- Installing nodeJS NPM and rtlcss for LTR support ----"
brew install nodejs npm openssl
sudo npm install -g rtlcss
sudo npm install -g less
sudo npm install -g prettier
sudo npm install -g prettier @prettier/plugin-xml

echo 'export PATH="/usr/local/opt/openssl@1.1/bin:$PATH"' >> ~/.zshrc

#--------------------------------------------------
# Install Wkhtmltopdf if needed
#--------------------------------------------------
echo  "\n---- Installing Wkhtmltopdf if needed ----"
if [ ! -f "wkhtmltox-0.12.6-2.macos-cocoa.pkg" ]; then
  sudo wget https://github.com/wkhtmltopdf/packaging/releases/download/0.12.6-2/wkhtmltox-0.12.6-2.macos-cocoa.pkg
  sudo sudo installer -pkg wkhtmltox-0.12.6-2.macos-cocoa.pkg -target /
else echo "Wkhtmltopdf already installed"
fi
