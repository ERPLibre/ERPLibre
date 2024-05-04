#!/usr/bin/env bash

# Need this for test extra

if [[ "${OSTYPE}" == "linux-gnu" ]]; then
    OS=$(lsb_release -si)
    VERSION=$(cat /etc/issue)
    if [[ "${OS}" == "Ubuntu" ]]; then
        if [[  "${VERSION}" == Ubuntu\ 18.04* || "${VERSION}" == Ubuntu\ 20.04* ]]; then
            # Install mariadb
            sudo apt install mariadb-client mariadb-server
            echo "This is not for production, this is for development. Mysql user root will be accessible without password."
            sudo mysql -u root << EOF
SET PASSWORD FOR root@localhost='';
FLUSH PRIVILEGES;
EOF

        # Install docker
        curl -fsSL https://get.docker.com | sh
        dockerd-rootless-setuptool.sh install
    else
        echo "Your Linux system is not supported, only support Ubuntu 18.04 or Ubuntu 20.04."
    fi
fi
