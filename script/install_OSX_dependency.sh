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
brew install postgresql

echo  "\n---- Creating the ERPLibre PostgreSQL User  ----"
sudo su - postgres -c "createuser -s ${EL_USER}" 2> /dev/null || true

#--------------------------------------------------
# Install Dependencies
#--------------------------------------------------
echo  "\n--- Installing Python 3 + pip3 --"
brew install git python3 wget pyenv
brew link git
brew link wget
echo  "\n--- Installing docker --"
brew install minikube docker docker-compose docker-machine
brew cask install virtualbox
docker-machine create --driver virtualbox default
docker-machine env default
eval "$(docker-machine env default)"
echo  "\n---- Installing nodeJS NPM and rtlcss for LTR support ----"
brew install nodejs npm openssl
sudo npm install -g rtlcss
sudo npm install -g less
sudo npm install -g prettier
sudo npm install -g prettier @prettier/plugin-xml
yes n|pyenv install 3.7.12
pyenv local 3.7.12

echo 'export PATH="/usr/local/opt/openssl@1.1/bin:$PATH"' >> ~/.zshrc

echo -e "\n---- Installing poetry for reliable python package ----"
curl -sSL https://raw.githubusercontent.com/python-poetry/poetry/master/get-poetry.py | python

#--------------------------------------------------
# Install Wkhtmltopdf if needed
#--------------------------------------------------
echo  "\n---- Installing Wkhtmltopdf if needed ----"
if [ ! -f "wkhtmltox-0.12.6-2.macos-cocoa.pkg" ]; then
  sudo wget https://github.com/wkhtmltopdf/packaging/releases/download/0.12.6-2/wkhtmltox-0.12.6-2.macos-cocoa.pkg
  sudo sudo installer -pkg wkhtmltox-0.12.6-2.macos-cocoa.pkg -target /
else echo "Wkhtmltopdf already installed"
fi
