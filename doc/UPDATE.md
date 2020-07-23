# Update ERPLibre
## Update all repo from origin source
The update is done on branch 12.0, you need to validate this branch exist.

1. Make sure all repo git is conform, remove all argument depth from manifest and regenerate.
You can clean all and regenerate
```bash
./script/clean_repo_manifest.sh
./script/install_locally_dev.sh
```

2. Update all remote with ssh/git
```bash
./script/git_change_remote_https_to_git.py
```

3. Run update script
```bash
./script/git_update_repo.py
```

4. Push force all needed repo, manage rebase conflict

5. Test a clone with dev, check file [DEVELOPMENT.md](./DEVELOPMENT.md)
