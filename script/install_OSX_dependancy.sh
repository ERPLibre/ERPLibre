#!/usr/bin/env bash
################################################################################
# Script for installing ERPLibre on OSX
# Author: Alexandre Ferreira Benevides
#-------------------------------------------------------------------------------
# This script will install dependency for ERPLibre on your OSX server.
#-------------------------------------------------------------------------------
################################################################################

EL_USER=$(whoami)

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
brew install git python3 wget
brew link git
brew link wget
echo  "\n---- Installing nodeJS NPM and rtlcss for LTR support ----"
brew install nodejs npm
sudo npm install -g rtlcss
sudo npm install -g less
#--------------------------------------------------
# Install Wkhtmltopdf if needed
#--------------------------------------------------
echo  "\n---- Installing Wkhtmltopdf if needed ----"
if [ ! -f "wkhtmltox-0.12.5-1.macos-carbon.pkg" ]; then
  sudo wget https://github.com/wkhtmltopdf/wkhtmltopdf/releases/download/0.12.5/wkhtmltox-0.12.5-1.macos-carbon.pkg
  sudo sudo installer -pkg wkhtmltox-0.12.5-1.macos-carbon.pkg -target /
else echo "Wkhtmltopdf already installed"
fi

# ===============================================================================================
# !!!! FOR OSX there is a problem with python 3.7.5 with PILLOW, use 3.6.9 instead and works fine
# install python 3.6.9
#       brew install pyenv
#       pyenv install 3.6.9
# then redoo link:
#       unlink /usr/local/bin/python3
#       ln -s ~/.pyenv/versions/3.6.9/bin/python3.6 /usr/local/bin/python3
# ===============================================================================================
echo  "\n---- Installing venv if not already existing (rm -r venv if already exists) ----"
#~/.pyenv/versions/3.6.9/bin/python3.6 -m venv venv
python3 -m venv venv
