#!/usr/bin/env bash

if [[ "${OSTYPE}" == "linux-gnu" ]]; then
    OS=$(lsb_release -si)
    VERSION=$(cat /etc/issue)
    if [[ "${OS}" == "Ubuntu" ]]; then
        if [[  "${VERSION}" == Ubuntu\ 18.04* || "${VERSION}" == Ubuntu\ 20.04* || "${VERSION}" == Ubuntu\ 22.04* ]]; then
            echo  "\n---- linux-gnu installation process started ----"
            ./script/install_debian_dependency.sh
        else
            echo "Your version is not supported, only support 18.04, 20.04 and 22.04 : ${VERSION}"
        fi
    else
        echo "Your Linux system is not supported, only support Ubuntu 18.04 or Ubuntu 20.04 or Ubuntu 22.04."
    fi
elif [[ "${OSTYPE}" == "darwin"* ]]; then
    echo  "\n---- Darwin installation process started ----"
    ./script/install_OSX_dependency.sh
fi
