#!/usr/bin/env bash

if [[ "${OSTYPE}" == "linux-gnu" ]]; then
    OS=$(lsb_release -si)
    VERSION=$(cat /etc/issue)
    if [[ "${OS}" == *"Ubuntu"* ]]; then
        if [[  "${VERSION}" == Ubuntu\ 18.04* || "${VERSION}" == Ubuntu\ 20.04* || "${VERSION}" == Ubuntu\ 22.04* || "${VERSION}" == Ubuntu\ 22.10* || "${VERSION}" == Ubuntu\ 23.04* || "${VERSION}" == Ubuntu\ 23.10* ]]; then
            echo  "\n---- linux-gnu installation process started ----"
            ./script/install/install_debian_dependency.sh
        else
            echo "Your version is not supported, only support 18.04, 20.04 and 22.04 - 23.10 : ${VERSION}"
        fi
    elif [[ "${OS}" == *"Debian"* ]]; then
        ./script/install/install_debian_dependency.sh
    else
        ./script/install/install_debian_dependency.sh
        echo "Your Linux system is not supported, only support Ubuntu 18.04 or Ubuntu 20.04 or Ubuntu 22.04 - Ubuntu 23.10."
    fi
elif [[ "${OSTYPE}" == "darwin"* ]]; then
    echo  "\n---- Darwin installation process started ----"
    ./script/install/install_OSX_dependency.sh
fi
