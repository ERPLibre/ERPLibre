<!---------------------------->
<!-- multilingual suffix: en, fr -->
<!-- no suffix: en -->
<!---------------------------->

<!-- [en] -->
# FAQ

## Into execution

### wkthmltopdf TimeoutError

If you find this bug on server log :
`odoo.addons.base.models.ir_actions_report: wkhtmltopdf: Exit with code 1 due to network error: TimeoutError`

Into configuration, technique, go to ir.config_parameter (system parameter) and add configuration :

<!-- [fr] -->
# FAQ

## Lors de l'exécution

### wkthmltopdf TimeoutError

Si vous trouvez ce bogue dans le journal du serveur :
`odoo.addons.base.models.ir_actions_report: wkhtmltopdf: Exit with code 1 due to network error: TimeoutError`

Dans la configuration, technique, allez dans ir.config_parameter (paramètre système) et ajoutez la configuration :

<!-- [common] -->
```
key : report.url
value : http://127.0.0.1:8069
```

<!-- [en] -->
## Scripting

### Search all duplicate file recursively in given directory

<!-- [fr] -->
## Scripts

### Rechercher tous les fichiers dupliqués récursivement dans un répertoire donné

<!-- [common] -->
```bash
find . -type f -printf '%p/ %f\n' | sort -k2 | uniq -f1 --all-repeated=separate
```

<!-- [en] -->
### Search all duplicate directory recursively in given directory

<!-- [fr] -->
### Rechercher tous les répertoires dupliqués récursivement dans un répertoire donné

<!-- [common] -->
```bash
find . -type d -printf '%p/ %f\n' | sort -k2 | uniq -f1 --all-repeated=separate
```

<!-- [en] -->
## Networking

Show all open port

<!-- [fr] -->
## Réseau

Afficher tous les ports ouverts

<!-- [common] -->
```bash
sudo lsof -i -P -n | grep LISTEN
```

<!-- [en] -->
or

<!-- [fr] -->
ou

<!-- [common] -->
```bash
sudo netstat -lpnt | grep LISTEN
```

<!-- [en] -->
or

<!-- [fr] -->
ou

<!-- [common] -->
```bash
sudo ss -lpnt | grep LISTEN
```

<!-- [en] -->
## Git

### Configuration

Prefer to use Vim when editing?

<!-- [fr] -->
## Git

### Configuration

Préférez-vous utiliser Vim pour l'édition ?

<!-- [common] -->
```bash
git config --global core.editor "vim"
```

<!-- [en] -->
Prefer to use Meld when resolving conflit?

<!-- [fr] -->
Préférez-vous utiliser Meld pour résoudre les conflits ?

<!-- [common] -->
```bash
git config --global merge.tool meld
```

<!-- [en] -->
Prefer to us Meld to show difference?

<!-- [fr] -->
Préférez-vous utiliser Meld pour afficher les différences ?

<!-- [common] -->
```bash
git config --global diff.tool meld
git config --global difftool.prompt false
```

<!-- [en] -->
### Retroactively applying format code to existing branches

Adapt this command to your situation, this is an example:

<!-- [fr] -->
### Appliquer rétroactivement le formatage du code sur des branches existantes

Adaptez cette commande à votre situation, ceci est un exemple :

<!-- [common] -->
```bash
git rebase --strategy-option=theirs --exec 'cd ../../ && ./script/maintenance/black.sh ./addons/ERPLibre_erplibre_theme_addons/website_snippet_all/ && cd - && git add --all && git commit --amend --no-edit' HEAD~47
```

<!-- [en] -->
### Unshallow git

By example, the repo Odoo use a depth clone. If you need all the clone repo, use this command on right directory:

<!-- [fr] -->
### Récupérer l'historique complet de git (unshallow)

Par exemple, le dépôt Odoo utilise un clone avec profondeur limitée. Si vous avez besoin du dépôt complet, utilisez cette commande dans le bon répertoire :

