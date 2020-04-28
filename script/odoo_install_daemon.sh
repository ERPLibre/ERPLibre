#!/bin/bash
################################################################################
# Script for installing Odoo on Ubuntu 14.04, 15.04, 16.04 and 18.04 (could be used for other version too)
# Author: Yenthe Van Ginneken
#-------------------------------------------------------------------------------
# This script will install Odoo on your Ubuntu 16.04 server. It can install multiple Odoo instances
# in one Ubuntu because of the different xmlrpc_ports
#-------------------------------------------------------------------------------
################################################################################

. ./env_var.sh

#OE_USER="odoo"
#OE_HOME="/${OE_USER}/odoo"
#OE_HOME_EXT="/${OE_USER}/odoo/odoo/odoo"
## The default port where this Odoo instance will run under (provided you use the command -c in the terminal)
## Set to true if you want to install it, false if you don't need it or have it already installed.
#INSTALL_WKHTMLTOPDF="True"
## Set the default Odoo port (you still have to use -c /etc/odoo-server.conf for example to use this.)
#OE_PORT="8069"
## set the superadmin password
#OE_SUPERADMIN="admin"
#OE_CONFIG="${OE_USER}"

#--------------------------------------------------
# Adding ODOO as a deamon with SystemD
#--------------------------------------------------
echo -e "\n* Create init file"
sudo rm -f /tmp/${OE_CONFIG}
cat <<EOF > /tmp/${OE_CONFIG}
[Unit]
Description=${OE_USER}
Requires=postgresql.service
After=network.target network-online.target postgresql.service

[Service]
Type=simple
SyslogIdentifier=${OE_USER}
PermissionsStartOnly=true
User=${OE_USER}
Group=${OE_USER}
Restart=always
RestartSec=5
PIDFile=${OE_HOME_ODOO}/venv/service.pid
ExecStart=${OE_HOME_ODOO}/venv/run.sh
StandardOutput=journal+console

[Install]
WantedBy=multi-user.target
EOF

echo -e "* Security Init File"
sudo cp /tmp/${OE_CONFIG} /etc/systemd/system/${OE_CONFIG}.service
sudo chmod 755 /etc/systemd/system/${OE_CONFIG}.service
sudo chown root: /etc/systemd/system/${OE_CONFIG}.service

echo -e "* Start ODOO on Startup"
sudo systemctl daemon-reload
sudo systemctl enable ${OE_CONFIG}.service

sudo su ${OE_USER} -c "sudo rm -f /tmp/${OE_USER}run.sh"
cat <<EOF > /tmp/${OE_USER}run.sh
#!/usr/bin/env bash
cd ${OE_HOME_ODOO}
source ./venv/bin/activate
python3 ${OE_HOME_ODOO}/odoo/odoo-bin -c ${OE_HOME_ODOO}/config.conf
EOF

echo -e "* Security Run File"
sudo cp /tmp/${OE_USER}run.sh ${OE_HOME_ODOO}/venv/run.sh
sudo chmod 755 ${OE_HOME_ODOO}/venv/run.sh
sudo chown ${OE_USER}: ${OE_HOME_ODOO}/venv/run.sh

echo "-----------------------------------------------------------"
echo "Done! The Odoo server is up and running. Specifications:"
echo "Port: ${OE_PORT}"
echo "Port Long Polling: ${OE_LONGPOLLING_PORT}"
echo "User service: ${OE_USER}"
echo "User PostgreSQL: ${OE_USER}"
echo "Code location: ${OE_USER}"
echo "Addons folder: ${OE_USER}/${OE_CONFIG}/addons/"
echo "Start Odoo service: sudo systemctl start ${OE_CONFIG}"
echo "Stop Odoo service: sudo systemctl stop ${OE_CONFIG}"
echo "Restart Odoo service: sudo systemctl restart ${OE_CONFIG}"
echo "-----------------------------------------------------------"

echo -e "* Starting Odoo Service"
sudo systemctl restart ${OE_CONFIG}.service
