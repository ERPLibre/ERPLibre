#!/usr/bin/env bash

# Extras de développement pour les tests, sur Ubuntu : MariaDB avec un root
# sans mot de passe, et Docker en mode rootless. Les versions acceptées sont
# celles qu'ERPLibre supporte, 24.04, 25.10 et 26.04 ; les plus anciennes,
# install_debian_dependency.sh les refuse déjà.
#
# uidmap n'est pas une dépendance du paquet docker-ce-rootless-extras, mais
# dockerd-rootless-setuptool.sh refuse de s'installer sans newuidmap. Le
# profil AppArmor de /usr/bin/rootlesskit, qu'exige la restriction des
# espaces de noms utilisateur non privilégiés de ces versions, vient du
# paquet apparmor d'Ubuntu.
#
# Rend 1, sans rien installer, sur un autre système ou une autre version.

if [[ ! -r /etc/os-release ]]; then
    echo "Your Linux system is not supported, only support Ubuntu 24.04, 25.10 and 26.04."
    exit 1
fi
# Sous-shell : « source » importerait NAME, PRETTY_NAME et le reste.
OS=$(. /etc/os-release && echo "${ID}")
VERSION=$(. /etc/os-release && echo "${VERSION_ID}")

if [[ "${OS}" != "ubuntu" ]]; then
    echo "Your Linux system is not supported, only support Ubuntu 24.04, 25.10 and 26.04."
    exit 1
fi
case "${VERSION}" in
    24.04 | 25.10 | 26.04) ;;
    *)
        echo "Your version is not supported, only support 24.04, 25.10 and 26.04 : ${VERSION}"
        exit 1
        ;;
esac

# Install mariadb
sudo apt-get update
sudo apt-get install -y mariadb-client mariadb-server
echo "This is not for production, this is for development. Mysql user root will be accessible without password."
sudo mysql -u root << EOF
SET PASSWORD FOR root@localhost='';
FLUSH PRIVILEGES;
EOF

# Install docker, rootless
curl -fsSL https://get.docker.com | sh
sudo apt-get install -y uidmap
dockerd-rootless-setuptool.sh install
