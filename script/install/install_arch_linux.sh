#!/usr/bin/env bash

install_package() {
    local package_name=$1

    # Check package is already installed
    if pacman -Qs "$package_name" > /dev/null; then
        echo "$package_name is already installed."
    else
        echo "Installation of package $package_name..."
        yes|yay -S "$package_name"
    fi
}

# Odoo installation
install_package postgis
install_package postgresql
install_package mariadb
install_package libev
install_package wkhtmltopdf

echo "Need password to create symbolic link, create postgres user and install npm :"
sudo ln -fs /usr/lib/libldap.so /usr/lib/libldap_r.so

sudo su - postgres -c "createuser -s ${EL_USER}" 2>/dev/null || true

echo -e "\n---- Update NPM ----"
install_package npm

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

# TODO install nginx

# ERPLibre installation
install_package cmake
install_package parallel
install_package tk
