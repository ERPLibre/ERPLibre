
# Update ERPLibre

## Update all repos from the origin source

The update is possible on branch 12.0, you need to verify this branch existence.

1. Make sure all git repos are conform, remove all argument depth from manifest and regenerate. You can clean all and
   regenerate.

```bash
./script/git/clean_repo_manifest.sh
./script/install/install_locally_dev.sh
```

2. Update all remote with ssh/git

```bash
./script/git/git_change_remote_https_to_git.py
```

3. Rebase each fork on its upstream branch, declared by `fork-upstream-remote` and `fork-upstream` in
   `./manifest/git_manifest_odoo<version>.xml`, then force push the needed repos and manage rebase conflicts.

4. Test a clone with dev, check file [DEVELOPMENT.md](./DEVELOPMENT.md)
