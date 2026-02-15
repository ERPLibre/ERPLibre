
# Mettre à jour ERPLibre

## Mettre à jour tous les dépôts depuis la source d'origine

La mise à jour est possible sur la branche 12.0, vous devez vérifier l'existence de cette branche.

1. Assurez-vous que tous les dépôts git sont conformes, supprimez tous les arguments depth du manifest et régénérez. Vous pouvez tout nettoyer et régénérer.

```bash
./script/git/clean_repo_manifest.sh
./script/install/install_locally_dev.sh
```

2. Mettre à jour tous les dépôts distants avec ssh/git

```bash
./script/git/git_change_remote_https_to_git.py
```

3. Exécutez le script de mise à jour

```bash
./script/git/git_update_repo.py
```

4. Faites un push forcé sur tous les dépôts nécessaires et gérez les conflits de rebase.

5. Testez un clone en dev, consultez le fichier [DEVELOPMENT.md](./DEVELOPMENT.md)