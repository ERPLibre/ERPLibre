# git-repo
This is a guide to understand git-repo. Scripts in ERPLibre use git-repo automatically.

[git-repo of Google](https://code.google.com/archive/p/git-repo) is used to manage all git repository under licence [Apache-2.0](https://www.apache.org/licenses/LICENSE-2.0.html).

## Setup repo
```bash
curl https://storage.googleapis.com/git-repo-downloads/repo > ./venv/repo
```

## prod
```bash
./venv/repo init -u http://git.erplibre.ca/ERPLibre -b 12.0_repo
./venv/repo sync
```

## dev
```bash
./venv/repo init -u http://git.erplibre.ca/ERPLibre -b 12.0_repo -m ./manifest/default.dev.xml
./venv/repo sync
```

## dev locally
[Guide to setup locally git](https://railsware.com/blog/taming-the-git-daemon-to-quickly-share-git-repository/).
```bash
git daemon --base-path=. --export-all --reuseaddr --informative-errors --verbose &

./venv/repo init -u git://127.0.0.1:9418/ -b $(git rev-parse --abbrev-ref HEAD) -m ./manifest/default.dev.xml
./venv/repo sync -m ./manifest/default.dev.xml
```

# Create Manifest
A [Manifest](https://gerrit.googlesource.com/git-repo/+/master/docs/manifest-format.md), is a XML file managed by git-repo to generate repo.

## Make a new version of prod
Freezes all repo, from dev to prod.

This will add revision git hash in the Manifest.
```bash
./venv/repo manifest -r -o ./manifest/default.xml
```
Do your commit.
```bash
git commit -am "[#ticket] subject: short sentence"
```

## Create a dev version
```bash
./venv/repo manifest -o ./manifest/default.dev.xml
```
Do your commit.
```bash
git commit -am "[#ticket] subject: short sentence"
```