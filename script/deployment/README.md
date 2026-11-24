
# Information about deployment with cloudflare

The script update_dns_cloudflare.py is used to update all DNS for case of DDNS, when ip address change, with a cron. This version support an old version of cloudflare==2.20.0

The script cloudflare_dns.py is used to update specific address at a deployment.

# erplibre_serve.py — starting a hosted ERPLibre

`erplibre_serve.py --port <port> --etat <state dir>` starts the Odoo of an
ERPLibre checkout from the host's environment, the way a hosting server
provides it. The database connection comes from libpq's variables (`PGHOST`,
`PGDATABASE`, `PGUSER`, `PGPASSWORD`, `PGSSLMODE`, `PGSSLROOTCERT`); the master
password from `ODOO_ADMIN_PASSWD`. The database password never enters the
configuration file. The versions are ERPLibre's own: `.erplibre-version` and
`.odoo-version`, else the default pair of `conf/supported_version_erplibre.json`.

On each start it initialises an empty database, migrates when the code
changed, serves otherwise, and REFUSES an empty database that its state
directory had already initialised: a restore that did not happen must not be
covered by a fresh database.
