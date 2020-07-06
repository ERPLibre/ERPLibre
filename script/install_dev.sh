#!/usr/bin/env bash
################################################################################
# Script for installing ERPLibre locally for dev
# Author: Alexandre Ferreira Benevides
################################################################################

if [[ "${OSTYPE}" == "linux-gnu" ]]; then
    OS=$(lsb_release -si)
    if [[ "${OS}" == "Ubuntu" ]]; then
        echo  "\n---- linux-gnu installation process started ----"
        ./script/install_debian_dependancy.sh
    else
        echo "Your Linux system is not supported."
    fi
elif [[ "${OSTYPE}" == "darwin"* ]]; then
    echo  "\n---- Darwin installation process started ----"
    ./script/install_OSX_dependancy.sh
fi
