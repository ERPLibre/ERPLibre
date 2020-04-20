== Start database ==
sudo systemctl start postgresql.service

== Run Odoo ==
./venv/bin/python ./odoo/odoo-bin -c config.conf
