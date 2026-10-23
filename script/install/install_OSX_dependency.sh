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
echo "\n---- Install PostgreSQL Server ----"
if which psql >/dev/null 2>&1; then
  echo "postgresql is already installed, skipping"
else
  brew install postgresql@15
  brew install postgis
  brew services start postgresql@15
fi

# postgresql@15 est une formule versionnée, donc « keg-only » : Homebrew ne
# lie pas psql, createuser ni pg_isready dans le PATH. Son répertoire bin y
# est ajouté pour la suite de ce script.
PG_BIN="$(brew --prefix postgresql@15 2>/dev/null)/bin"
if [ -d "${PG_BIN}" ]; then
  PATH="${PG_BIN}:${PATH}"
fi

echo "\n---- Creating the ERPLibre PostgreSQL User  ----"
# PostGIS est posé comme paquet, comme sous Linux : son extension se crée dans
# une base, pas à l'installation.
. ./script/install/lib_postgres_role.sh
el_postgres_role_local "${EL_USER}" || exit 1

#--------------------------------------------------
# Install Dependencies
#--------------------------------------------------
echo "\n--- Installing Python 3 + pip3 --"
brew install git wget parallel mariadb
brew link git
brew link wget

echo "\n--- Installing extra --"
brew install shfmt
# gettext : outil de DÉVELOPPEMENT des catalogues de traduction (« msgfmt
# --check », « msgmerge ») ; Odoo n'en a pas besoin pour tourner. La formule
# Homebrew n'est pas « keg-only » : « brew install » lie déjà ses binaires
# dans le PATH, sans « link --force ».
brew install gettext
brew install parallel
brew install swig
brew install portaudio
brew install xmlsec1
echo "\n---- Installing nodeJS NPM and rtlcss for LTR support ----"
brew install nodejs npm openssl
sudo npm install -g rtlcss
sudo npm install -g less
npm install

echo 'export PATH="/usr/local/opt/openssl@1.1/bin:$PATH"' >>~/.zshrc

#--------------------------------------------------
# Install Wkhtmltopdf if needed
#--------------------------------------------------
echo "\n---- Installing Wkhtmltopdf if needed ----"
if [ ! -f "wkhtmltox-0.12.6-2.macos-cocoa.pkg" ]; then
  sudo wget https://github.com/wkhtmltopdf/packaging/releases/download/0.12.6-2/wkhtmltox-0.12.6-2.macos-cocoa.pkg
  sudo sudo installer -pkg wkhtmltox-0.12.6-2.macos-cocoa.pkg -target /
else
  echo "Wkhtmltopdf already installed"
fi
