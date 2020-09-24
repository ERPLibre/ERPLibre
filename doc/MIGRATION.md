# ERPLibre

# Migrate Data
## Migration procedure in production

TODO

## Migration procedure in dev

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