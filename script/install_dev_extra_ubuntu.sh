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
        sudo apt-get update
        sudo apt-get install ca-certificates curl gnupg lsb-release
        curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg
        echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
        sudo apt-get update
        sudo apt-get install docker-ce docker-ce-cli containerd.io

        # Run without root
        #sudo groupadd docker
        sudo usermod -aG docker "$USER"
        #newgrp docker

        # Install docker-compose
        sudo curl -L "https://github.com/docker/compose/releases/download/1.29.2/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
        sudo chmod +x /usr/local/bin/docker-compose
        else
            echo "Your version is not supported, only support 18.04 and 20.04 : ${VERSION}"
        fi
    else
        echo "Your Linux system is not supported, only support Ubuntu 18.04 or Ubuntu 20.04."
    fi
fi