<!-- [common] -->
```bash
git fetch REMOTE --unshallow
```

<!-- [en] -->
### Amend several commits in Git to change author

<!-- [fr] -->
### Modifier plusieurs commits dans Git pour changer l'auteur

<!-- [common] -->
```bash
git rebase -i HEAD~4 -x "git commit --amend --author 'Author Name <author.name@mail.com>' --no-edit"
```

<!-- [en] -->
### Cherry-pick a merged commit with conflict

<!-- [fr] -->
### Cherry-pick d'un commit fusionné avec conflit

<!-- [common] -->
```bash
git cherry-pick -m 1 --strategy-option theirs HASH
```

<!-- [en] -->
## git update manifest

### Service git-daemon already running, error bind or Error fatal: unable to allocate any listen sockets on port 9418

This error occur when force stop (ctrl+c) a script like `./script/manifest/update_manifest_local_dev.sh`

The error into console is similar to `Could not bind to 0.0.0.0: Address already in use`

<!-- [fr] -->
## git update manifest

### Service git-daemon déjà en cours d'exécution, erreur bind ou Erreur fatale : impossible d'allouer des sockets d'écoute sur le port 9418

Cette erreur survient lors de l'arrêt forcé (ctrl+c) d'un script comme `./script/manifest/update_manifest_local_dev.sh`

L'erreur dans la console ressemble à `Could not bind to 0.0.0.0: Address already in use`

<!-- [common] -->
```bash
pkill -f git-daemon
```

<!-- [en] -->
## git-repo

### error.GitError fatal bad revision

Example:

<!-- [fr] -->
## git-repo

### error.GitError fatal bad revision

Exemple :

<!-- [common] -->
```
error.GitError: manifests rev-list (u'^2736dfd46e8a30cf59a9cd6e93d9e56e87021f2a', 'HEAD', '--'): fatal: bad revision 'HEAD'
```

<!-- [en] -->
Did you modify files in .repo?

To reset files from your branch into .repo:

<!-- [fr] -->
Avez-vous modifié des fichiers dans .repo ?

Pour réinitialiser les fichiers de votre branche dans .repo :

<!-- [common] -->
```bash
cd .repo/manifests
git branch -av
> remotes/m/rel/8953/zd552kl/7.1.1-11.40.208                -> origin/rel/8953/zd552kl/7.1.1-11.40.208
> remotes/origin/dev/ze550kl/asus/5.0.0-20150208            11a37fe set dev/ze550kl/asus/5.0.0-20150208
> remotes/origin/rel/8953/zd552kl/7.1.1-11.40.208           2736dfd Remove opencv3 from the manifest
# To reset the "remotes/origin" use the same as "remotes/m"
git reset --hard REF_OF_REMOTES/m
> git reset --hard remotes/origin/rel/8953/zd552kl/7.1.1-11.40.208
```

<!-- [en] -->
### fatal: GitCommandError: git command failure

Example of error after an installation with git-repo:

<!-- [fr] -->
### fatal: GitCommandError: git command failure

Exemple d'erreur après une installation avec git-repo :

<!-- [common] -->
```
raise GitCommandError(
git_command.GitCommandError: GitCommandError: git command failure
    Project: manifests
    Args: rev-list ^e96a83f03665ecc1b151331776909be32d5e2c7b HEAD --
    Stdout:
None
    Stderr:
fatal: bad revision 'HEAD'
Skipped fetching project manifests (already have persistent ref)
fatal: GitCommandError: git command failure
    Project: manifests
    Args: rev-list ^HEAD c8e64956f188f77abcfa7ff0e764af97162d3071 --
    Stdout:
None
    Stderr:
fatal: bad revision '^HEAD'
```

<!-- [en] -->
Solution: Check files into directory `cd .repo/manifests` with commande `git status`. If
you
have some differences in stage, you can try `git reset --hard` and redo the
installation.

