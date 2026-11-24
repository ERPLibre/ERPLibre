
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

# erplibre_dist.py — building a self-contained ERPLibre

`erplibre_dist.py --racine <ERPLibre checkout> --sortie <dir>` turns an
installed ERPLibre into ONE directory that installs without an index, for a
hosting server that reads an application from a single repository. Freeze the
checkout first: `make repo_configure_all FREEZE=1` puts every project on its
frozen commit, and the build refuses a project that still follows its branch.

The directory holds the Odoo tree of the version without `.git` and without
proprietary modules (OPL-1, OEEL-1, « Other proprietary »), one wheel per
dependency in `roues/` with `requirements.lock.txt` naming each by its
sha256, ERPLibre's version files, a `config.conf` whose `addons_path` is
relative, the `erplibre_serve.py` launcher, and `PROVENANCE.lock` (the
commit of each project and the excluded modules). The build ends with a
proof: a fresh venv installed with `--no-index --require-hashes` must
initialise `base` in a throwaway database. Wheels built from source link the
build host's libraries (libpq, libldap…): the target runs the same system.

`--figer` runs the freeze first. `--detache <journal>` runs the build in its
own session and follows the journal to the verdict: a dropped connection
stops only the follow-up, and the same command resumes it. TODO runs both on
the selected SSH target with `Deploy › SSH › Build the offline bundle`
(`make ssh_dist`, output in `SSH_DIST`, `~/erplibre-dist` by default) — a
build machine, since its repositories are frozen.
