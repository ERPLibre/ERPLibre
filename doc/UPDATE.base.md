<!---------------------------->
<!-- multilingual suffix: en, fr -->
<!-- no suffix: en -->
<!---------------------------->

<!-- [en] -->
# Update ERPLibre

## Update all repos from the origin source

The update is possible on branch 12.0, you need to verify this branch existence.

1. Make sure all git repos are conform, remove all argument depth from manifest and regenerate. You can clean all and
   regenerate.

<!-- [fr] -->
# Mettre à jour ERPLibre

## Mettre à jour tous les dépôts depuis la source d'origine

La mise à jour est possible sur la branche 12.0, vous devez vérifier l'existence de cette branche.

1. Assurez-vous que tous les dépôts git sont conformes, supprimez tous les arguments depth du manifest et régénérez. Vous pouvez tout nettoyer et régénérer.

<!-- [common] -->
```bash
./script/git/clean_repo_manifest.sh
./script/install/install_locally_dev.sh
```

<!-- [en] -->
2. Update all remote with ssh/git

<!-- [fr] -->
2. Mettre à jour tous les dépôts distants avec ssh/git

<!-- [common] -->
```bash
./script/git/git_change_remote_https_to_git.py
```

<!-- [en] -->
3. Run update script

<!-- [fr] -->
3. Exécutez le script de mise à jour

<!-- [common] -->
```bash
./script/git/git_update_repo.py
```

<!-- [en] -->
4. Do a forced push on all needed repo and manage rebase conflicts.

5. Test a clone with dev, check file [DEVELOPMENT.md](./DEVELOPMENT.md)

<!-- [fr] -->
4. Faites un push forcé sur tous les dépôts nécessaires et gérez les conflits de rebase.

5. Testez un clone en dev, consultez le fichier [DEVELOPMENT.md](./DEVELOPMENT.md)
