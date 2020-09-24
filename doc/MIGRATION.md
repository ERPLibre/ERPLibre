# ERPLibre

# Migrate Data
## Migration procedure production

TODO

## Migration procedure dev

Example:

update module helpdesk_mgmt and helpdesk_join_team

update translation all

Remove helpdesk_res_partner_team

Delete module not found

smile_upgrade?

--limit-time-real 99999 -c config.conf --stop-after-init -d santelibre -i helpdesk_mrp -i erplibre_base_enterprise_mrp,erplibre_base_hackaton,helpdesk_mgmt -u helpdesk_join_team

--limit-time-real 99999 -c config.conf --stop-after-init -d santelibre  -u helpdesk_join_team

# Migrate Code
## New repo with old 
Checkout a new branch, like this example :
```bash
git checkout -b mig_REPO
```

You need dependency : 
```bash
./.venv/bin/pip install -e git://github.com/grap/odoo-module-migrator.git#egg=odoo-module-migrator
```

Add repo in file [source_repo_addons.csv](../source_repo_addons.csv)

Fork it
```bash
./script/fork_project_ERPLibre.py --github_token GITHUB_KEY --organization NAME
```

Add actual revision in ./manifest/default.dev.xml on new line in <project name="mig_REPO" ...>
```
revision="10.0"
```

Commit
```bash
git commit -am "Migrate REPO"
```

Go on the repo and create branch `12.0_mig`
```bash
cd addons/REPO
git checkout -b 12.0_mig
```

For each module, run this command
```bash
/.venv/bin/odoo-module-migrate --directory ./ --init-version-name 10.0 --target-version-name 12.0 --modules module_name
```

Update python dependency
```bash
cd ../..
./script/poetry_update.py
```

Create a clean environment and install all this module.
