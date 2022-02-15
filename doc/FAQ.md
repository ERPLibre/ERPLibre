# FAQ

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
