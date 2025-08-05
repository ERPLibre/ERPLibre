#!/usr/bin/env bash

. ./env_var.sh

#EL_USER="erplibre"
#EL_HOME="/${EL_USER}"
#EL_HOME_ERPLIBRE="${EL_HOME}/erplibre"
#EL_HOME_ODOO="${EL_HOME_ERPLIBRE}/odoo"
#EL_INSTALL_WKHTMLTOPDF="True"
#EL_PORT="8069"
#EL_SUPERADMIN="admin"
#EL_CONFIG="${EL_USER}"

#--------------------------------------------------
# Adding ERPLibre as a daemon with SystemD
#--------------------------------------------------
echo -e "\n* Create init file"
sudo rm -f /tmp/${EL_CONFIG}
cat <<EOF > /tmp/${EL_CONFIG}
[Unit]
Description=${EL_USER}
Requires=postgresql.service
After=network.target network-online.target postgresql.service

[Service]
Type=simple
SyslogIdentifier=${EL_USER}
PermissionsStartOnly=true
User=${EL_USER}
Group=${EL_USER}
Restart=always
RestartSec=5
PIDFile=${EL_HOME_ERPLIBRE}/.venv.erplibre/service.pid
ExecStart=${EL_HOME_ERPLIBRE}/run.sh
WorkingDirectory=${EL_HOME_ERPLIBRE}
StandardOutput=journal+console

[Install]
WantedBy=multi-user.target
EOF

echo -e "* Security Init File"
sudo cp /tmp/${EL_CONFIG} /etc/systemd/system/${EL_CONFIG}.service
sudo chmod 755 /etc/systemd/system/${EL_CONFIG}.service
sudo chown root: /etc/systemd/system/${EL_CONFIG}.service

echo -e "* Start ERPLibre on Startup"
sudo systemctl daemon-reload
sudo systemctl enable ${EL_CONFIG}.service

sudo su ${EL_USER} -c "sudo rm -f /tmp/${EL_USER}run.sh"
cat <<EOF > /tmp/${EL_USER}run.sh
#!/usr/bin/env bash
cd ${EL_HOME_ERPLIBRE}
source ./.venv/bin/activate
python3 ${EL_HOME_ERPLIBRE}/odoo/odoo-bin -c ${EL_HOME_ERPLIBRE}/config.conf --limit-time-real 99999 --limit-time-cpu 99999 $@
EOF

echo -e "* Security Run File"
sudo cp /tmp/${EL_USER}run.sh ${EL_HOME_ERPLIBRE}/.venv/run.sh
sudo chmod 755 ${EL_HOME_ERPLIBRE}/.venv/run.sh
sudo chown ${EL_USER}: ${EL_HOME_ERPLIBRE}/.venv/run.sh

echo "-----------------------------------------------------------"
echo "Done! The ERPLibre server is up and running. Specifications:"
echo "Port: ${EL_PORT}"
echo "Port Long Polling: ${EL_LONGPOLLING_PORT}"
echo "User service: ${EL_USER}"
echo "User PostgreSQL: ${EL_USER}"
echo "Code location: ${EL_USER}"
echo "Addons folder: ${EL_USER}/${EL_CONFIG}/addons/"
echo "SystemD file ERPLibre: /etc/systemd/system/${EL_CONFIG}.service"
echo "Start ERPLibre service: sudo systemctl start ${EL_CONFIG}"
echo "Stop ERPLibre service: sudo systemctl stop ${EL_CONFIG}"
echo "Restart ERPLibre service: sudo systemctl restart ${EL_CONFIG}"
echo "Status ERPLibre service: sudo systemctl status ${EL_CONFIG}"
echo "Logs ERPLibre service: sudo journalctl -feu ${EL_CONFIG}"
echo "-----------------------------------------------------------"

echo -e "* Starting ERPLibre Service"
sudo systemctl restart ${EL_CONFIG}.service