If it's not working, re-clone the repo and do a fresh installation.

## OSX installation

### Docker installation

This guide works in the past, but it's now broken

<!-- [fr] -->
Solution : Vérifiez les fichiers dans le répertoire `cd .repo/manifests` avec la commande `git status`. Si
vous
avez des différences en staging, vous pouvez essayer `git reset --hard` et refaire
l'installation.

Si cela ne fonctionne pas, re-clonez le dépôt et faites une installation fraîche.

## Installation OSX

### Installation Docker

Ce guide fonctionnait dans le passé, mais il est maintenant cassé

<!-- [common] -->
```bash
echo  "\n--- Installing docker --"
brew install minikube docker docker-compose docker-machine
brew cask install virtualbox
docker-machine create --driver virtualbox default
docker-machine env default
eval "$(docker-machine env default)"
```

<!-- [en] -->
### Run error `current limit exceeds maximum limit`

When you got

<!-- [fr] -->
### Erreur d'exécution `current limit exceeds maximum limit`

Lorsque vous obtenez

<!-- [common] -->
```
File "/Users/test/Desktop/ERPLibre/odoo/odoo/service/server.py", line 83, in set_limit_memory_hard
resource.setrlimit(rlimit, (config['limit_memory_hard'], hard))
ValueError: current limit exceeds maximum limit
```

<!-- [en] -->
Add line at the end of config.conf

<!-- [fr] -->
Ajoutez la ligne à la fin de config.conf

<!-- [common] -->
```
limit_memory_hard = 0
```

<!-- [en] -->
## Docker - All interface bind docker

### Error non-overlapping IPv4 address pool

You got this error when you start a
docker-compose:
`ERROR: could not find an available, non-overlapping IPv4 address pool among the defaults to assign to the network`

It's because the subnet is limited, you need to change it.

Create a subnet :

<!-- [fr] -->
## Docker - Liaison de toutes les interfaces docker

### Erreur non-overlapping IPv4 address pool

Vous obtenez cette erreur lorsque vous démarrez un
docker-compose :
`ERROR: could not find an available, non-overlapping IPv4 address pool among the defaults to assign to the network`

C'est parce que le sous-réseau est limité, vous devez le changer.

Créez un sous-réseau :

<!-- [common] -->
```bash
docker network create localnetwork --subnet 10.0.1.0/24
```

<!-- [en] -->
Create a new file `docker-compose.override.yml` at the root of ERPLibre, at same level of your docker-compose.yml and
fill with:

<!-- [fr] -->
Créez un nouveau fichier `docker-compose.override.yml` à la racine d'ERPLibre, au même niveau que votre docker-compose.yml et
remplissez avec :

<!-- [common] -->
```yaml
version: '3'
networks:
    default:
        external:
            name: localnetwork
```

<!-- [en] -->
## Pycharm inotify watches limit Linux

Please read this: https://intellij-support.jetbrains.com/hc/en-us/articles/15268113529362-Inotify-Watches-Limit-Linux

Validate it works:

<!-- [fr] -->
## Limite inotify watches de Pycharm sous Linux

Veuillez lire ceci : https://intellij-support.jetbrains.com/hc/en-us/articles/15268113529362-Inotify-Watches-Limit-Linux

Validez que cela fonctionne :

<!-- [common] -->
```bash
cat /proc/sys/fs/inotify/max_user_watches
```

<!-- [en] -->
Tips, when doing `sudo sysctl -p --system`, validate the order of the process, another process can overwrite your new
value.

## How killing all process from selenium

<!-- [fr] -->
Astuce : lorsque vous exécutez `sudo sysctl -p --system`, validez l'ordre des processus, un autre processus peut écraser votre nouvelle valeur.

## Comment tuer tous les processus de selenium

<!-- [common] -->
```bash
pkill -f "firefox.*--marionette"
```
