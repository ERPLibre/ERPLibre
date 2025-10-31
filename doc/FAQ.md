# FAQ

## Into execution

### wkthmltopdf TimeoutError

If you find this bug on server log :
`odoo.addons.base.models.ir_actions_report: wkhtmltopdf: Exit with code 1 due to network error: TimeoutError`

Into configuration, technique, go to ir.config_parameter (system parameter) and add configuration :
```
key : report.url
value : http://127.0.0.1:8069
```

## Scripting

### Search all duplicate file recursively in given directory

```bash
find . -type f -printf '%p/ %f\n' | sort -k2 | uniq -f1 --all-repeated=separate
```

### Search all duplicate directory recursively in given directory

```bash
find . -type d -printf '%p/ %f\n' | sort -k2 | uniq -f1 --all-repeated=separate
```

## Networking

Show all open port

```bash
sudo lsof -i -P -n | grep LISTEN
```

or

```bash
sudo netstat -lpnt | grep LISTEN
```

or

```bash
sudo ss -lpnt | grep LISTEN
```

## Git

### Configuration

Prefer to use Vim when editing?

```bash
git config --global core.editor "vim"
```

Prefer to use Meld when resolving conflit?

```bash
git config --global merge.tool meld
```

Prefer to us Meld to show difference?

```bash
git config --global diff.tool meld
git config --global difftool.prompt false
```

### Retroactively applying format code to existing branches

Adapt this command to your situation, this is an example:

```bash
git rebase --strategy-option=theirs --exec 'cd ../../ && ./script/maintenance/black.sh ./addons/ERPLibre_erplibre_theme_addons/website_snippet_all/ && cd - && git add --all && git commit --amend --no-edit' HEAD~47
```

### Unshallow git

By example, the repo Odoo use a depth clone. If you need all the clone repo, use this command on right directory:

```bash
git fetch REMOTE --unshallow
```

### Amend several commits in Git to change author

```bash
git rebase -i HEAD~4 -x "git commit --amend --author 'Author Name <author.name@mail.com>' --no-edit"
```

### Cherry-pick a merged commit with conflict

```bash
git cherry-pick -m 1 --strategy-option theirs HASH
```

## git update manifest

### Service git-daemon already running, error bind or Error fatal: unable to allocate any listen sockets on port 9418

This error occur when force stop (ctrl+c) a script like `./script/manifest/update_manifest_local_dev.sh`

The error into console is similar to `Could not bind to 0.0.0.0: Address already in use`

```bash
pkill -f git-daemon
```

## git-repo

### error.GitError fatal bad revision

Example:

```
error.GitError: manifests rev-list (u'^2736dfd46e8a30cf59a9cd6e93d9e56e87021f2a', 'HEAD', '--'): fatal: bad revision 'HEAD'
```

Did you modify files in .repo?

To reset files from your branch into .repo:

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

### fatal: GitCommandError: git command failure

Example of error after an installation with git-repo:

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

Solution: Check files into directory `cd .repo/manifests` with commande `git status`. If
you
have some differences in stage, you can try `git reset --hard` and redo the
installation.

If it's not working, re-clone the repo and do a fresh installation.

## OSX installation

### Docker installation

This guide works in the past, but it's now broken

```bash
echo  "\n--- Installing docker --"
brew install minikube docker docker-compose docker-machine
brew cask install virtualbox
docker-machine create --driver virtualbox default
docker-machine env default
eval "$(docker-machine env default)"
```

### Run error `current limit exceeds maximum limit`

When you got

```
File "/Users/test/Desktop/ERPLibre/odoo/odoo/service/server.py", line 83, in set_limit_memory_hard
resource.setrlimit(rlimit, (config['limit_memory_hard'], hard))
ValueError: current limit exceeds maximum limit
```

Add line at the end of config.conf

```
limit_memory_hard = 0
```

## Docker - All interface bind docker

### Error non-overlapping IPv4 address pool

You got this error when you start a
docker-compose:
`ERROR: could not find an available, non-overlapping IPv4 address pool among the defaults to assign to the network`

It's because the subnet is limited, you need to change it.

Create a subnet :

```bash
docker network create localnetwork --subnet 10.0.1.0/24
```

Create a new file `docker-compose.override.yml` at the root of ERPLibre, at same level of your docker-compose.yml and
fill with:

```yaml
version: '3'
networks:
    default:
        external:
            name: localnetwork
```

## Pycharm inotify watches limit Linux

Please read this: https://intellij-support.jetbrains.com/hc/en-us/articles/15268113529362-Inotify-Watches-Limit-Linux

Validate it works:

```bash
cat /proc/sys/fs/inotify/max_user_watches
```

Tips, when doing `sudo sysctl -p --system`, validate the order of the process, another process can overwrite your new
value.

## How killing all process from selenium

```bash
pkill -f "firefox.*--marionette"
```
