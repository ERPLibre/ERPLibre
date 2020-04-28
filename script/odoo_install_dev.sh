#!/bin/bash
################################################################################
# Script for installing Odoo locally for dev
# Author: Alexandre Ferreira Benevides
################################################################################

. ./env_var.sh

if [[ "${OSTYPE}" == "linux-gnu" ]]; then
    OS=$(lsb_release -si)
    if [[ "${OS}" == "Ubuntu" ]]; then
        echo  "\n---- linux-gnu installation process started ----"
        ./script/odoo_install_debian_dependancy.sh
        ./script/odoo_install_locally.sh
    else
        echo "Your Linux system is not supported."
    fi
elif [[ "${OSTYPE}" == "darwin"* ]]; then
    echo  "\n---- Darwin installation process started ----"
    ./script/odoo_install_OSX_dependancy.sh
    ./script/odoo_install_locally.sh
fi
