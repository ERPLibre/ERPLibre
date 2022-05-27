#!/usr/bin/env bash

. ./env_var.sh

echo -e "\n---- Create ERPLIBRE system user ----"
sudo adduser --system --quiet --shell=/bin/bash --home=/${EL_USER} --gecos 'ERPLIBRE' --group ${EL_USER}
#The user should also be added to the sudo'ers group.
sudo adduser ${EL_USER} sudo

echo -e "\n---- Creating the ERPLIBRE PostgreSQL User  ----"
sudo su - postgres -c "createuser -s ${EL_USER}" 2> /dev/null || true

#echo -e "\n---- Create Log directory ----"
#sudo mkdir /var/log/${EL_USER}
#sudo chown ${EL_USER}:${EL_USER} /var/log/${EL_USER}

echo -e "\n---- Setting permissions on home folder ----"
sudo mkdir -p ${EL_HOME}
sudo chown -R ${EL_USER}:${EL_USER} ${EL_HOME}

#--------------------------------------------------
# Install ERPLIBRE
#--------------------------------------------------
echo -e "\n==== Clone this installation  ===="
REMOTE_URL_GIT=`git remote get-url origin`
BRANCH_GIT=`git rev-parse --abbrev-ref HEAD`
if [ "HEAD" = "${BRANCH_GIT}" ]; then
  # Checkout version of env_var.sh
  sudo su ${EL_USER} -c "git clone --branch v${ERPLIBRE_VERSION} ${REMOTE_URL_GIT} ${EL_HOME_ERPLIBRE}"
else
  sudo su ${EL_USER} -c "git clone --branch ${BRANCH_GIT} ${REMOTE_URL_GIT} ${EL_HOME_ERPLIBRE}"
fi
sudo cp ./env_var.sh ${EL_HOME_ERPLIBRE}
sudo chown -R ${EL_USER}:${EL_USER} ${EL_HOME_ERPLIBRE}/env_var.sh

LAST_PWD=$PWD
cd ${EL_HOME_ERPLIBRE}
sudo su ${EL_USER} -c "./script/install_locally_prod.sh"
cd ${LAST_PWD}
#echo -e "\n* Updating server config file"
#sudo su ${EL_USER} -c "printf 'logfile = /var/log/${EL_USER}/${EL_CONFIG}.log\n' >> /${EL_USER}/erplibre/config.conf"

#--------------------------------------------------
# Adding ERPLIBRE as a daemon
#--------------------------------------------------
./script/install_daemon.sh

#--------------------------------------------------
# Install Nginx if needed
#--------------------------------------------------
./script/install_production_nginx.sh